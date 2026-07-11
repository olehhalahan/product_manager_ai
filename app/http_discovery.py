"""Shared GET/HEAD helpers for public discovery endpoints."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response


def discovery_response(
    request: Request,
    body: str | bytes,
    *,
    media_type: str,
) -> Response:
    """Return GET body or HEAD with matching status, type, and Content-Length."""
    payload = body.encode("utf-8") if isinstance(body, str) else body
    if request.method == "HEAD":
        return Response(
            content=b"",
            media_type=media_type,
            headers={"Content-Length": str(len(payload))},
        )
    if isinstance(body, str):
        return PlainTextResponse(body, media_type=media_type)
    return Response(content=payload, media_type=media_type)
