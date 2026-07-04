"""Public fictional product feed examples and CSV template landing pages."""
from __future__ import annotations

import html

from fastapi import Request
from fastapi.responses import FileResponse, HTMLResponse

from .air_design import site_page_shell_css
from .gtm import GTM_BODY, GTM_HEAD
from .public_nav import HP_FOOTER_CSS, HP_NAV_CSS, public_site_footer_html, public_site_nav_html, public_site_theme_toggle_script
from .seo import (
    BRAND_NAME,
    breadcrumb_json_ld,
    dataset_json_ld,
    head_canonical_social,
    organization_json_ld_graph,
    rss_feed_link_tag,
    site_base_url,
    web_page_json_ld,
)

_TEMPLATE_DOWNLOADS = [
    (
        "/templates/google-merchant-center-feed-template.csv",
        "Google Merchant Center feed template (CSV)",
    ),
    ("/templates/sample-product-feed-before.csv", "Sample product feed — before optimization"),
    ("/templates/sample-product-feed-after.csv", "Sample product feed — after optimization"),
]

_SHARED_CSS = site_page_shell_css() + """
.ap-example{display:grid;gap:12px;margin:16px 0}
@media(min-width:640px){.ap-example{grid-template-columns:1fr 1fr}}
"""


def _esc(s: str) -> str:
    return html.escape(s or "", quote=False)


def _page_shell(
    *,
    path: str,
    title: str,
    description: str,
    breadcrumb: list[tuple[str, str]],
    body_html: str,
    extra_json_ld: str = "",
    og_image: str = "",
) -> str:
    base = site_base_url().rstrip("/")
    canonical = f"{base}{path}"
    crumbs = breadcrumb_json_ld(items=breadcrumb)
    page_ld = web_page_json_ld(url=canonical, name=title, description=description)
    json_ld = organization_json_ld_graph() + crumbs + page_ld + (extra_json_ld or "")
    seo = head_canonical_social(
        canonical_url=canonical,
        og_title=title,
        og_description=description,
        og_image=og_image,
        og_site_name=BRAND_NAME,
        og_type="website",
    )
    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
{GTM_HEAD}
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(description)}"/>
<meta name="robots" content="index,follow"/>
{seo}
{rss_feed_link_tag()}
<script>try{{document.documentElement.setAttribute('data-theme',localStorage.getItem('hp-theme')||'dark')}}catch(e){{}}</script>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:var(--hp-font);background:var(--hp-bg,#100904);color:var(--hp-text,#ffedd7);line-height:1.5;-webkit-font-smoothing:antialiased}}
{_SHARED_CSS}
{HP_NAV_CSS}
{HP_FOOTER_CSS}
</style>
{json_ld}
</head>
<body>
{GTM_BODY}
{public_site_nav_html()}
<main class="ap-wrap">
{body_html}
</main>
{public_site_footer_html()}
<script>{public_site_theme_toggle_script().strip()}</script>
<script src="/static/page-transition.js"></script>
</body>
</html>"""


def _examples_index_html() -> str:
    base = site_base_url().rstrip("/")
    downloads = "".join(
        f'<li><a href="{_esc(href)}">{_esc(label)}</a></li>' for href, label in _TEMPLATE_DOWNLOADS
    )
    body = f"""
<nav class="ap-bc" aria-label="Breadcrumb"><a href="/">Home</a> · Examples</nav>
<h1 class="ap-h1">Product feed examples and CSV templates</h1>
<p class="ap-lead">Fictional Google Shopping feed examples you can study, cite, and download. All data is illustrative — not real customer catalogs.</p>
<div class="ap-box">
<h2>Example pages</h2>
<ul class="ap-dl-list">
<li><a href="/examples/google-shopping-feed-before-after">Google Shopping feed before/after table</a></li>
<li><a href="/examples/product-title-optimization-examples">20+ product title optimization examples</a></li>
<li><a href="/examples/product-feed-quality-audit-example">Feed quality audit example</a></li>
</ul>
</div>
<div class="ap-box">
<h2>Downloadable CSV templates</h2>
<ul class="ap-dl-list">{downloads}</ul>
<p class="ap-note">Templates use fictional SKUs and example.com URLs. They are not performance guarantees or Merchant Center approvals.</p>
</div>
<div class="ap-cta">
<p>Want to analyze your own feed?</p>
<a href="/login">Upload your feed</a>
<a href="/pricing" class="secondary">View pricing</a>
</div>
"""
    ds = dataset_json_ld(
        name="Cartozo.ai sample product feed templates",
        description="Fictional Google Merchant Center CSV templates and before/after sample feeds.",
        url=f"{base}/examples",
        downloads=[
            {"name": label, "contentUrl": f"{base}{href}", "encodingFormat": "text/csv"}
            for href, label in _TEMPLATE_DOWNLOADS
        ],
        date_published="2026-07-03",
        date_modified="2026-07-03",
    )
    return _page_shell(
        path="/examples",
        title="Product Feed Examples and CSV Templates — Cartozo.ai",
        description="Fictional Google Shopping feed before/after examples, title optimization samples, and downloadable Merchant Center CSV templates.",
        breadcrumb=[("Home", f"{base}/"), ("Examples", f"{base}/examples")],
        body_html=body,
        extra_json_ld=ds,
    )


def _before_after_html() -> str:
    base = site_base_url().rstrip("/")
    rows = [
        ("SKU-301", "Shoe", "Men's Trail Running Shoe Blue 42 — Waterproof", "Good shoe.", "Waterproof men's trail shoe with mesh upper and rubber outsole.", "TrailForge", "012345678905", "Shoes", "Missing attributes; generic title", "Added product type, brand, size, intent"),
        ("SKU-302", "Chair", "Oak Dining Chair Black — Solid Wood", "Nice chair.", "Modern oak dining chair with solid wood seat.", "HomeCo", "", "Dining chair", "Vague title; missing brand in title", "Structured title with material and use"),
        ("SKU-303", "Phone case", "iPhone 15 Pro Clear Case — Shockproof TPU", "Protective case.", "Shockproof clear TPU case with raised edges.", "ShieldTech", "012345678936", "Phone case", "Missing device model", "Added compatible device and material"),
    ]
    trs = ""
    for rid, tb, ta, db, da, brand, gtin, ptype, issue, reason in rows:
        trs += (
            f"<tr><td>{_esc(rid)}</td><td>{_esc(tb)}</td><td>{_esc(ta)}</td>"
            f"<td>{_esc(db)}</td><td>{_esc(da)}</td><td>{_esc(brand)}</td><td>{_esc(gtin)}</td>"
            f"<td>{_esc(ptype)}</td><td>{_esc(issue)}</td><td>{_esc(reason)}</td></tr>"
        )
    body = f"""
<nav class="ap-bc"><a href="/">Home</a> · <a href="/examples">Examples</a> · Before/after feed</nav>
<h1 class="ap-h1">Google Shopping feed before and after example</h1>
<p class="ap-lead">Illustrative fictional rows showing how clearer titles and descriptions improve attribute coverage. Results vary by catalog and Merchant Center policies.</p>
<div class="ap-table-wrap"><table class="ap-table">
<thead><tr><th>id</th><th>title_before</th><th>title_after</th><th>description_before</th><th>description_after</th><th>brand</th><th>gtin</th><th>product_type</th><th>issue_detected</th><th>improvement_reason</th></tr></thead>
<tbody>{trs}</tbody></table></div>
<p class="ap-note">Limitations: examples are illustrative only. They do not guarantee approval, ranking, or ROAS improvements.</p>
<p>Related: <a href="/use-cases/fix-google-merchant-center-disapprovals">Fix disapprovals</a> ·
<a href="/use-cases/optimize-google-shopping-product-titles">Title optimization</a> ·
<a href="/guides/google-merchant-center-feed-optimization">Feed optimization guide</a> ·
<a href="/feed-structure">Feed structure</a></p>
<div class="ap-cta"><a href="/login">Try Cartozo.ai on your feed</a></div>
"""
    return _page_shell(
        path="/examples/google-shopping-feed-before-after",
        title="Google Shopping Feed Before/After Example — Cartozo.ai",
        description="Fictional before and after Google Shopping product feed rows with issue detection and improvement notes.",
        breadcrumb=[("Home", f"{base}/"), ("Examples", f"{base}/examples"), ("Before/after", f"{base}/examples/google-shopping-feed-before-after")],
        body_html=body,
    )


def _title_examples_html() -> str:
    base = site_base_url().rstrip("/")
    examples = [
        ("Apparel", "Shoe", "Men's Trail Running Shoe Blue Size 42 — Waterproof", "Product type + gender + attributes + intent modifier"),
        ("Apparel", "Dress", "Women's Linen Midi Dress Sage Green Size M", "Category + material + color + size"),
        ("Furniture", "Chair", "Oak Dining Chair Black — Solid Wood Seat", "Material + product type + color + detail"),
        ("Furniture", "Desk", "Standing Desk White 120cm — Electric Adjustable", "Product type + color + dimension + feature"),
        ("Electronics", "Headphones", "Wireless Noise Cancelling Headphones Black — 40h Battery", "Key features + color + spec"),
        ("Electronics", "Case", "Samsung Galaxy S24 Clear Case — Shockproof TPU", "Brand/device + product type + material"),
        ("Beauty", "Serum", "Vitamin C Face Serum 30ml — Brightening Daily Use", "Ingredient + product type + size + benefit"),
        ("Beauty", "Shampoo", "Sulfate-Free Shampoo 250ml — Color-Treated Hair", "Formula + size + hair type"),
        ("Home goods", "Bottle", "Insulated Water Bottle 750ml Stainless Steel — Black", "Feature + size + material + color"),
        ("Home goods", "Bedding", "Cotton Queen Duvet Cover Set White — 3 Piece", "Material + size + product type + color + count"),
        ("Apparel", "Jacket", "Jacket", "Too generic — missing type and attributes"),
        ("Furniture", "Table", "Table wood", "Missing product type clarity and dimensions"),
        ("Electronics", "Cable", "USB cable", "Missing connector type, length, compatibility"),
        ("Beauty", "Cream", "Moisturizer", "Missing size, skin type, key ingredient"),
        ("Home goods", "Lamp", "Light", "Missing product category and specs"),
        ("Apparel", "Sneakers", "Women's White Leather Sneakers Size 38 — Low Top", "Structured title for footwear"),
        ("Furniture", "Sofa", "3-Seat Fabric Sofa Gray — Removable Covers", "Seating capacity + material + color + feature"),
        ("Electronics", "Monitor", "27 Inch 4K Monitor IPS — USB-C 65W", "Size + resolution + panel + connectivity"),
        ("Beauty", "Lipstick", "Matte Lipstick Rose Nude — Long-Wear 3.5g", "Finish + shade + benefit + weight"),
        ("Home goods", "Pan", "Nonstick Frying Pan 28cm — Induction Compatible", "Coating + type + size + compatibility"),
        ("Apparel", "Hoodie", "Unisex Cotton Hoodie Navy XL — Fleece Lined", "Gender scope + material + color + size + feature"),
    ]
    trs = "".join(
        f"<tr><td>{_esc(cat)}</td><td>{_esc(weak)}</td><td>{_esc(strong)}</td><td>{_esc(reason)}</td></tr>"
        for cat, weak, strong, reason in examples
    )
    body = f"""
<nav class="ap-bc"><a href="/">Home</a> · <a href="/examples">Examples</a> · Title optimization</nav>
<h1 class="ap-h1">Product title optimization examples</h1>
<p class="ap-lead">Twenty fictional Google Shopping title pairs across apparel, furniture, electronics, beauty, and home goods. Strong titles lead with product type, then brand/key attributes, size/color/material, and intent where appropriate.</p>
<div class="ap-table-wrap"><table class="ap-table">
<thead><tr><th>Category</th><th>Weak title</th><th>Improved title</th><th>Reason</th></tr></thead>
<tbody>{trs}</tbody></table></div>
<p class="ap-note">Avoid trademark misuse and unsupported claims. Titles should stay readable within Merchant field limits.</p>
<p>Related: <a href="/guides/google-shopping-title-optimization">Title optimization guide</a> ·
<a href="/use-cases/optimize-google-shopping-product-titles">Use case</a></p>
<div class="ap-cta"><a href="/login">Optimize your titles</a></div>
"""
    return _page_shell(
        path="/examples/product-title-optimization-examples",
        title="Product Title Optimization Examples — Cartozo.ai",
        description="20+ fictional Google Shopping title before/after examples across apparel, furniture, electronics, beauty, and home goods.",
        breadcrumb=[("Home", f"{base}/"), ("Examples", f"{base}/examples"), ("Title examples", f"{base}/examples/product-title-optimization-examples")],
        body_html=body,
    )


def _audit_example_html() -> str:
    base = site_base_url().rstrip("/")
    rows = [
        ("SKU-401", "72", "Missing GTIN on brand-required category", "Add valid GTIN or valid MPN+brand pair"),
        ("SKU-402", "58", "Weak title — generic 'Shoe'", "Expand title with type, brand, size, color"),
        ("SKU-403", "61", "Missing brand", "Populate brand attribute"),
        ("SKU-404", "55", "Vague description", "Add product-specific attributes and use case"),
        ("SKU-405", "63", "Inconsistent product_type", "Align product_type with google_product_category"),
        ("SKU-406", "49", "Missing image_link", "Add primary image URL"),
        ("SKU-407", "66", "Invalid availability vs landing page", "Sync availability with site stock"),
    ]
    trs = "".join(
        f"<tr><td>{_esc(sku)}</td><td>{_esc(score)}</td><td>{_esc(issue)}</td><td>{_esc(fix)}</td></tr>"
        for sku, score, issue, fix in rows
    )
    body = f"""
<nav class="ap-bc"><a href="/">Home</a> · <a href="/examples">Examples</a> · Quality audit</nav>
<h1 class="ap-h1">Product feed quality audit example</h1>
<p class="ap-lead">Fictional audit scores (0–100) showing common feed issues Cartozo.ai flags during CSV review. Scores are illustrative — not guarantees of Merchant Center outcomes.</p>
<div class="ap-box"><h2>Sample audit summary</h2><p>Average score before review: <strong>60</strong> · After prioritized fixes (example batch): <strong>78</strong></p></div>
<div class="ap-table-wrap"><table class="ap-table">
<thead><tr><th>SKU</th><th>Score</th><th>Issue</th><th>Suggested fix</th></tr></thead>
<tbody>{trs}</tbody></table></div>
<p>Related: <a href="/use-cases/product-feed-quality-audit">Quality audit use case</a> ·
<a href="/guides/product-feed-quality-audit">Audit guide</a></p>
<div class="ap-cta"><a href="/login">Upload and analyze your feed</a></div>
"""
    return _page_shell(
        path="/examples/product-feed-quality-audit-example",
        title="Product Feed Quality Audit Example — Cartozo.ai",
        description="Fictional product feed quality audit table with scores and common Google Merchant Center issue examples.",
        breadcrumb=[("Home", f"{base}/"), ("Examples", f"{base}/examples"), ("Quality audit", f"{base}/examples/product-feed-quality-audit-example")],
        body_html=body,
    )


def register_example_routes(app) -> None:
    @app.get("/examples", response_class=HTMLResponse, include_in_schema=False)
    def examples_index(_request: Request):
        return HTMLResponse(content=_examples_index_html())

    @app.get("/examples/google-shopping-feed-before-after", response_class=HTMLResponse, include_in_schema=False)
    def examples_before_after(_request: Request):
        return HTMLResponse(content=_before_after_html())

    @app.get("/examples/product-title-optimization-examples", response_class=HTMLResponse, include_in_schema=False)
    def examples_titles(_request: Request):
        return HTMLResponse(content=_title_examples_html())

    @app.get("/examples/product-feed-quality-audit-example", response_class=HTMLResponse, include_in_schema=False)
    def examples_audit(_request: Request):
        return HTMLResponse(content=_audit_example_html())

    @app.get("/templates/{filename}", include_in_schema=False)
    def template_csv(filename: str):
        allowed = {
            "google-merchant-center-feed-template.csv",
            "sample-product-feed-before.csv",
            "sample-product-feed-after.csv",
        }
        if filename not in allowed:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Not found")
        from pathlib import Path

        path = Path(__file__).resolve().parent.parent / "static" / "templates" / filename
        if not path.is_file():
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(
            path,
            media_type="text/csv; charset=utf-8",
            headers={"X-Robots-Tag": "noindex, nofollow"},
        )
