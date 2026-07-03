"""Middleware — record public page visits with bot/human classification."""
from __future__ import annotations

import logging
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .security import _client_ip
from .traffic import (
    classify_referrer,
    classify_user_agent,
    hash_client_ip,
    parse_referrer_domain,
    should_track_path,
)

logger = logging.getLogger("cartozo.traffic")


class TrafficAnalyticsMiddleware(BaseHTTPMiddleware):
    """Persist classified GET visits on public marketing paths."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        path = request.url.path or "/"
        if response.status_code != 200 or not should_track_path(path, request.method):
            return response
        accept = (request.headers.get("accept") or "").lower()
        if "text/html" not in accept and "*/*" not in accept:
            return response
        try:
            ua = request.headers.get("user-agent") or ""
            ref = request.headers.get("referer") or request.headers.get("referrer") or ""
            cls = classify_user_agent(ua)
            from .db import get_db
            from .services.db_repository import record_site_visit

            with get_db() as db:
                record_site_visit(
                    db,
                    path=path.split("?", 1)[0],
                    visitor_class=cls.visitor_class,
                    bot_name=cls.bot_name,
                    user_agent=ua[:512],
                    referrer=ref[:512],
                    referrer_domain=parse_referrer_domain(ref) or classify_referrer(ref),
                    ip_hash=hash_client_ip(_client_ip(request)),
                )
        except Exception:
            logger.exception("Failed to record site visit for %s", path)
        return response
