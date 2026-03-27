"""
Google Merchant Center via Merchant API (OAuth + account discovery + productInputs.insert).

Uses merchantapi.googleapis.com only (not the deprecated Content API for Shopping).

OAuth client credentials must come from the same Google Cloud project as
GOOGLE_CLOUD_PROJECT_ID (see app/google_cloud.py).

Merchant ID resolution:
- GMC_MERCHANT_ID in .env overrides the built-in default account id.
- If GMC_MERCHANT_ID is not present in the environment, the default id 5750677992 is used (single-store).
- Legacy wrong account id 5635309342 is never used: remapped to 5750677992 everywhere (env, DB, API).
- accounts.list returns accessible accounts; for each, listSubaccounts may return MCA clients.
- If a provider has subaccounts, the first subaccount id is used (MCA / agency case).
- Otherwise the first account from accounts.list is used.

Product insert requires an API primary (or supplemental) data source:
- Optional GMC_DATA_SOURCE_NAME = full resource name, e.g. accounts/123/dataSources/456
- Else we list data sources and pick one with input=API and primaryProductDataSource set
- Else we create a primary API data source (display name via GMC_DATA_SOURCE_DISPLAY_NAME).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

import httpx

from ..google_cloud import get_normalized_google_oauth_credentials
from ..models import ProductResult

if TYPE_CHECKING:
    from ..models import NormalizedProduct

_log = logging.getLogger("uvicorn.error")

MERCHANT_API_BASE = "https://merchantapi.googleapis.com"

# Single Merchant Center account when GMC_MERCHANT_ID is not set in .env.
# Set GMC_MERCHANT_ID= in .env (empty) to skip this and run API discovery instead.
_DEFAULT_GMC_MERCHANT_ID = "5750677992"
# Must not be used for product uploads; always remapped to _DEFAULT_GMC_MERCHANT_ID.
_BLOCKED_LEGACY_MERCHANT_ID = "5635309342"


def canonical_merchant_id(raw: Optional[str]) -> Optional[str]:
    """Normalize Merchant Center account id; map deprecated wrong account to the canonical store id."""
    n = _normalize_merchant_id_str(raw)
    if not n:
        return None
    if n == _BLOCKED_LEGACY_MERCHANT_ID:
        return _DEFAULT_GMC_MERCHANT_ID
    return n


def effective_gmc_merchant_id_override() -> str:
    """Numeric id from GMC_MERCHANT_ID, or built-in default when that env var is unset."""
    if "GMC_MERCHANT_ID" in os.environ:
        raw = (os.getenv("GMC_MERCHANT_ID") or "").strip()
        if raw == _BLOCKED_LEGACY_MERCHANT_ID:
            return _DEFAULT_GMC_MERCHANT_ID
        return raw
    return _DEFAULT_GMC_MERCHANT_ID
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def _gmc_content_language() -> str:
    return (os.getenv("GMC_CONTENT_LANGUAGE") or "en").strip() or "en"


def _gmc_target_country() -> str:
    return (os.getenv("GMC_TARGET_COUNTRY") or "US").strip().upper() or "US"


def _gmc_feed_label() -> str:
    """Feed label for ProductInput and primary data source (A–Z, 0–9, -, _; max 20)."""
    raw = (os.getenv("GMC_FEED_LABEL") or _gmc_target_country()).strip().upper()
    s = re.sub(r"[^A-Z0-9_-]", "_", raw)[:20]
    return s or "US"


def _gmc_data_source_display_name() -> str:
    return (os.getenv("GMC_DATA_SOURCE_DISPLAY_NAME") or "Cartozo API").strip()[:200] or "Cartozo API"


_COUNTRY_NAME_TO_ISO2: Dict[str, str] = {
    "ukraine": "UA",
    "україна": "UA",
    "germany": "DE",
    "deutschland": "DE",
    "united states": "US",
    "usa": "US",
    "united kingdom": "GB",
    "great britain": "GB",
    "poland": "PL",
    "polska": "PL",
    "france": "FR",
    "sweden": "SE",
    "sverige": "SE",
    "spain": "ES",
    "italy": "IT",
    "netherlands": "NL",
    "canada": "CA",
    "australia": "AU",
}

_ISO3_TO_ISO2 = {"UKR": "UA", "USA": "US", "GBR": "GB", "DEU": "DE", "POL": "PL", "FRA": "FR", "SWE": "SE"}


def normalize_country_code(raw: Optional[str]) -> str:
    """Map CSV / UI country to ISO 3166-1 alpha-2; fallback to GMC_TARGET_COUNTRY."""
    if not raw or not str(raw).strip():
        return _gmc_target_country()
    s = str(raw).strip()
    if len(s) == 2 and s.isalpha():
        return s.upper()
    if len(s) == 3 and s.isalpha():
        return _ISO3_TO_ISO2.get(s.upper(), _gmc_target_country())
    low = s.lower()
    if low in _COUNTRY_NAME_TO_ISO2:
        return _COUNTRY_NAME_TO_ISO2[low]
    return _gmc_target_country()


def _country_from_product(product: "NormalizedProduct") -> str:
    """Prefer mapped target_country, then attributes / original_row country columns."""
    raw = (product.target_country or "").strip()
    if raw:
        return normalize_country_code(raw)
    for key in ("country", "target_country", "shipping_country", "country_of_sale", "Country", "TARGET_COUNTRY"):
        v = product.attributes.get(key) or (product.original_row.get(key) if product.original_row else "") or ""
        if v and str(v).strip():
            return normalize_country_code(str(v).strip())
    if product.original_row:
        for k, v in product.original_row.items():
            if not k or not (v or "").strip():
                continue
            if k.lower() in ("country", "target_country", "shipping_country", "country_of_sale"):
                return normalize_country_code(str(v).strip())
    return _gmc_target_country()


def _normalize_content_language_for_api(lang: str) -> str:
    s = (lang or "en").strip().lower().replace("_", "-")
    base = s.split("-")[0]
    if len(base) == 2:
        return base
    return "en"


def content_language_for_product(product: "NormalizedProduct", country_iso: str) -> str:
    if product.language and str(product.language).strip():
        return _normalize_content_language_for_api(str(product.language))
    if country_iso == "UA":
        return "uk"
    return _normalize_content_language_for_api(_gmc_content_language())


def feed_label_for_country(country_iso: str) -> str:
    """Feed label must match [A-Z0-9_-] max 20 — use country code by default."""
    raw = (country_iso or _gmc_target_country()).strip().upper()
    s = re.sub(r"[^A-Z0-9_-]", "_", raw)[:20]
    return s or "US"


def _unique_offer_id(raw_id: str) -> str:
    """
    Stable unique offer id per product id (max 50 chars).
    Merchant API upserts by offerId + feedLabel + contentLanguage + dataSource; if
    many rows map to the same offerId after sanitization, later inserts overwrite
    earlier ones — the catalog item count may not grow.
    """
    digest = hashlib.sha256(str(raw_id).encode("utf-8")).hexdigest()[:12]
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", (raw_id or "").strip())[:30]
    if not safe:
        return f"item_{digest}"[:50]
    return f"{safe}_{digest}"[:50]


def _account_id_from_resource_name(name: str) -> Optional[str]:
    if not name or not name.startswith("accounts/"):
        return None
    rest = name[len("accounts/") :].strip()
    if "/" in rest:
        rest = rest.split("/", 1)[0]
    return rest if rest.isdigit() else None


def _account_id_from_account(acc: Dict[str, Any]) -> Optional[str]:
    """Prefer numeric accountId from API; fallback to parsing name."""
    aid = acc.get("accountId")
    if aid is not None and str(aid).strip().isdigit():
        return str(aid).strip()
    return _account_id_from_resource_name((acc.get("name") or "").strip())


def _normalize_merchant_id_str(raw: Optional[str]) -> Optional[str]:
    """Strip to digits-only Merchant Center account id (from UI or 'accounts/123')."""
    if not raw:
        return None
    s = str(raw).strip()
    if s.startswith("accounts/"):
        s = s.split("/")[-1]
    return s if s.isdigit() else None


def normalize_merchant_id(raw: Optional[str]) -> Optional[str]:
    """Public alias for API / settings (same rules as _normalize_merchant_id_str)."""
    return _normalize_merchant_id_str(raw)


def _parse_price_currency(result: ProductResult) -> Tuple[Optional[str], Optional[str]]:
    """Return (decimal value string, currency) from ProductResult."""
    p = result.product
    cur = (p.currency or "USD").strip().upper()
    price_raw = (p.sale_price or p.price or "").strip()
    if not price_raw:
        return None, cur
    cleaned = price_raw
    for token in ("USD", "EUR", "GBP", "UAH", "PLN"):
        cleaned = re.sub(rf"\b{token}\b", "", cleaned, flags=re.I)
    cleaned = cleaned.replace("$", "").replace("€", "").replace("£", "").strip()
    m = re.search(r"(\d+(?:[.,]\d+)?)", cleaned)
    if not m:
        return None, cur
    num = m.group(1).replace(",", ".")
    parts = num.split(".")
    if len(parts) > 2:
        num = "".join(parts[:-1]) + "." + parts[-1]
    try:
        val = f"{float(num):.2f}"
    except ValueError:
        return None, cur
    return val, cur


def _price_decimal_to_amount_micros(value_str: str) -> Optional[str]:
    try:
        micros = int(round(float(value_str) * 1_000_000))
        return str(micros)
    except ValueError:
        return None


def _map_condition_merchant(raw: Optional[str]) -> str:
    if not raw:
        return "NEW"
    s = raw.strip().lower()
    if s in ("refurbished", "refurb"):
        return "REFURBISHED"
    if s in ("used",):
        return "USED"
    if s in ("new",):
        return "NEW"
    if "refurb" in s:
        return "REFURBISHED"
    if "used" in s or "second" in s:
        return "USED"
    return "NEW"


def build_merchant_product_body(
    result: ProductResult,
    *,
    content_language: Optional[str] = None,
    feed_label: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Map ProductResult to Merchant API ProductInput resource.
    Returns (body, skip_reason). skip_reason set if product cannot be pushed.
    When content_language / feed_label are omitted, uses GMC_* env defaults.
    """
    p = result.product
    title = result.effective_title()
    desc = result.effective_description()
    link = (p.url or "").strip()
    image = (p.image_url or "").strip()
    if not link:
        return None, "missing product link"
    if not image:
        return None, "missing image URL"
    if not title:
        return None, "missing title"
    price_val, currency = _parse_price_currency(result)
    if not price_val:
        return None, "missing or invalid price"
    micros = _price_decimal_to_amount_micros(price_val)
    if not micros:
        return None, "missing or invalid price"

    offer_id = _unique_offer_id(p.id)
    attrs: Dict[str, Any] = {
        "title": title[:150],
        "description": desc[:5000] if desc else title[:5000],
        "link": link[:2000],
        "imageLink": image[:2000],
        "availability": "IN_STOCK",
        "condition": _map_condition_merchant(p.condition),
        "price": {"amountMicros": micros, "currencyCode": currency},
    }
    if p.brand and str(p.brand).strip():
        attrs["brand"] = str(p.brand).strip()[:70]
    if p.gtin and str(p.gtin).strip():
        gtin = re.sub(r"\D", "", str(p.gtin))[:50]
        if gtin:
            attrs["gtins"] = [gtin]
    if p.mpn and str(p.mpn).strip():
        attrs["mpn"] = str(p.mpn).strip()[:70]

    cl = (
        _normalize_content_language_for_api(content_language)
        if content_language is not None
        else _normalize_content_language_for_api(_gmc_content_language())
    )
    if feed_label is not None:
        fl = re.sub(r"[^A-Z0-9_-]", "_", feed_label.strip().upper())[:20] or _gmc_feed_label()
    else:
        fl = _gmc_feed_label()

    body: Dict[str, Any] = {
        "offerId": offer_id,
        "contentLanguage": cl,
        "feedLabel": fl,
        "productAttributes": attrs,
    }
    return body, None


async def get_access_token_from_refresh(refresh_token: str) -> Optional[str]:
    """Exchange a stored refresh token for a short-lived access token (server-side uploads)."""
    cid, csec = get_normalized_google_oauth_credentials()
    if not refresh_token or not cid or not csec:
        return None
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": cid,
                    "client_secret": csec,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=30.0,
            )
        if r.status_code != 200:
            return None
        return r.json().get("access_token")
    except Exception:
        return None


def _google_api_error_message(r: httpx.Response) -> str:
    try:
        j = r.json()
        err = j.get("error")
        if isinstance(err, dict):
            msg = err.get("message") or err.get("status") or ""
            if msg:
                return str(msg)[:500]
        if isinstance(err, str) and err:
            return err[:500]
    except Exception:
        pass
    return (r.text or "")[:300]


_DEVELOPER_REGISTER_GUIDE = (
    "https://developers.google.com/merchant/api/guides/quickstart/direct-api-calls#step_1_register_as_a_developer"
)


def _merchant_api_error_hint(status_code: int, google_msg: str) -> str:
    """Human-readable next steps for common Merchant API failures."""
    base = f"Merchant API HTTP {status_code}"
    if google_msg:
        base += f": {google_msg}"
    gm = (google_msg or "").lower()
    # Same symptom often reported as HTTP 401: project must be linked to the merchant account.
    if "not registered" in gm and "merchant" in gm:
        base += (
            " — Your OAuth Google Cloud project must be registered with this Merchant Center account "
            f"(Merchant API “developer registration”). See {_DEVELOPER_REGISTER_GUIDE} — call "
            "POST .../accounts/{MERCHANT_ID}/developerRegistration:registerGcp with your developer email, "
            "or complete the equivalent step in Merchant Center. Use the same project as GOOGLE_CLIENT_ID / "
            "GOOGLE_CLOUD_PROJECT_ID. Wait about 5 minutes after registration, then retry (reconnect OAuth if needed)."
        )
        return base
    if status_code == 403:
        base += (
            " — In the same Google Cloud project as GOOGLE_CLIENT_ID: enable “Merchant API” "
            "(console.cloud.google.com → APIs & Services → Library). "
            "OAuth consent screen: scope https://www.googleapis.com/auth/content. "
            "On Upload: Disconnect Merchant Center and Connect again. "
            "If the app is in Testing mode, add your Google account as a Test user."
        )
    elif status_code == 401:
        base += " — If the message above is not about GCP registration: access token invalid or revoked — disconnect Merchant on Upload and connect again."
    return base


async def _merchant_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    access_token: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Any = None,
) -> httpx.Response:
    url = f"{MERCHANT_API_BASE}/{path}"
    headers: Dict[str, str] = {"Authorization": f"Bearer {access_token}"}
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    return await client.request(method, url, headers=headers, params=params, json=json_body, timeout=60.0)


async def _list_accounts_all(access_token: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    out: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    try:
        async with httpx.AsyncClient() as client:
            while True:
                params: Dict[str, Any] = {"pageSize": 250}
                if page_token:
                    params["pageToken"] = page_token
                r = await _merchant_request(client, "GET", "accounts/v1/accounts", access_token, params=params)
                if r.status_code != 200:
                    gmsg = _google_api_error_message(r)
                    hint = _merchant_api_error_hint(r.status_code, gmsg)
                    _log.warning("accounts.list %s", hint[:800])
                    return [], hint
                data = r.json()
                out.extend(data.get("accounts") or [])
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
    except Exception as ex:
        _log.warning("accounts.list failed: %s", ex)
        return [], str(ex)[:200]
    return out, None


async def _list_subaccounts_all(
    access_token: str, provider: str
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """provider is accounts/{numericId}."""
    out: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    enc_provider = provider
    if not enc_provider.startswith("accounts/"):
        enc_provider = f"accounts/{provider}"
    path = f"accounts/v1/{enc_provider}:listSubaccounts"
    try:
        async with httpx.AsyncClient() as client:
            while True:
                params: Dict[str, Any] = {"pageSize": 250}
                if page_token:
                    params["pageToken"] = page_token
                r = await _merchant_request(client, "GET", path, access_token, params=params)
                if r.status_code != 200:
                    return [], None
                data = r.json()
                out.extend(data.get("accounts") or [])
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
    except Exception as ex:
        _log.debug("listSubaccounts for %s: %s", provider, ex)
        return [], None
    return out, None


async def all_accessible_numeric_merchant_ids(access_token: str) -> Tuple[Set[str], Optional[str]]:
    """
    Every numeric account id the token can act on (top-level accounts + subaccounts).
    Used to validate user-selected GMC_MERCHANT_ID / DB merchant_id.
    """
    out: Set[str] = set()
    accounts, err = await _list_accounts_all(access_token)
    if err and not accounts:
        return out, err
    if not accounts:
        return out, "No Merchant Center accounts returned by accounts.list."

    for acc in accounts:
        parent_name = (acc.get("name") or "").strip()
        if not parent_name:
            continue
        mid = _account_id_from_account(acc)
        if mid:
            out.add(mid)
        subs, _ = await _list_subaccounts_all(access_token, parent_name)
        for s in subs:
            sm = _account_id_from_account(s)
            if sm:
                out.add(sm)
    return out, None


async def merchant_id_is_accessible(access_token: str, merchant_id: str) -> Tuple[bool, Optional[str]]:
    """True if this id is one of the accounts reachable with the current OAuth token."""
    want = canonical_merchant_id(merchant_id)
    if not want:
        return False, "merchant_id must be a numeric Merchant Center account id."
    ids, err = await all_accessible_numeric_merchant_ids(access_token)
    if err:
        return False, err
    if want in ids:
        return True, None
    return False, (
        f"Merchant ID {want} is not in the accounts accessible for this Google login. "
        "Pick an id from Merchant Center (gear → Account settings) or from GET /api/merchant/accounts."
    )


async def resolve_merchant_account_id(
    access_token: str, preferred_merchant_id: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """
    Resolve numeric Merchant Center account id for productInputs.insert.

    Returns (merchant_id, hint_if_none) — hint explains why resolution failed.

    Important: do **not** prefer “first subaccount of the first MCA” — that often is not the
    merchant storefront the user sees in Merchant Center. Prefer **leaf** accounts (no
    subaccounts under them), which match standalone stores and MCA client accounts listed
    as their own Account rows.
    """
    override = effective_gmc_merchant_id_override()
    if override.isdigit():
        return override, None

    pref = canonical_merchant_id(preferred_merchant_id)
    if pref:
        ok, _err = await merchant_id_is_accessible(access_token, pref)
        if ok:
            _log.info("Using preferred merchant id %s (user profile or API)", pref)
            return pref, None

    accounts, err = await _list_accounts_all(access_token)
    if err and not accounts:
        return None, err
    if not accounts:
        return (
            None,
            "No Merchant Center accounts returned by Merchant API accounts.list. "
            "Use the same Google account as in Merchant Center, or set GMC_MERCHANT_ID in .env.",
        )

    # Single row: either a standalone merchant or an MCA parent (only entry returned).
    if len(accounts) == 1:
        acc = accounts[0]
        parent_name = (acc.get("name") or "").strip()
        if not parent_name:
            return None, "Could not parse merchant account id from accounts.list response."
        subs, _ = await _list_subaccounts_all(access_token, parent_name)
        if subs:
            mid = _account_id_from_account(subs[0])
            if mid:
                _log.info(
                    "Single list entry is an advanced account with subaccounts; using first subaccount %s",
                    mid,
                )
                return mid, None
        mid = _account_id_from_account(acc)
        if mid:
            return mid, None
        return None, "Could not parse merchant account id from accounts.list response."

    # Multiple accounts: collect "leaf" merchants (this account is not a parent with subaccounts).
    leaf_ids: List[str] = []
    for acc in accounts:
        parent_name = (acc.get("name") or "").strip()
        if not parent_name:
            continue
        subs, _ = await _list_subaccounts_all(access_token, parent_name)
        if subs:
            continue
        mid = _account_id_from_account(acc)
        if mid:
            leaf_ids.append(mid)

    if len(leaf_ids) == 1:
        _log.info("Resolved merchant id to sole leaf account %s", leaf_ids[0])
        return leaf_ids[0], None

    if len(leaf_ids) > 1:
        sample = ", ".join(leaf_ids[:12])
        return (
            None,
            "Multiple Merchant Center accounts are accessible. Pick one numeric ID (e.g. "
            f"{sample}) and either: set GMC_MERCHANT_ID in server .env and restart, or "
            'call POST /api/merchant/select-account with JSON {"merchant_id":"<id>"} while logged in '
            "(same as Upload). GET /api/merchant/accounts lists valid ids for your Google login.",
        )

    # No leaf rows (e.g. only MCA parents listed, subs not duplicated as Account rows): legacy fallback.
    for acc in accounts:
        parent_name = (acc.get("name") or "").strip()
        if not parent_name:
            continue
        subs, _ = await _list_subaccounts_all(access_token, parent_name)
        if subs:
            mid = _account_id_from_account(subs[0])
            if mid:
                _log.warning(
                    "Falling back to first subaccount %s under %s — set GMC_MERCHANT_ID to your real store id if wrong",
                    mid,
                    parent_name,
                )
                return mid, None

    mid = _account_id_from_account(accounts[0])
    if mid:
        return mid, None
    return None, "Could not parse merchant account id from accounts.list response."


async def resolve_merchant_id_for_content_api(
    access_token: str, preferred_merchant_id: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """Deprecated alias — use resolve_merchant_account_id."""
    return await resolve_merchant_account_id(access_token, preferred_merchant_id)


async def fetch_primary_merchant_id(access_token: str) -> Optional[str]:
    """Return merchant id for OAuth callback / DB (legacy name)."""
    mid, _hint = await resolve_merchant_account_id(access_token)
    return mid


def _primary_product_data_source(ds: Dict[str, Any]) -> Dict[str, Any]:
    ppd = ds.get("primaryProductDataSource")
    return ppd if isinstance(ppd, dict) else {}


def _ppd_matches_restricted(
    ppd: Dict[str, Any], want_feed: str, want_lang: str, want_country: str
) -> bool:
    """primaryProductDataSource matches desired feed label, language, and country list."""
    if not ppd:
        return False
    fl = str(ppd.get("feedLabel") or "").strip().upper()
    cl = str(ppd.get("contentLanguage") or "").strip().lower()
    if not fl or not cl:
        return False
    wf = want_feed.strip().upper()
    wln = _normalize_content_language_for_api(want_lang)
    cln = cl.replace("_", "-")
    lang_ok = cln.split("-")[0] == wln
    if fl != wf or not lang_ok:
        return False
    countries = ppd.get("countries") or []
    wc = want_country.strip().upper()
    if not countries:
        return True
    return any(str(c).strip().upper() == wc for c in countries)


def _ppd_is_unrestricted(ppd: Dict[str, Any]) -> bool:
    fl = str(ppd.get("feedLabel") or "").strip()
    cl = str(ppd.get("contentLanguage") or "").strip()
    return not fl and not cl


def _ppd_country_list_matches(ppd: Dict[str, Any], want_country: str) -> bool:
    countries = ppd.get("countries") or []
    if not countries:
        return True
    wc = want_country.strip().upper()
    return any(str(c).strip().upper() == wc for c in countries)


def _select_api_primary_data_source(
    data_sources: List[Dict[str, Any]],
    want_feed: str,
    want_lang: str,
    want_country: str,
) -> Optional[str]:
    """
    Pick an API primary data source that can accept our ProductInput (feedLabel, contentLanguage, country).
    """
    api_primaries: List[Dict[str, Any]] = []
    for ds in data_sources:
        if ds.get("input") != "API":
            continue
        if not ds.get("primaryProductDataSource"):
            continue
        nm = (ds.get("name") or "").strip()
        if not nm:
            continue
        api_primaries.append(ds)

    if not api_primaries:
        return None

    wf = want_feed.strip().upper()
    wl = _normalize_content_language_for_api(want_lang)
    wc = want_country.strip().upper()

    for ds in api_primaries:
        ppd = _primary_product_data_source(ds)
        if _ppd_matches_restricted(ppd, wf, wl, wc):
            _log.info("Selected API data source (feed/lang/country): %s", ds["name"])
            return str(ds["name"]).strip()

    for ds in api_primaries:
        ppd = _primary_product_data_source(ds)
        if _ppd_is_unrestricted(ppd) and _ppd_country_list_matches(ppd, wc):
            _log.info("Selected unrestricted API data source: %s", ds["name"])
            return str(ds["name"]).strip()

    _log.warning(
        "No API primary data source matches feed_label=%s content_language=%s country=%s; will create new",
        wf,
        wl,
        wc,
    )
    return None


async def _list_data_sources_all(
    access_token: str, parent: str
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """parent: accounts/{numericId}."""
    out: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    path = f"datasources/v1/{parent}/dataSources"
    try:
        async with httpx.AsyncClient() as client:
            while True:
                params: Dict[str, Any] = {"pageSize": 500}
                if page_token:
                    params["pageToken"] = page_token
                r = await _merchant_request(client, "GET", path, access_token, params=params)
                if r.status_code != 200:
                    gmsg = _google_api_error_message(r)
                    return [], _merchant_api_error_hint(r.status_code, gmsg)
                data = r.json()
                out.extend(data.get("dataSources") or [])
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
    except Exception as ex:
        return [], str(ex)[:200]
    return out, None


async def _create_primary_api_data_source(
    access_token: str,
    parent: str,
    *,
    content_language: str,
    feed_label: str,
    target_country: str,
) -> Tuple[Optional[str], Optional[str]]:
    path = f"datasources/v1/{parent}/dataSources"
    cl = _normalize_content_language_for_api(content_language)
    fl = re.sub(r"[^A-Z0-9_-]", "_", feed_label.strip().upper())[:20] or feed_label_for_country(target_country)
    tc = target_country.strip().upper()
    body: Dict[str, Any] = {
        "displayName": f"{_gmc_data_source_display_name()} {fl}",
        "primaryProductDataSource": {
            "contentLanguage": cl,
            "feedLabel": fl,
            "countries": [tc],
        },
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await _merchant_request(client, "POST", path, access_token, json_body=body)
        if r.status_code in (200, 201):
            name = (r.json().get("name") or "").strip()
            if name:
                return name, None
            return None, "dataSources.create returned no name"
        return None, _google_api_error_message(r)[:2000]
    except Exception as e:
        return None, str(e)[:2000]


async def resolve_or_create_api_data_source(
    access_token: str,
    merchant_id: str,
    *,
    content_language: Optional[str] = None,
    feed_label: Optional[str] = None,
    target_country: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Full resource name for dataSource query param, e.g. accounts/123/dataSources/456.
    When content_language / feed_label / target_country are omitted, uses GMC_* env defaults.
    """
    env_name = (os.getenv("GMC_DATA_SOURCE_NAME") or "").strip()
    if env_name and "/dataSources/" in env_name and env_name.startswith("accounts/"):
        return env_name, None

    cl = (
        _normalize_content_language_for_api(content_language)
        if content_language is not None
        else _normalize_content_language_for_api(_gmc_content_language())
    )
    tc = (target_country.strip().upper() if target_country else _gmc_target_country())
    if feed_label is not None:
        fl = re.sub(r"[^A-Z0-9_-]", "_", feed_label.strip().upper())[:20] or feed_label_for_country(tc)
    else:
        fl = _gmc_feed_label()

    parent = f"accounts/{merchant_id}"
    sources, err = await _list_data_sources_all(access_token, parent)
    if err:
        return None, err

    picked = _select_api_primary_data_source(sources, fl, cl, tc)
    if picked:
        return picked, None

    _log.info("No suitable API primary data source; creating one for %s (%s/%s/%s)", parent, fl, cl, tc)
    created_name, create_err = await _create_primary_api_data_source(
        access_token, parent, content_language=cl, feed_label=fl, target_country=tc
    )
    if created_name:
        return created_name, None

    _log.warning("dataSources.create failed (%s); re-listing data sources", (create_err or "")[:300])
    sources2, err2 = await _list_data_sources_all(access_token, parent)
    if err2:
        return None, create_err or err2
    picked2 = _select_api_primary_data_source(sources2, fl, cl, tc)
    if picked2:
        return picked2, None
    return None, create_err or "Could not create or select an API primary data source"


def _extract_offer_id_from_listed_product(p: Dict[str, Any]) -> Optional[str]:
    """Best-effort offer id from products.list item (Merchant API shapes vary)."""
    if not isinstance(p, dict):
        return None
    for key in ("offerId", "offer_id"):
        v = p.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    attrs = p.get("attributes") or p.get("productAttributes") or {}
    if isinstance(attrs, dict):
        for key in ("offerId", "offer_id"):
            v = attrs.get(key)
            if v is not None and str(v).strip():
                return str(v).strip()
    name = (p.get("name") or "").strip()
    if not name:
        return None
    if "~" in name:
        parts = name.split("~")
        if len(parts) >= 3:
            tail = parts[-1].strip()
            return tail.split("/")[-1] if tail else None
    if ":" in name:
        tail = name.rsplit(":", 1)[-1].strip()
        return tail.split("/")[-1] if tail else None
    return None


async def _list_processed_products_sample(
    access_token: str, merchant_id: str, page_size: int = 10
) -> Optional[Dict[str, Any]]:
    """GET processed products — confirms the API sees listings for this merchant id."""
    path = f"products/v1/accounts/{merchant_id}/products"
    try:
        async with httpx.AsyncClient() as client:
            r = await _merchant_request(
                client,
                "GET",
                path,
                access_token,
                params={"pageSize": min(max(page_size, 1), 1000)},
            )
        if r.status_code != 200:
            return {"http_status": r.status_code, "error": _google_api_error_message(r)[:500]}
        data = r.json()
        prods = data.get("products") or []
        return {
            "count_on_page": len(prods),
            "has_more": bool(data.get("nextPageToken")),
            "sample_product_names": [(p.get("name") or "")[:160] for p in prods[:5]],
        }
    except Exception as ex:
        return {"error": str(ex)[:300]}


async def verify_offer_ids_in_processed_catalog(
    access_token: str,
    merchant_id: str,
    offer_ids: List[str],
    *,
    max_pages: int = 10,
    page_size: int = 250,
) -> Dict[str, Any]:
    """
    After productInputs.insert, poll products.list and see how many expected offerIds appear
    in the *processed* catalog (Google may need minutes to process — missing ids are not always errors).
    """
    want: Set[str] = {str(x).strip() for x in offer_ids if str(x).strip()}
    if not want:
        return {
            "expected": 0,
            "found_in_catalog": 0,
            "not_yet_in_catalog": [],
            "catalog_match_complete": True,
            "pages_scanned": 0,
            "note": "No offer ids to verify.",
        }

    path = f"products/v1/accounts/{merchant_id}/products"
    found: Set[str] = set()
    page_token: Optional[str] = None
    pages_scanned = 0
    list_error: Optional[str] = None

    try:
        async with httpx.AsyncClient() as client:
            while pages_scanned < max_pages:
                params: Dict[str, Any] = {"pageSize": min(max(page_size, 1), 1000)}
                if page_token:
                    params["pageToken"] = page_token
                r = await _merchant_request(client, "GET", path, access_token, params=params)
                pages_scanned += 1
                if r.status_code != 200:
                    list_error = _google_api_error_message(r)[:500]
                    break
                data = r.json()
                prods = data.get("products") or []
                for p in prods:
                    if not isinstance(p, dict):
                        continue
                    oid = _extract_offer_id_from_listed_product(p)
                    if oid and oid in want:
                        found.add(oid)
                if want <= found:
                    break
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
    except Exception as ex:
        list_error = str(ex)[:400]

    missing = sorted(want - found)
    truncated_scan = bool(missing and pages_scanned >= max_pages)
    note = (
        "All inserted offerIds appear in the Merchant API processed products list."
        if not missing and not list_error
        else (
            "Some offerIds are not on the first pages of products.list yet — Merchant Center "
            "processes inputs asynchronously (often a few minutes). Check Merchant Center or retry later."
            if missing
            else "Catalog check."
        )
    )
    if truncated_scan:
        note += " (Stopped after scanning max pages; very large catalogs may need a direct check in Merchant Center.)"

    return {
        "expected": len(want),
        "found_in_catalog": len(found.intersection(want)),
        "found_offer_ids": sorted(found.intersection(want))[:80],
        "not_yet_in_catalog": missing[:80],
        "catalog_match_complete": len(missing) == 0,
        "pages_scanned": pages_scanned,
        "list_error": list_error,
        "note": note,
    }


async def insert_product(
    access_token: str,
    merchant_id: str,
    data_source_name: str,
    product_body: Dict[str, Any],
) -> Tuple[bool, Optional[str], Optional[str]]:
    """POST productInputs:insert. Returns (success, error_message, product_input_resource_name)."""
    parent = f"accounts/{merchant_id}"
    path = f"products/v1/{parent}/productInputs:insert"
    params = {"dataSource": data_source_name}
    try:
        async with httpx.AsyncClient() as client:
            r = await _merchant_request(client, "POST", path, access_token, params=params, json_body=product_body)
        if r.status_code in (200, 201):
            try:
                j = r.json()
            except Exception:
                _log.warning("productInputs.insert HTTP %s but response was not JSON", r.status_code)
                return True, None, None
            if isinstance(j, dict) and j.get("error"):
                err = j.get("error")
                if isinstance(err, dict):
                    return False, (err.get("message") or str(err))[:2000], None
                return False, str(err)[:2000], None
            name = (j.get("name") or "").strip() or None
            if name:
                _log.info("productInputs.insert ok: %s", name[:200])
            else:
                _log.warning("productInputs.insert HTTP %s but no name in JSON body", r.status_code)
            return True, None, name
        try:
            err = r.json()
            msg = err.get("error", {}).get("message") or err.get("message") or r.text
        except Exception:
            msg = r.text or f"HTTP {r.status_code}"
        return False, msg[:2000], None
    except Exception as e:
        return False, str(e)[:2000], None


async def push_batch_products(
    access_token: str,
    merchant_id: str,
    results: List[ProductResult],
) -> Dict[str, Any]:
    """
    Insert each ProductResult via Merchant API productInputs:insert (API data source).

    When GMC_DATA_SOURCE_NAME is a full resource name (accounts/.../dataSources/...),
    that single data source is used and ProductInput uses GMC_* env defaults (feed
    label / language must match that data source).

    Otherwise, per-product target country (CSV / target_country / attributes) selects
    content language, feed label, and the matching or newly created API primary data source.
    """
    forced_env_ds = (os.getenv("GMC_DATA_SOURCE_NAME") or "").strip()
    use_fixed_ds = bool(
        forced_env_ds.startswith("accounts/") and "/dataSources/" in forced_env_ds
    )

    data_source: Optional[str] = None
    ds_err: Optional[str] = None
    ds_cache: Dict[Tuple[str, str, str], Tuple[Optional[str], Optional[str]]] = {}

    if use_fixed_ds:
        data_source, ds_err = await resolve_or_create_api_data_source(access_token, merchant_id)
        if not data_source:
            return {
                "merchant_id": merchant_id,
                "data_source": None,
                "inserted": 0,
                "skipped": len(results),
                "failed": 0,
                "details": [
                    {
                        "product_id": r.product.id,
                        "status": "error",
                        "message": ds_err or "Could not resolve or create API data source",
                    }
                    for r in results[:200]
                ],
                "error": ds_err or "Could not resolve or create API data source",
            }

    async def get_ds(cc: str, cl: str, fl: str) -> Tuple[Optional[str], Optional[str]]:
        key = (cc, cl, fl)
        if key not in ds_cache:
            ds_cache[key] = await resolve_or_create_api_data_source(
                access_token,
                merchant_id,
                content_language=cl,
                feed_label=fl,
                target_country=cc,
            )
        return ds_cache[key]

    inserted = 0
    skipped = 0
    failed = 0
    details: List[Dict[str, Any]] = []
    inserted_offer_ids: List[str] = []
    region_counts: Dict[str, int] = {}
    last_success_region: Optional[Tuple[str, str, str]] = None  # country_iso, content_lang, feed_label

    for result in results:
        pid = result.product.id
        cc = ""
        cl = ""
        fl = ""
        if use_fixed_ds:
            ds = data_source
            body, skip_reason = build_merchant_product_body(result)
        else:
            cc = _country_from_product(result.product)
            cl = content_language_for_product(result.product, cc)
            fl = feed_label_for_country(cc)
            ds, err_ds = await get_ds(cc, cl, fl)
            if not ds:
                failed += 1
                details.append(
                    {
                        "product_id": pid,
                        "status": "error",
                        "message": err_ds or "Could not resolve or create API data source",
                        "target_country": cc,
                    }
                )
                await asyncio.sleep(0.1)
                continue
            body, skip_reason = build_merchant_product_body(result, content_language=cl, feed_label=fl)

        if skip_reason:
            skipped += 1
            details.append({"product_id": pid, "status": "skipped", "reason": skip_reason})
            await asyncio.sleep(0.1)
            continue
        ok, err, res_name = await insert_product(access_token, merchant_id, ds, body)
        if ok:
            inserted += 1
            oid = (body.get("offerId") or "").strip()
            if oid:
                inserted_offer_ids.append(oid)
            row: Dict[str, Any] = {"product_id": pid, "status": "inserted"}
            if oid:
                row["offer_id"] = oid
            if res_name:
                row["merchant_resource_name"] = res_name
            if not use_fixed_ds and cc:
                last_success_region = (cc, cl, fl)
                region_counts[cc] = region_counts.get(cc, 0) + 1
            details.append(row)
        else:
            failed += 1
            details.append({"product_id": pid, "status": "error", "message": err or "unknown"})
        await asyncio.sleep(0.1)

    products_api: Optional[Dict[str, Any]] = None
    merchant_verification: Optional[Dict[str, Any]] = None
    if inserted:
        await asyncio.sleep(1.0)
        merchant_verification = await verify_offer_ids_in_processed_catalog(
            access_token, merchant_id, inserted_offer_ids
        )
        products_api = await _list_processed_products_sample(access_token, merchant_id)

    if use_fixed_ds:
        summary_feed = _gmc_feed_label()
        summary_cl = _normalize_content_language_for_api(_gmc_content_language())
        summary_tc = _gmc_target_country()
    elif len(region_counts) > 1:
        summary_feed = "mixed"
        summary_cl = "mixed"
        summary_tc = "mixed"
    elif last_success_region:
        summary_tc, summary_cl, summary_feed = last_success_region
    else:
        summary_feed = _gmc_feed_label()
        summary_cl = _normalize_content_language_for_api(_gmc_content_language())
        summary_tc = _gmc_target_country()

    ds_out: Optional[str] = None
    if use_fixed_ds:
        ds_out = data_source
    elif len(ds_cache) == 1:
        ds_out = next(iter(ds_cache.values()))[0]
    elif len(ds_cache) > 1:
        ds_out = "multiple"

    out: Dict[str, Any] = {
        "merchant_id": merchant_id,
        "data_source": ds_out,
        "feed_label": summary_feed,
        "content_language": summary_cl,
        "target_country": summary_tc,
        "inserted": inserted,
        "skipped": skipped,
        "failed": failed,
        "details": details[:200],
        "processing_note": (
            "Merchant Center processes product inputs asynchronously (often 5–15 minutes). "
            "Use the same Merchant ID as in this response; in MC, open the feed that matches "
            "feed_label + content_language above (Data sources → your API primary). "
            "The overview product count may not include pending/disapproved items."
            if inserted
            else None
        ),
        "merchant_products_api": products_api,
        "merchant_verification": merchant_verification,
    }
    if not use_fixed_ds and region_counts:
        out["regions_breakdown"] = region_counts
    return out
