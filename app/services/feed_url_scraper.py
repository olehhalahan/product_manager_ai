"""
Best-effort scrape of product listing pages into Google Merchant–style CSV rows.

Limitations:
- Many storefronts render products only in the browser (SPA). Static HTML fetch may return 0 items;
  use a site that exposes JSON-LD / server HTML, or export from the source system when possible.
- Respect robots.txt and the target site's terms of use.
"""
from __future__ import annotations

import csv
import io
import json
import re
import uuid
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

# Same columns as exporter.generate_merchant_feed_csv
GMC_FEED_FIELDNAMES = [
    "id",
    "title",
    "description",
    "link",
    "image_link",
    "additional_image_link",
    "availability",
    "price",
    "sale_price",
    "brand",
    "gtin",
    "mpn",
    "condition",
    "google_product_category",
    "gender",
    "age_group",
    "color",
    "size",
    "material",
]

DEFAULT_UA = (
    "Mozilla/5.0 (compatible; CartozoFeedBot/1.0; +https://cartozo.ai) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class FeedScrapeError(Exception):
    pass


def validate_public_http_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        raise FeedScrapeError("URL is required")
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https"):
        raise FeedScrapeError("Only http and https URLs are allowed")
    if not parsed.netloc:
        raise FeedScrapeError("Invalid URL")
    return u


def _fetch(url: str, timeout: float = 30.0) -> str:
    headers = {"User-Agent": DEFAULT_UA, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.text


def _walk_json_ld(obj: Any, products_out: list[dict]) -> None:
    if isinstance(obj, dict):
        t = obj.get("@type")
        types = t if isinstance(t, list) else ([t] if t else [])
        if "Product" in types or t == "Product":
            products_out.append(obj)
        if "ItemList" in types or t == "ItemList":
            for el in obj.get("itemListElement") or []:
                if isinstance(el, dict):
                    it = el.get("item") or el
                    _walk_json_ld(it, products_out)
                else:
                    _walk_json_ld(el, products_out)
        for v in obj.values():
            _walk_json_ld(v, products_out)
    elif isinstance(obj, list):
        for x in obj:
            _walk_json_ld(x, products_out)


def _parse_json_ld_scripts(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    products: list[dict] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        _walk_json_ld(data, products)
    return products


def _schema_string_value(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, list):
        for x in v:
            s = _schema_string_value(x)
            if s:
                return s
        return ""
    if isinstance(v, dict):
        return str(v.get("name") or v.get("value") or "").strip()
    return str(v).strip()


_COLOR_LABELS = frozenset({"färg", "color", "colour", "couleur", "farbe", "farve"})
_SIZE_LABELS = frozenset({"dimensioner", "dimensions", "size", "mått", "measurements"})
_MATERIAL_LABELS = frozenset({"material", "materials", "materiale"})


def _label_category(label: str) -> str | None:
    lo = label.lower().strip()
    if lo in _COLOR_LABELS:
        return "color"
    if lo in _SIZE_LABELS:
        return "size"
    if lo in _MATERIAL_LABELS:
        return "material"
    return None


def _label_next_value(label_el) -> str:
    """Value in next sibling (e.g. Yllw: label row then value row)."""
    nxt = label_el.find_next_sibling()
    if nxt:
        v = nxt.get_text(" ", strip=True)
        lc = label_el.get_text(" ", strip=True).lower()
        if v and v.lower() != lc:
            return v[:200]
    par = label_el.parent
    if par:
        nxt2 = par.find_next_sibling()
        if nxt2:
            v2 = nxt2.get_text(" ", strip=True)
            if v2 and _label_category(v2) is None:
                return v2[:200]
    return ""


def _extract_product_specs_from_soup(soup: BeautifulSoup) -> dict[str, str]:
    """Parse common PDP spec blocks: Färg/Color, Dimensioner, Material (e.g. Yllw Factory)."""
    out: dict[str, str] = {"color": "", "size": "", "material": ""}

    for dt in soup.find_all("dt"):
        cat = _label_category(dt.get_text(" ", strip=True))
        if not cat:
            continue
        dd = dt.find_next_sibling("dd")
        if not dd:
            continue
        val = dd.get_text(" ", strip=True)
        if val and not out[cat]:
            out[cat] = val[:200]

    for tr in soup.find_all("tr"):
        th = tr.find("th")
        td = tr.find("td")
        if not th or not td:
            continue
        cat = _label_category(th.get_text(" ", strip=True))
        if not cat:
            continue
        val = td.get_text(" ", strip=True)
        if val and not out[cat]:
            out[cat] = val[:200]

    for tag in soup.find_all(True):
        if tag.name in ("script", "style", "noscript"):
            continue
        t = tag.get_text(" ", strip=True)
        if not t or len(t) > 80:
            continue
        cat = _label_category(t)
        if not cat or out[cat]:
            continue
        val = _label_next_value(tag)
        if val:
            out[cat] = val[:200]

    return out


def _merge_specs_into_row(row: dict[str, str], specs: dict[str, str]) -> None:
    for k in ("color", "size", "material"):
        if not (row.get(k) or "").strip() and (specs.get(k) or "").strip():
            row[k] = specs[k]


def _normalize_url_for_match(url: str) -> str:
    p = urlparse((url or "").strip())
    if not p.netloc:
        return ""
    path = (p.path or "").rstrip("/") or "/"
    return f"{p.scheme}://{p.netloc.lower()}{path}".lower()


def _apply_dom_specs_for_page(soup: BeautifulSoup, rows: list[dict[str, str]], page_url: str) -> None:
    """Fill color/size/material from HTML when this page is the product detail for that row."""
    specs = _extract_product_specs_from_soup(soup)
    if not any(specs.values()):
        return
    nu = _normalize_url_for_match(page_url)
    if len(rows) == 1:
        _merge_specs_into_row(rows[0], specs)
        return
    for row in rows:
        lk = (row.get("link") or "").strip()
        if lk and _normalize_url_for_match(lk) == nu:
            _merge_specs_into_row(row, specs)


def _parse_next_data(html: str) -> list[dict]:
    """Some React sites embed data in __NEXT_DATA__."""
    m = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>([\s\S]*?)</script>',
        html,
        re.I,
    )
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    products: list[dict] = []
    _walk_json_ld(data, products)
    return products


def _product_dict_to_row(p: dict, base_url: str, *, fallback_link: str = "") -> dict[str, str]:
    name = (p.get("name") or p.get("title") or "").strip()
    desc = (p.get("description") or "").strip()
    if isinstance(desc, dict):
        desc = str(desc)
    desc = unescape(re.sub(r"<[^>]+>", " ", str(desc)))[:5000]

    pid = (
        (p.get("sku") or p.get("productID") or p.get("mpn") or "").strip()
        or ""
    )
    if not pid:
        pid = re.sub(r"\W+", "-", name.lower())[:64] or str(uuid.uuid4())[:12]

    img = p.get("image") or ""
    if isinstance(img, list):
        img = img[0] if img else ""
    if isinstance(img, dict):
        img = img.get("url") or ""
    img = str(img).strip()

    brand = p.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name") or ""
    brand = str(brand or "").strip()

    link = ""
    offers = p.get("offers")
    if isinstance(offers, list) and offers:
        offers = offers[0]
    if isinstance(offers, dict):
        link = (offers.get("url") or offers.get("offerUrl") or "").strip()
        price = offers.get("price")
        cur = (offers.get("priceCurrency") or offers.get("pricecurrency") or "USD").strip()
    else:
        price = p.get("price")
        cur = (p.get("priceCurrency") or "USD").strip()

    price_s = ""
    if price is not None:
        try:
            f = float(str(price).replace(",", "."))
            price_s = f"{f:.2f} {cur.upper()}"
        except ValueError:
            price_s = f"{price} {cur.upper()}".strip()

    gtin = (p.get("gtin") or p.get("gtin13") or p.get("gtin8") or p.get("gtin14") or "").strip()
    if gtin:
        gtin = re.sub(r"\D", "", str(gtin))[:50]

    mpn = (p.get("mpn") or "").strip()[:70]

    color = _schema_string_value(p.get("color"))[:100]
    size = _schema_string_value(p.get("size"))[:100]
    material = _schema_string_value(p.get("material"))[:100]

    if link:
        link = urljoin(base_url, link)
    elif (fallback_link or "").strip():
        link = fallback_link.strip()
    if img:
        img = urljoin(base_url, img)

    return {
        "id": str(pid)[:80],
        "title": name[:150] or "Untitled",
        "description": desc if desc else (name[:5000] if name else ""),
        "link": link,
        "image_link": img,
        "additional_image_link": "",
        "availability": "in stock",
        "price": price_s,
        "sale_price": "",
        "brand": brand,
        "gtin": gtin,
        "mpn": mpn,
        "condition": "new",
        "google_product_category": "",
        "gender": "",
        "age_group": "",
        "color": color,
        "size": size,
        "material": material,
    }


_PRICE_KR = re.compile(
    r"(\d{1,3}(?:\s?\d{3})*(?:[.,]\d{2})?)\s*kr",
    re.IGNORECASE,
)

_PROMO_TITLE = re.compile(
    r"^(se våra|missa inte|behöver du|kundtjänst|meny|sök|logga|social agenda|"
    r"över\s+\d|varumärke|kategori|sortera|nuvarande sida)",
    re.I,
)


def _looks_like_product_href(href: str) -> bool:
    low = href.lower()
    return any(
        x in low
        for x in ("/produkt", "/product", "/p/", "/item/", "/shop/", "/varor/")
    )


def _heuristic_cards(soup: BeautifulSoup, base_url: str, max_products: int) -> list[dict[str, str]]:
    """Very loose heuristics for listing pages without JSON-LD."""
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    # Prefer article blocks or elements with product links
    for art in soup.find_all(["article", "div"], class_=re.compile(r"product|item|card", re.I), limit=200):
        if len(rows) >= max_products:
            break
        a = art.find("a", href=True)
        if not a:
            continue
        href = urljoin(base_url, a["href"])
        if href in seen:
            continue
        path = urlparse(href).path.lower()
        if path in ("/", "") or "javascript:" in href.lower():
            continue
        text_blob = art.get_text(" ", strip=True)
        price_s = ""
        m = _PRICE_KR.search(text_blob)
        if m:
            num = m.group(1).replace(" ", "").replace(",", ".")
            try:
                price_s = f"{float(num):.2f} SEK"
            except ValueError:
                price_s = f"{m.group(1)} SEK"
        if not price_s and not _looks_like_product_href(href):
            continue

        title_el = art.find(["h1", "h2", "h3", "h4"]) or a
        title = title_el.get_text(" ", strip=True) if title_el else ""
        title = unescape(re.sub(r"\s+", " ", title))[:150]
        if len(title) < 4 or _PROMO_TITLE.search(title.strip()):
            continue

        brand_el = art.find(class_=re.compile(r"brand|manufacturer|vendor", re.I))
        brand = brand_el.get_text(" ", strip=True)[:100] if brand_el else ""

        pid = href.split("/")[-1].split("?")[0][:80] or str(uuid.uuid4())[:12]
        seen.add(href)
        rows.append(
            {
                "id": pid,
                "title": title,
                "description": title[:5000],
                "link": href,
                "image_link": "",
                "additional_image_link": "",
                "availability": "in stock",
                "price": price_s,
                "sale_price": "",
                "brand": brand,
                "gtin": "",
                "mpn": "",
                "condition": "new",
                "google_product_category": "",
                "gender": "",
                "age_group": "",
                "color": "",
                "size": "",
                "material": "",
            }
        )

    if len(rows) >= max_products:
        return rows[:max_products]

    # Fallback: standalone links that look like product pages + nearby heading
    for a in soup.find_all("a", href=True, limit=400):
        if len(rows) >= max_products:
            break
        href = urljoin(base_url, a["href"])
        if href in seen:
            continue
        if not _looks_like_product_href(href):
            continue
        title = unescape(a.get_text(" ", strip=True))[:150]
        if len(title) < 4 or _PROMO_TITLE.search(title.strip()):
            continue
        pid = href.split("/")[-1].split("?")[0][:80] or str(uuid.uuid4())[:12]
        seen.add(href)
        rows.append(
            {
                "id": pid,
                "title": title,
                "description": title[:5000],
                "link": href,
                "image_link": "",
                "additional_image_link": "",
                "availability": "in stock",
                "price": "",
                "sale_price": "",
                "brand": "",
                "gtin": "",
                "mpn": "",
                "condition": "new",
                "google_product_category": "",
                "gender": "",
                "age_group": "",
                "color": "",
                "size": "",
                "material": "",
            }
        )

    return rows[:max_products]


def _enrich_from_detail(row: dict[str, str], html: str, page_url: str) -> None:
    soup = BeautifulSoup(html, "html.parser")
    base = f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}"
    og_img = soup.find("meta", property="og:image")
    if og_img and og_img.get("content") and not row.get("image_link"):
        row["image_link"] = urljoin(page_url, og_img["content"].strip())
    og_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
    if og_desc and og_desc.get("content") and len((row.get("description") or "")) < 80:
        row["description"] = unescape(og_desc["content"].strip())[:5000]
    for p in _parse_json_ld_scripts(html):
        if not isinstance(p, dict):
            continue
        if (p.get("name") or "").strip() and (p.get("name") or "").strip()[:80] == row.get("title", "")[:80]:
            r2 = _product_dict_to_row(p, base, fallback_link=page_url)
            if r2.get("image_link"):
                row["image_link"] = r2["image_link"]
            if r2.get("price"):
                row["price"] = r2["price"]
            if r2.get("description") and len(r2["description"]) > len(row.get("description") or ""):
                row["description"] = r2["description"]
            for k in ("color", "size", "material"):
                if (r2.get(k) or "").strip() and not (row.get(k) or "").strip():
                    row[k] = r2[k]
            break
    specs = _extract_product_specs_from_soup(soup)
    _merge_specs_into_row(row, specs)


def scrape_url_to_rows(
    url: str,
    *,
    max_products: int = 100,
    detail_pages: int = 0,
) -> tuple[list[dict[str, str]], list[str]]:
    """
    Fetch one listing URL and return GMC-shaped rows + human-readable warnings.
    detail_pages: fetch up to N product URLs for og:image / schema (sequential).
    """
    warnings: list[str] = []
    u = validate_public_http_url(url)
    max_products = max(1, min(int(max_products), 500))
    detail_pages = max(0, min(int(detail_pages), 50))

    try:
        html = _fetch(u)
    except httpx.HTTPError as e:
        raise FeedScrapeError(f"Could not fetch URL: {e}") from e

    base = f"{urlparse(u).scheme}://{urlparse(u).netloc}"

    rows: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    for p in _parse_json_ld_scripts(html):
        if len(rows) >= max_products:
            break
        if not isinstance(p, dict):
            continue
        row = _product_dict_to_row(p, base, fallback_link=u)
        if row["id"] in seen_ids:
            row["id"] = f"{row['id']}-{len(seen_ids)}"
        seen_ids.add(row["id"])
        rows.append(row)

    if not rows:
        for p in _parse_next_data(html):
            if len(rows) >= max_products:
                break
            row = _product_dict_to_row(p, base, fallback_link=u)
            if row["id"] in seen_ids:
                continue
            seen_ids.add(row["id"])
            rows.append(row)

    if not rows:
        soup = BeautifulSoup(html, "html.parser")
        rows = _heuristic_cards(soup, u, max_products)
        if rows:
            warnings.append(
                "Products were detected with heuristics only (no JSON-LD). "
                "Verify titles, links, and prices before uploading to Merchant Center."
            )

    if not rows:
        warnings.append(
            "No products found in the HTML. The page may load catalog data only in the browser (JavaScript). "
            "Try an HTML source that includes JSON-LD Product markup, or export a CSV from your store admin."
        )
        return [], warnings

    soup_main = BeautifulSoup(html, "html.parser")
    _apply_dom_specs_for_page(soup_main, rows, u)

    if detail_pages and rows:
        for i, row in enumerate(rows[:detail_pages]):
            link = (row.get("link") or "").strip()
            if not link:
                continue
            try:
                dhtml = _fetch(link, timeout=20.0)
                _enrich_from_detail(row, dhtml, link)
            except httpx.HTTPError:
                warnings.append(f"Could not fetch detail page: {link[:80]}…")

    return rows[:max_products], warnings


def rows_to_csv_bytes(rows: list[dict[str, str]]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=GMC_FEED_FIELDNAMES, extrasaction="ignore")
    w.writeheader()
    for row in rows:
        w.writerow({k: row.get(k, "") for k in GMC_FEED_FIELDNAMES})
    return buf.getvalue().encode("utf-8")
