"""Public About us / legal entity disclosure page (FOP details)."""
from __future__ import annotations

from .legal_document_page import build_legal_document_html

_ABOUT_ARTICLE = """
<article class="legal-doc">
  <h1>About us</h1>
  <p class="legal-lead">Legal and contact information for the business that provides goods and services in connection with this website.</p>

  <section id="about-entity" aria-labelledby="about-h-entity">
    <h2 id="about-h-entity">Business entity</h2>
    <p><strong>Sole proprietor (FOP):</strong> Halahan Oleh Olehovych</p>
    <p><strong>Tax identification number (TIN):</strong> 3517315374</p>
  </section>

  <section id="about-address" aria-labelledby="about-h-address">
    <h2 id="about-h-address">Legal and actual address</h2>
    <p>29a Myru Avenue, Apt. 50<br/>
    Kryvyi Rih, Dnipropetrovsk Region<br/>
    50000, Ukraine</p>
  </section>

  <section id="about-contact" aria-labelledby="about-h-contact">
    <h2 id="about-h-contact">Contact</h2>
    <p><strong>Phone:</strong> <a href="tel:+380981755955">+380981755955</a></p>
    <p><strong>Business email (goods and services):</strong> <a href="mailto:oleh.halahan@zanzarra.com">oleh.halahan@zanzarra.com</a></p>
  </section>

  <section id="about-service" aria-labelledby="about-h-service">
    <h2 id="about-h-service">Service</h2>
    <p>The Cartozo.ai product is operated in cooperation with the above business. For general product and account questions you may also use our <a href="/contact">contact page</a> and the channels listed in our <a href="/terms">Terms of Service</a>.</p>
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
    return build_legal_document_html(
        article_html=_ABOUT_ARTICLE,
        meta_title=meta_title,
        meta_description=meta_description,
        og_title=og_title,
        og_description=og_description,
        canonical_url=canonical_url,
        og_image=og_image,
        gtm_head=gtm_head,
        gtm_body=gtm_body,
    )
