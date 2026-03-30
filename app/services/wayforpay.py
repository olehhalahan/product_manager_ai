"""
WayForPay Purchase + serviceUrl callbacks.

Spec: https://wiki.wayforpay.com/en/view/852102 (Accept payment / Purchase).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Mapping


WAYFORPAY_PAY_URL = "https://secure.wayforpay.com/pay"


def hmac_md5_hex(secret_key: str, message: str) -> str:
    """merchantSignature / response signature (hex digest, lowercase)."""
    key = (secret_key or "").encode("utf-8")
    msg = (message or "").encode("utf-8")
    return hmac.new(key, msg, hashlib.md5).hexdigest()


def _join_parts(parts: list[str]) -> str:
    return ";".join(parts)


def build_purchase_signature_string(
    *,
    merchant_account: str,
    merchant_domain: str,
    order_reference: str,
    order_date: str,
    amount: str,
    currency: str,
    product_names: list[str],
    product_counts: list[str],
    product_prices: list[str],
) -> str:
    """Semicolon-separated string for Purchase merchantSignature (order matters)."""
    parts: list[str] = [
        merchant_account,
        merchant_domain,
        order_reference,
        order_date,
        amount,
        currency,
    ]
    parts.extend(product_names)
    parts.extend(product_counts)
    parts.extend(product_prices)
    return _join_parts(parts)


def sign_purchase_request(
    secret_key: str,
    *,
    merchant_account: str,
    merchant_domain: str,
    order_reference: str,
    order_date: str,
    amount: str,
    currency: str,
    product_names: list[str],
    product_counts: list[str],
    product_prices: list[str],
) -> str:
    s = build_purchase_signature_string(
        merchant_account=merchant_account,
        merchant_domain=merchant_domain,
        order_reference=order_reference,
        order_date=order_date,
        amount=amount,
        currency=currency,
        product_names=product_names,
        product_counts=product_counts,
        product_prices=product_prices,
    )
    return hmac_md5_hex(secret_key, s)


def build_service_callback_signature_string(payload: Mapping[str, Any]) -> str:
    """
    Verify WayForPay POST to serviceUrl:
    merchantAccount;orderReference;amount;currency;authCode;cardPan;transactionStatus;reasonCode
    """
    def _g(key: str) -> str:
        v = payload.get(key)
        if v is None:
            return ""
        return str(v)

    return _join_parts(
        [
            _g("merchantAccount"),
            _g("orderReference"),
            _g("amount"),
            _g("currency"),
            _g("authCode"),
            _g("cardPan"),
            _g("transactionStatus"),
            _g("reasonCode"),
        ]
    )


def verify_service_callback(secret_key: str, payload: Mapping[str, Any]) -> bool:
    expected = (payload.get("merchantSignature") or "").strip().lower()
    if not expected:
        return False
    s = build_service_callback_signature_string(payload)
    calc = hmac_md5_hex(secret_key, s).lower()
    return hmac.compare_digest(calc, expected)


def build_service_accept_response(
    secret_key: str,
    *,
    order_reference: str,
    status: str = "accept",
    response_time: int | None = None,
) -> dict[str, Any]:
    """JSON body to return to WayForPay after handling serviceUrl (200 OK)."""
    t = response_time if response_time is not None else int(time.time())
    sig = hmac_md5_hex(secret_key, _join_parts([order_reference, status, str(t)]))
    return {
        "orderReference": order_reference,
        "status": status,
        "time": t,
        "signature": sig,
    }


def parse_subscribe_options(raw: str | None) -> dict[str, Any]:
    """Optional admin JSON merged into Purchase fields (regularMode, regularOn, …)."""
    if not raw or not str(raw).strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
