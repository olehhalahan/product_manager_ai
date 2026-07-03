"""Public /feed-structure — Google Merchant product feed field reference."""
from __future__ import annotations

from .legal_document_page import build_legal_document_html
from .seo import BRAND_DESCRIPTION, breadcrumb_json_ld, organization_json_ld_graph, web_page_json_ld

_ARTICLE = """
<article class="legal-doc">
  <h1>Google Merchant product feed structure</h1>
  <p class="legal-lead">A practical reference to common Google Merchant Center product data fields Cartozo.ai maps, validates, and optimizes when you upload a CSV.</p>

  <section>
    <h2>Required and high-impact fields</h2>
    <table style="width:100%;border-collapse:collapse;font-size:.9rem">
      <tr><th style="text-align:left;padding:8px;border-bottom:1px solid rgba(255,255,255,.1)">Field</th><th style="text-align:left;padding:8px;border-bottom:1px solid rgba(255,255,255,.1)">Why it matters</th></tr>
      <tr><td style="padding:8px">id</td><td style="padding:8px">Stable product identifier in your feed</td></tr>
      <tr><td style="padding:8px">title</td><td style="padding:8px">Primary Shopping listing text; should include key attributes</td></tr>
      <tr><td style="padding:8px">description</td><td style="padding:8px">Product details aligned with title and landing page</td></tr>
      <tr><td style="padding:8px">link</td><td style="padding:8px">Product landing page URL</td></tr>
      <tr><td style="padding:8px">image_link</td><td style="padding:8px">Main product image</td></tr>
      <tr><td style="padding:8px">availability</td><td style="padding:8px">in stock / out of stock / preorder</td></tr>
      <tr><td style="padding:8px">price</td><td style="padding:8px">Price with currency (must match landing page)</td></tr>
      <tr><td style="padding:8px">brand</td><td style="padding:8px">Brand name (required for many product types)</td></tr>
      <tr><td style="padding:8px">gtin / mpn</td><td style="padding:8px">Product identifiers; missing GTIN is a common disapproval cause</td></tr>
      <tr><td style="padding:8px">condition</td><td style="padding:8px">new / refurbished / used</td></tr>
      <tr><td style="padding:8px">google_product_category</td><td style="padding:8px">Google taxonomy for category matching</td></tr>
    </table>
  </section>

  <section>
    <h2>How Cartozo.ai uses your feed</h2>
    <p>Upload a UTF-8 CSV, map your columns to these fields, review intent-aware title and description improvements, score quality, and export a Merchant-ready CSV. Cartozo.ai is designed to make structured feed cleanup faster—not to replace Merchant Center policy review.</p>
    <p><a href="/how-it-works">See the workflow</a> · <a href="/guides/google-merchant-center-feed-optimization">Read the optimization guide</a></p>
  </section>
</article>
"""


def build_feed_structure_html(
    *,
    meta_title: str,
    meta_description: str,
    og_title: str,
    og_description: str,
    canonical_url: str,
    og_image: str = "",
    gtm_head: str,
    gtm_body: str,
) -> str:
    base = canonical_url.rsplit("/feed-structure", 1)[0]
    extra = (
        organization_json_ld_graph()
        + breadcrumb_json_ld(items=[("Home", f"{base}/"), ("Feed structure", canonical_url)])
        + web_page_json_ld(url=canonical_url, name=meta_title, description=meta_description)
    )
    return build_legal_document_html(
        article_html=_ARTICLE,
        meta_title=meta_title,
        meta_description=meta_description,
        og_title=og_title,
        og_description=og_description,
        canonical_url=canonical_url,
        og_image=og_image,
        extra_head=extra,
        gtm_head=gtm_head,
        gtm_body=gtm_body,
    )
