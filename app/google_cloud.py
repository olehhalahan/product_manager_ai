"""
Google Cloud project alignment for OAuth (login + Merchant Center).

Use one GCP project for:
  - OAuth 2.0 Client ID (Web application) → GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET
  - Enabled APIs: Merchant API, etc.
  - OAuth consent screen scopes

Set GOOGLE_CLOUD_PROJECT_ID to the same project ID shown in Google Cloud Console
(top bar or IAM). Optional but recommended for clarity and admin UI.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

_log = logging.getLogger("uvicorn.error")


def _strip_oauth_value(val: Optional[str]) -> str:
    """Trim whitespace and accidental quotes from .env copy-paste."""
    if not val:
        return ""
    s = str(val).strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()
    return s


def get_normalized_google_oauth_credentials() -> tuple[str, str]:
    """GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET as actually used by OAuth (cleaned)."""
    gid = _strip_oauth_value(os.getenv("GOOGLE_CLIENT_ID"))
    gsec = _strip_oauth_value(os.getenv("GOOGLE_CLIENT_SECRET"))
    return gid, gsec


def get_google_cloud_project_id() -> Optional[str]:
    """GCP project ID from env (not numeric project number)."""
    raw = (os.getenv("GOOGLE_CLOUD_PROJECT_ID") or os.getenv("GCP_PROJECT_ID") or "").strip()
    return raw or None


def get_google_oauth_env_summary() -> Dict[str, Any]:
    """Non-secret summary for admin UI (masked client id)."""
    gid, _gsec = get_normalized_google_oauth_credentials()
    has_secret = bool(_gsec)
    hint = ""
    if len(gid) > 24:
        hint = gid[:12] + "…" + gid[-16:]
    elif gid:
        hint = gid[:6] + "…"
    return {
        "google_cloud_project_id": get_google_cloud_project_id(),
        "oauth_client_configured": bool(gid and has_secret),
        "oauth_client_id_hint": hint or None,
    }


def log_google_cloud_startup() -> None:
    """Log once at startup so deploys confirm which GCP project OAuth targets."""
    s = get_google_oauth_env_summary()
    if not s["oauth_client_configured"]:
        return
    pid = s.get("google_cloud_project_id")
    hint = s.get("oauth_client_id_hint") or "?"
    if pid:
        _log.info("Google OAuth: GCP project=%s, client_id=%s", pid, hint)
    else:
        _log.info(
            "Google OAuth: client_id=%s (set GOOGLE_CLOUD_PROJECT_ID to your Console project id)",
            hint,
        )
