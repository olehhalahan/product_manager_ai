"""Render HTML to PNG via headless Chromium (Playwright)."""

from __future__ import annotations

import logging
from typing import Optional

_log = logging.getLogger("uvicorn.error")

_BANNER_W = 1200
_BANNER_H = 630


def html_to_png_bytes(
    html: str,
    *,
    width: int = _BANNER_W,
    height: int = _BANNER_H,
    timeout_ms: int = 45_000,
) -> Optional[bytes]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _log.warning("playwright not installed; skip blog banner PNG render")
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": width, "height": height})
                page.set_content(html, wait_until="load", timeout=timeout_ms)
                png = page.screenshot(
                    type="png",
                    clip={"x": 0, "y": 0, "width": width, "height": height},
                    timeout=timeout_ms,
                )
                return png
            finally:
                browser.close()
    except Exception:
        _log.exception("blog banner playwright screenshot failed")
        return None


def banner_dimensions() -> tuple[int, int]:
    return _BANNER_W, _BANNER_H
