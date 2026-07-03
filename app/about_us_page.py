"""Public About us — product trust + legal entity disclosure."""
from __future__ import annotations

from .legal_document_page import build_legal_document_html
from .seo import BRAND_DESCRIPTION, SUPPORT_EMAIL, breadcrumb_json_ld, organization_json_ld_graph, web_page_json_ld

_ABOUT_ARTICLE = f"""
<article class="legal-doc">
  <h1>About Cartozo.ai</h1>
  <p class="legal-lead">{BRAND_DESCRIPTION}</p>

  <section id="about-product" aria-labelledby="about-h-product">
    <h2 id="about-h-product">What Cartozo.ai is</h2>
    <p>Cartozo.ai helps e-commerce teams, performance marketers, and agencies improve Google Merchant Center and Google Shopping product feeds. Upload a CSV, map your fields, review intent-aware title and description improvements, score feed quality, and export a Merchant-ready file.</p>
    <p><a href="/how-it-works">How it works</a> · <a href="/pricing">Pricing</a> · <a href="/faq">FAQ</a></p>
  </section>

  <section id="about-for" aria-labelledby="about-h-for">
    <h2 id="about-h-for">Who it is for</h2>
    <ul>
      <li>E-commerce managers responsible for Shopping feed quality</li>
      <li>Performance marketers reducing Merchant Center disapprovals</li>
      <li>Agencies optimizing client product catalogs in batches</li>
      <li>Teams with large SKU counts that outgrow spreadsheet edits</li>
    </ul>
  </section>

  <section id="about-why" aria-labelledby="about-h-why">
    <h2 id="about-h-why">Why it exists</h2>
    <p>Product feed quality directly affects whether items serve in Google Shopping and how clearly they match shopper intent. Cartozo.ai was built to make structured feed cleanup and title/description optimization faster than manual spreadsheet work—without replacing Merchant Center or your existing feed tools.</p>
  </section>

  <section id="about-data" aria-labelledby="about-h-data">
    <h2 id="about-h-data">Data and security</h2>
    <p>We process your product data to provide the service. Read our <a href="/privacy">Privacy Policy</a> for retention, security, and subprocessors. Cartozo.ai does not sell your feed data.</p>
  </section>

  <section id="about-support" aria-labelledby="about-h-support">
    <h2 id="about-h-support">Support</h2>
    <p>Product and billing support: <a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a></p>
    <p>General inquiries: <a href="/contact">Contact form</a></p>
  </section>

  <section id="about-entity" aria-labelledby="about-h-entity">
    <h2 id="about-h-entity">Legal operator</h2>
    <p><strong>Sole proprietor (FOP):</strong> Halahan Oleh Olehovych</p>
    <p><strong>Tax identification number (TIN):</strong> 3517315374</p>
    <p><strong>Legal and actual address:</strong> 29a Myru Avenue, Apt. 50, Kryvyi Rih, Dnipropetrovsk Region, 50000, Ukraine</p>
    <p><strong>Business operator email (legal / goods and services):</strong> <a href="mailto:oleh.halahan@zanzarra.com">oleh.halahan@zanzarra.com</a></p>
    <p>See also our <a href="/terms">Terms of Service</a> and <a href="/refund-policy">Refund Policy</a>.</p>
  </section>

  <section id="about-zanzarra" aria-labelledby="about-h-z">
    <h2 id="about-h-z">Built by Zanzarra</h2>
    <p>Cartozo.ai is developed in cooperation with <a href="https://zanzarra.com/" target="_blank" rel="noopener noreferrer">Zanzarra</a>.</p>
  </section>
</article>
"""


def build_about_us_html(
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
    base = canonical_url.rsplit("/about", 1)[0]
    extra = (
        organization_json_ld_graph()
        + breadcrumb_json_ld(items=[("Home", f"{base}/"), ("About", canonical_url)])
        + web_page_json_ld(url=canonical_url, name=meta_title, description=meta_description)
    )
    return build_legal_document_html(
        article_html=_ABOUT_ARTICLE,
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
