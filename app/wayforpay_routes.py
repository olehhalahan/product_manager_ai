"""
WayForPay: checkout session + serviceUrl webhook.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from .auth import get_current_user, require_admin_http, require_login_http
from .db import get_db
from .pricing_page import load_pricing_config
from .seo import site_base_url
from .services import db_repository as repo
from .services.wayforpay import (
    WAYFORPAY_PAY_URL,
    parse_subscribe_options,
    sign_purchase_request,
    verify_service_callback,
    build_service_accept_response,
)

_log = logging.getLogger("uvicorn.error")


def _plan_wayforpay(plan_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    cfg = load_pricing_config()
    for p in cfg.get("plans") or []:
        if p.get("id") == plan_id:
            wp = p.get("wayforpay")
            if isinstance(wp, dict) and (wp.get("amount") or "").strip():
                return p, wp
            break
    raise HTTPException(
        status_code=400,
        detail="This plan is not available via WayForPay yet (add a wayforpay block in pricing_plans.json).",
    )


def register_wayforpay_routes(app) -> None:
    @app.post("/api/payments/wayforpay/session")
    async def wayforpay_create_session(request: Request):
        """Authenticated: build signed Purchase fields for POST to secure.wayforpay.com/pay."""
        require_login_http(request)
        user = get_current_user(request)
        email = (user.get("email") or "") if user else ""
        if not email:
            raise HTTPException(status_code=401, detail="Not logged in")

        body = await request.json()
        plan_id = (body.get("plan_id") or body.get("planId") or "").strip()
        if not plan_id or plan_id == "free":
            raise HTTPException(status_code=400, detail="Invalid plan_id")

        plan, wp = _plan_wayforpay(plan_id)
        amount = str(wp.get("amount") or "").strip()
        currency = (wp.get("currency") or "UAH").strip().upper()
        product_name = (wp.get("product_name") or plan.get("name") or plan_id).strip()

        with get_db() as db:
            s = repo.get_settings(db)
            merchant = (s.get("wayforpay_merchant_account") or "").strip()
            secret = (s.get("wayforpay_secret_key") or "").strip()
            domain = (s.get("wayforpay_merchant_domain") or "").strip()
            if not merchant or not secret or not domain:
                raise HTTPException(
                    status_code=503,
                    detail="WayForPay is not configured yet. Ask an admin to fill Settings → WayForPay.",
                )

            order_reference = f"cz-{uuid.uuid4().hex[:24]}"
            order_date = str(int(time.time()))
            product_names = [product_name]
            product_counts = ["1"]
            product_prices = [amount]

            sig = sign_purchase_request(
                secret,
                merchant_account=merchant,
                merchant_domain=domain,
                order_reference=order_reference,
                order_date=order_date,
                amount=amount,
                currency=currency,
                product_names=product_names,
                product_counts=product_counts,
                product_prices=product_prices,
            )

            base = site_base_url().rstrip("/")
            return_url = (s.get("wayforpay_return_url") or "").strip() or f"{base}/upload?subscription=success"
            service_url = f"{base}/api/payments/wayforpay/service"

            extra = parse_subscribe_options(s.get("wayforpay_subscribe_options_json"))

            # Form field names per https://wiki.wayforpay.com/en/view/852102 (productName[] / productPrice[] / productCount[])
            fields: dict[str, str] = {
                "merchantAccount": merchant,
                "merchantDomainName": domain,
                "orderReference": order_reference,
                "orderDate": order_date,
                "amount": amount,
                "currency": currency,
                "productName[]": product_names[0],
                "productCount[]": product_counts[0],
                "productPrice[]": product_prices[0],
                "merchantSignature": sig,
                "returnUrl": return_url,
                "serviceUrl": service_url,
                "clientEmail": email,
            }

            for k, v in extra.items():
                if v is None or k in fields:
                    continue
                if isinstance(v, (dict, list)):
                    fields[k] = json.dumps(v, ensure_ascii=False)
                else:
                    fields[k] = str(v)

            repo.create_wayforpay_payment(
                db,
                order_reference=order_reference,
                user_email=email,
                plan_id=plan_id,
                amount=amount,
                currency=currency,
            )

        return JSONResponse(
            {
                "pay_url": WAYFORPAY_PAY_URL,
                "method": "POST",
                "order_reference": order_reference,
                "fields": fields,
            }
        )

    @app.post("/api/payments/wayforpay/service")
    async def wayforpay_service_callback(request: Request):
        """WayForPay server-to-server notification (JSON)."""
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Expected JSON body")

        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON")

        order_reference = str(payload.get("orderReference") or "").strip()
        if not order_reference:
            raise HTTPException(status_code=400, detail="orderReference required")

        with get_db() as db:
            s = repo.get_settings(db)
            secret = (s.get("wayforpay_secret_key") or "").strip()
            if not secret or not verify_service_callback(secret, payload):
                _log.warning("WayForPay serviceUrl: bad signature for %s", order_reference)
                raise HTTPException(status_code=403, detail="Invalid signature")

            row = repo.get_wayforpay_by_order_ref(db, order_reference)
            if not row:
                _log.warning("WayForPay serviceUrl: unknown order %s", order_reference)
                raise HTTPException(status_code=404, detail="Unknown order")

            prev_pay_status = row.status
            tx_status = str(payload.get("transactionStatus") or "")
            reason = str(payload.get("reasonCode") or "")
            raw = json.dumps(payload, ensure_ascii=False)

            ok = tx_status.lower() in ("approved", "accept") or str(reason).strip() == "1100"
            new_status = "completed" if ok else "failed"
            repo.update_wayforpay_from_callback(
                db,
                row,
                transaction_status=tx_status,
                reason_code=reason,
                status=new_status,
                raw_json=raw[:8000],
            )

            if ok and prev_pay_status != "completed":
                repo.apply_paid_subscription_to_user(db, row.user_email, row.plan_id)

            body = build_service_accept_response(secret, order_reference=order_reference)
            return JSONResponse(body)

    @app.post("/api/admin/wayforpay")
    async def admin_save_wayforpay(request: Request):
        require_admin_http(request)
        data = await request.json()
        from .services.db_repository import set_setting

        with get_db() as db:
            if "wayforpay_merchant_account" in data:
                set_setting(db, "wayforpay_merchant_account", str(data["wayforpay_merchant_account"] or "").strip())
            if "wayforpay_merchant_domain" in data:
                set_setting(db, "wayforpay_merchant_domain", str(data["wayforpay_merchant_domain"] or "").strip())
            if "wayforpay_return_url" in data:
                set_setting(db, "wayforpay_return_url", str(data["wayforpay_return_url"] or "").strip())
            if "wayforpay_subscribe_options_json" in data:
                set_setting(
                    db,
                    "wayforpay_subscribe_options_json",
                    str(data["wayforpay_subscribe_options_json"] or "").strip(),
                )
            sk = data.get("wayforpay_secret_key")
            if sk is not None and str(sk).strip():
                set_setting(db, "wayforpay_secret_key", str(sk).strip())
        return JSONResponse({"ok": True})
