from typing import Dict, Optional, List

from ..models import (
    Batch,
    BatchStatus,
    NormalizedProduct,
    ProductResult,
    ProductAction,
    ProductStatus,
)
from .ai_provider import AIProvider
from .validator import validate_product_result


class InMemoryStorage:
    """
    Simple in-memory storage + synchronous processing for v1.
    Later this can be replaced with Postgres + Celery workers.
    """

    def __init__(self) -> None:
        self._batches: Dict[str, Batch] = {}
        self._ai = AIProvider()
        self.default_target_language: str = "en"

    def create_batch(
        self,
        batch_id: str,
        products: List[NormalizedProduct],
        actions: Dict[str, ProductAction],
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

        self._batches[batch_id] = Batch(
            id=batch_id,
            status=BatchStatus.NORMALIZED,
            products=results,
        )

    def get_batch(self, batch_id: str) -> Optional[Batch]:
        return self._batches.get(batch_id)

    def process_batch_synchronously(
        self, batch_id: str, optimize_fields: Optional[set] = None
    ) -> None:
        if optimize_fields is None:
            optimize_fields = {"title", "description"}

        batch = self._batches.get(batch_id)
        if not batch:
            return

        batch.status = BatchStatus.PROCESSING

        for result in batch.products:
            if result.action == ProductAction.SKIP:
                result.status = ProductStatus.SKIPPED
                continue

            result.status = ProductStatus.PROCESSING
            try:
                if result.action in {
                    ProductAction.GENERATE_NEW,
                    ProductAction.IMPROVE_EXISTING,
                    ProductAction.MANUAL_REVIEW,
                    ProductAction.TRANSLATE,
                }:
                    if "title" in optimize_fields:
                        result.optimized_title = self._ai.generate_title(result.product)
                    if "description" in optimize_fields:
                        result.optimized_description = self._ai.generate_description(result.product)

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

                errors = validate_product_result(result)
                if errors:
                    result.status = ProductStatus.NEEDS_REVIEW
                    result.notes = "; ".join(errors)
                else:
                    result.status = ProductStatus.DONE
            except Exception as exc:  # noqa: BLE001
                result.status = ProductStatus.FAILED
                result.error = str(exc)

        batch.status = BatchStatus.READY_FOR_REVIEW

    def regenerate_products(self, batch_id: str, product_ids: List[str]) -> None:
        batch = self._batches.get(batch_id)
        if not batch:
            return

        for result in batch.products:
            if result.product.id not in product_ids:
                continue

            try:
                result.optimized_title = self._ai.generate_title(result.product)
                result.optimized_description = self._ai.generate_description(result.product)

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

                errors = validate_product_result(result)
                if errors:
                    result.status = ProductStatus.NEEDS_REVIEW
                    result.notes = "; ".join(errors)
                else:
                    result.status = ProductStatus.DONE
                    result.notes = None
                    result.error = None
            except Exception as exc:  # noqa: BLE001
                result.status = ProductStatus.FAILED
                result.error = str(exc)

    def get_batch_summary(self, batch_id: str):
        batch = self._batches.get(batch_id)
        if not batch:
            return None

        total = len(batch.products)
        done = sum(1 for r in batch.products if r.status == ProductStatus.DONE)
        failed = sum(1 for r in batch.products if r.status == ProductStatus.FAILED)
        skipped = sum(1 for r in batch.products if r.status == ProductStatus.SKIPPED)
        needs_review = sum(1 for r in batch.products if r.status == ProductStatus.NEEDS_REVIEW)

        from ..models import BatchSummary

        return BatchSummary(
            id=batch.id,
            status=batch.status,
            total=total,
            done=done,
            failed=failed,
            skipped=skipped,
            needs_review=needs_review,
        )

