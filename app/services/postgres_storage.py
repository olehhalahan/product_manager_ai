"""
Database-backed storage for batches. Reuses InMemoryStorage processing logic.
Works with SQLite or PostgreSQL via db_repository.
"""
from datetime import datetime, timezone
from typing import Dict, Optional, List

from ..models import (
    Batch,
    BatchStatus,
    NormalizedProduct,
    ProductResult,
    ProductAction,
    ProductStatus,
    BatchSummary,
)
from ..db import get_db
from ..services.db_repository import (
    create_batch as db_create_batch,
    get_batch as db_get_batch,
    update_batch as db_update_batch,
    mark_batch_merchant_pushed as db_mark_batch_merchant_pushed,
)
from .ai_provider import AIProvider
from .positioning import apply_feed_optimization
from .validator import validate_gmc


def _products_to_json(products: List[ProductResult]) -> list:
    """Serialize ProductResult list to JSON-serializable dicts."""
    return [p.model_dump(mode="json") for p in products]


def _products_from_json(data: list) -> List[ProductResult]:
    """Deserialize ProductResult list from JSON."""
    return [ProductResult.model_validate(p) for p in data]


class PostgresStorage:
    """
    PostgreSQL-backed storage. Batches are persisted to DB.
    Processing logic is the same as InMemoryStorage (synchronous).
    """

    def __init__(self) -> None:
        self._ai = AIProvider()
        self.default_target_language: str = "en"

    def create_batch(
        self,
        batch_id: str,
        products: List[NormalizedProduct],
        actions: Dict[str, ProductAction],
        product_type: str = "standard",
        user_email: Optional[str] = None,
    ) -> None:
        results: List[ProductResult] = []
        for p in products:
            action = actions.get(p.id, ProductAction.SKIP)
            results.append(
                ProductResult(
                    product=p,
                    action=action,
                    status=ProductStatus.PENDING,
                )
            )
        products_json = _products_to_json(results)
        with get_db() as db:
            db_create_batch(
                db,
                batch_id,
                products_json,
                BatchStatus.NORMALIZED.value,
                product_type,
                user_email=user_email,
            )

    def get_batch(self, batch_id: str) -> Optional[Batch]:
        with get_db() as db:
            row = db_get_batch(db, batch_id)
        if not row:
            return None
        products = _products_from_json(row["products_json"])
        return Batch(
            id=row["batch_id"],
            status=BatchStatus(row["status"]),
            products=products,
            product_type=row.get("product_type", "standard"),
            client_id=row.get("client_id"),
            total_cost_usd=row.get("total_cost_usd", 0.0),
            created_at=row.get("created_at"),
            completed_at=row.get("completed_at"),
            user_email=row.get("user_email") or None,
            merchant_pushed_at=row.get("merchant_pushed_at"),
            closed_at=row.get("closed_at"),
        )

    def _save_batch(self, batch: Batch) -> None:
        products_json = _products_to_json(batch.products)
        with get_db() as db:
            db_update_batch(
                db,
                batch.id,
                batch.status.value,
                products_json,
                completed_at=(batch.status == BatchStatus.READY_FOR_REVIEW),
            )

    def process_batch_synchronously(
        self, batch_id: str, optimize_fields: Optional[set] = None
    ) -> None:
        if optimize_fields is None:
            optimize_fields = {"title", "description"}

        batch = self.get_batch(batch_id)
        if not batch:
            return

        batch.status = BatchStatus.PROCESSING
        self._save_batch(batch)

        for result in batch.products:
            if result.action == ProductAction.SKIP:
                result.status = ProductStatus.SKIPPED
                continue

            result.status = ProductStatus.PROCESSING
            try:
                result.original_score = self._ai.score_optimization(
                    result.product, result.product.title, result.product.description
                )

                if result.action in {
                    ProductAction.GENERATE_NEW,
                    ProductAction.IMPROVE_EXISTING,
                    ProductAction.MANUAL_REVIEW,
                    ProductAction.TRANSLATE,
                }:
                    apply_feed_optimization(
                        result, self._ai, optimize_fields, positioning_mode="fast"
                    )

                if result.action == ProductAction.TRANSLATE:
                    title_source = result.optimized_title or result.product.title
                    desc_source = result.optimized_description or result.product.description
                    if title_source:
                        result.translated_title = self._ai.translate_text(
                            title_source,
                            target_language=self.default_target_language,
                        )
                    if desc_source:
                        result.translated_description = self._ai.translate_text(
                            desc_source,
                            target_language=self.default_target_language,
                        )

                result.score = self._ai.score_optimization(
                    result.product, result.optimized_title, result.optimized_description
                )
                if (
                    result.positioning
                    and result.positioning.get("routing") == "skipped_already_strong"
                ):
                    result.score = result.original_score

                gmc_errs, gmc_warns = validate_gmc(result, product_type=batch.product_type)
                result.gmc_errors = gmc_errs
                result.gmc_warnings = gmc_warns

                all_issues = gmc_errs + gmc_warns
                if gmc_errs:
                    result.status = ProductStatus.NEEDS_REVIEW
                    result.notes = "; ".join(all_issues)
                elif gmc_warns:
                    result.status = ProductStatus.DONE
                    result.notes = "; ".join(all_issues)
                else:
                    result.status = ProductStatus.DONE
            except Exception as exc:  # noqa: BLE001
                result.status = ProductStatus.FAILED
                result.error = str(exc)

        batch.status = BatchStatus.READY_FOR_REVIEW
        self._save_batch(batch)

    def mark_batch_merchant_pushed(self, batch_id: str) -> None:
        with get_db() as db:
            db_mark_batch_merchant_pushed(db, batch_id)

    def regenerate_products(self, batch_id: str, product_ids: List[str]) -> None:
        batch = self.get_batch(batch_id)
        if not batch:
            return

        for result in batch.products:
            if result.product.id not in product_ids:
                continue

            try:
                apply_feed_optimization(
                    result,
                    self._ai,
                    {"title", "description"},
                    positioning_mode="deep",
                )

                if result.action == ProductAction.TRANSLATE:
                    title_source = result.optimized_title or result.product.title
                    desc_source = result.optimized_description or result.product.description
                    if title_source:
                        result.translated_title = self._ai.translate_text(
                            title_source,
                            target_language=self.default_target_language,
                        )
                    if desc_source:
                        result.translated_description = self._ai.translate_text(
                            desc_source,
                            target_language=self.default_target_language,
                        )

                result.score = self._ai.score_optimization(
                    result.product, result.optimized_title, result.optimized_description
                )

                gmc_errs, gmc_warns = validate_gmc(result, product_type=batch.product_type)
                result.gmc_errors = gmc_errs
                result.gmc_warnings = gmc_warns

                all_issues = gmc_errs + gmc_warns
                if gmc_errs:
                    result.status = ProductStatus.NEEDS_REVIEW
                    result.notes = "; ".join(all_issues)
                elif gmc_warns:
                    result.status = ProductStatus.DONE
                    result.notes = "; ".join(all_issues)
                else:
                    result.status = ProductStatus.DONE
                    result.notes = None
                    result.error = None
            except Exception as exc:  # noqa: BLE001
                result.status = ProductStatus.FAILED
                result.error = str(exc)

        self._save_batch(batch)

    def get_batch_summary(self, batch_id: str) -> Optional[BatchSummary]:
        batch = self.get_batch(batch_id)
        if not batch:
            return None

        total = len(batch.products)
        done = sum(1 for r in batch.products if r.status == ProductStatus.DONE)
        failed = sum(1 for r in batch.products if r.status == ProductStatus.FAILED)
        skipped = sum(1 for r in batch.products if r.status == ProductStatus.SKIPPED)
        needs_review = sum(1 for r in batch.products if r.status == ProductStatus.NEEDS_REVIEW)

        return BatchSummary(
            id=batch.id,
            status=batch.status,
            total=total,
            done=done,
            failed=failed,
            skipped=skipped,
            needs_review=needs_review,
        )
