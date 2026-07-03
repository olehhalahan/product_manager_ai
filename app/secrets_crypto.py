"""
Encrypt sensitive settings at rest (OpenAI key, WayForPay secret, cron secret).

Values are stored as ``enc:v1:<fernet-token>``. Legacy plaintext values are still
readable; use ``migrate_plaintext_secrets`` to re-encrypt existing rows.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

logger = logging.getLogger("uvicorn.error")

ENC_PREFIX = "enc:v1:"

ENCRYPTED_SETTING_KEYS = frozenset(
    {
        "openai_api_key",
        "wayforpay_secret_key",
        "writter_auto_cron_secret",
    }
)


def _fernet():
    from cryptography.fernet import Fernet

    raw = (os.getenv("SECRETS_ENCRYPTION_KEY") or "").strip()
    if not raw:
        return None
    try:
        return Fernet(raw.encode("utf-8"))
    except Exception as exc:
        raise RuntimeError("SECRETS_ENCRYPTION_KEY must be a valid Fernet key") from exc


def encryption_configured() -> bool:
    return bool((os.getenv("SECRETS_ENCRYPTION_KEY") or "").strip())


def is_encrypted_value(value: str) -> bool:
    return (value or "").startswith(ENC_PREFIX)


def encrypt_setting_value(key: str, value: str) -> str:
    if key not in ENCRYPTED_SETTING_KEYS:
        return value or ""
    plain = (value or "").strip()
    if not plain:
        return ""
    if is_encrypted_value(plain):
        return plain
    f = _fernet()
    if not f:
        return plain
    token = f.encrypt(plain.encode("utf-8")).decode("ascii")
    return f"{ENC_PREFIX}{token}"


def decrypt_setting_value(value: str) -> str:
    raw = value or ""
    if not raw:
        return ""
    if not is_encrypted_value(raw):
        return raw
    f = _fernet()
    if not f:
        raise RuntimeError(
            "Encrypted setting found in database but SECRETS_ENCRYPTION_KEY is not configured."
        )
    token = raw[len(ENC_PREFIX) :]
    return f.decrypt(token.encode("ascii")).decode("utf-8")


def decrypt_settings_dict(settings: dict) -> dict:
    out = dict(settings)
    for key in ENCRYPTED_SETTING_KEYS:
        if key in out and out[key]:
            out[key] = decrypt_setting_value(out[key])
    return out


def migrate_plaintext_secrets(db: Session) -> int:
    """Encrypt legacy plaintext secret rows. Returns number of rows updated."""
    if not encryption_configured():
        return 0
    from .db_models import Setting

    updated = 0
    rows = db.execute(select(Setting).where(Setting.key.in_(ENCRYPTED_SETTING_KEYS))).scalars().all()
    for row in rows:
        val = row.value or ""
        if not val or is_encrypted_value(val):
            continue
        row.value = encrypt_setting_value(row.key, val)
        updated += 1
    if updated:
        logger.info("Encrypted %s legacy plaintext setting(s) at rest", updated)
    return updated
