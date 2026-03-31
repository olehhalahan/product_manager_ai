"""Render HTML to PNG via headless Chromium (Playwright)."""

from __future__ import annotations

import concurrent.futures
import logging
from typing import Optional

_log = logging.getLogger("uvicorn.error")

_BANNER_W = 1200
_BANNER_H = 630


def _html_to_png_bytes_worker(
    html: str,
    *,
    width: int,
    height: int,
    timeout_ms: int,
) -> Optional[bytes]:
    """Playwright sync API must run off the asyncio event loop (FastAPI/uvicorn)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _log.warning(
            "playwright package missing — install playwright and run: python -m playwright install chromium"
        )
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": width, "height": height})
                page.set_content(html, wait_until="load", timeout=timeout_ms)
                return page.screenshot(
                    type="png",
                    clip={"x": 0, "y": 0, "width": width, "height": height},
                    timeout=timeout_ms,
                )
            finally:
                browser.close()
    except Exception:
        _log.exception("blog banner playwright screenshot failed")
        return None


def html_to_png_bytes(
    html: str,
    *,
    width: int = _BANNER_W,
    height: int = _BANNER_H,
    timeout_ms: int = 45_000,
) -> Optional[bytes]:
    """Run Chromium capture in a worker thread so sync Playwright is safe under async ASGI."""
    timeout_sec = max(60.0, (timeout_ms / 1000.0) + 30.0)

    def _job() -> Optional[bytes]:
        return _html_to_png_bytes_worker(html, width=width, height=height, timeout_ms=timeout_ms)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_job)
            return fut.result(timeout=timeout_sec)
    except concurrent.futures.TimeoutError:
        _log.error("blog banner screenshot timed out (%.1fs)", timeout_sec)
        return None
    except Exception:
        _log.exception("blog banner screenshot thread failed")
        return None


def banner_dimensions() -> tuple[int, int]:
    return _BANNER_W, _BANNER_H
