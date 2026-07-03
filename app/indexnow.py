"""IndexNow URL submission for Bing and compatible search engines."""
from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib.parse import urlparse

import httpx

from .public_urls import collect_public_page_urls, filter_production_public_urls, production_base_url

logger = logging.getLogger("cartozo.indexnow")

INDEXNOW_ENDPOINT = "https://api.indexnow.org/IndexNow"
DEFAULT_BATCH_SIZE = 100


def indexnow_enabled() -> bool:
    return os.getenv("INDEXNOW_ENABLED", "").strip().lower() in ("1", "true", "yes")


def indexnow_key() -> str:
    return (os.getenv("INDEXNOW_KEY") or "").strip()


def indexnow_host() -> str:
    base = production_base_url() or site_base_url().rstrip("/")
    return (urlparse(base).hostname or "cartozo.ai").lower()


def indexnow_key_location() -> str:
    base = production_base_url() or site_base_url().rstrip("/")
    key = indexnow_key()
    return f"{base}/{key}.txt"


def build_indexnow_payload(urls: list[str]) -> dict[str, Any]:
    return {
        "host": indexnow_host(),
        "key": indexnow_key(),
        "keyLocation": indexnow_key_location(),
        "urlList": urls,
    }


def submit_indexnow_urls(urls: list[str], *, db: Any = None) -> dict[str, Any]:
    """
    Submit canonical public URLs to IndexNow.

    Returns a result dict with accepted/rejected/failed counts and HTTP status.
    """
    if not indexnow_enabled():
        return {
            "ok": False,
            "skipped": True,
            "reason": "INDEXNOW_ENABLED is not true",
            "submitted": 0,
            "rejected": len(urls),
            "failed": [],
        }

    key = indexnow_key()
    if not key:
        return {
            "ok": False,
            "skipped": True,
            "reason": "INDEXNOW_KEY is not configured",
            "submitted": 0,
            "rejected": len(urls),
            "failed": [],
        }

    if not production_base_url():
        return {
            "ok": False,
            "skipped": True,
            "reason": "DEPLOY_URL must be a production https origin",
            "submitted": 0,
            "rejected": len(urls),
            "failed": [],
        }

    accepted, rejected = filter_production_public_urls(urls)
    if not accepted:
        return {
            "ok": False,
            "submitted": 0,
            "rejected": len(rejected),
            "failed": [],
            "rejected_urls": rejected[:20],
        }

    failed: list[str] = []
    submitted = 0
    last_status = 0
    last_body = ""

    for i in range(0, len(accepted), DEFAULT_BATCH_SIZE):
        batch = accepted[i : i + DEFAULT_BATCH_SIZE]
        payload = build_indexnow_payload(batch)
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    INDEXNOW_ENDPOINT,
                    headers={"Content-Type": "application/json; charset=utf-8"},
                    content=json.dumps(payload),
                )
            last_status = resp.status_code
            last_body = (resp.text or "")[:500]
            if resp.status_code in (200, 202):
                submitted += len(batch)
                logger.info("IndexNow batch submitted count=%s status=%s", len(batch), resp.status_code)
            else:
                failed.extend(batch)
                logger.warning(
                    "IndexNow batch failed status=%s body=%s urls=%s",
                    resp.status_code,
                    last_body,
                    len(batch),
                )
        except Exception as exc:
            failed.extend(batch)
            logger.exception("IndexNow submission error: %s", exc)

    result = {
        "ok": submitted > 0 and not failed,
        "submitted": submitted,
        "rejected": len(rejected),
        "failed_count": len(failed),
        "failed_urls": failed[:50],
        "rejected_urls": rejected[:50],
        "http_status": last_status,
        "http_body": last_body,
    }
    return result


def collect_all_public_urls(db: Any) -> list[str]:
    return collect_public_page_urls(db, include_blog=True)


def submit_all_public_urls(db: Any) -> dict[str, Any]:
    urls = collect_all_public_urls(db)
    return submit_indexnow_urls(urls, db=db)


def site_base_url() -> str:
    from .seo import site_base_url as _base

    return _base()
