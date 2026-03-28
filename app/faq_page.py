"""Public /faq — server-rendered FAQ with FAQPage JSON-LD."""
from __future__ import annotations

import html

from .legal_document_page import build_legal_document_html
from .seo import faq_page_json_ld

_FAQ_QA: list[tuple[str, str]] = [
    (
        "What does Cartozo.ai do?",
        "Cartozo.ai optimizes product feeds for Google Merchant Center and similar channels. "
        "Instead of a simple AI rewrite, it runs a decision layer: infer likely shopper search intents, score them, pick the best few, "
        "then assemble titles and descriptions grounded in your data. You also get mapping, validation, and batch export.",
    ),
    (
        "Do I need Google Merchant Center to start?",
        "You can upload a CSV to review and improve feed quality without connecting Merchant Center first. Connecting Merchant Center unlocks publishing workflows where supported.",
    ),
    (
        "How is my data protected?",
        "We process your data to provide the service. For details on categories, retention, and security, read our Privacy Policy.",
    ),
    (
        "How do refunds work?",
        "Refund eligibility depends on your plan, region, and payment provider. See our Refund Policy for full terms and how to request a refund.",
    ),
    (
        "Who can I contact for support?",
        "Email support@cartozo.ai for product, billing, or technical questions.",
    ),
]


def _faq_article_html(qa: list[tuple[str, str]]) -> str:
    parts: list[str] = [
        '<article class="legal-doc">',
        "<h1>Frequently asked questions</h1>",
        '<p class="legal-lead">Quick answers about Cartozo.ai, product feeds, and your account.</p>',
    ]
    for i, (q, a) in enumerate(qa):
        parts.append(f'<section aria-labelledby="faq-h{i}">')
        parts.append(f'  <h2 id="faq-h{i}">{html.escape(q)}</h2>')
        parts.append(f"  <p>{html.escape(a)}</p>")
        parts.append("</section>")
    parts.append("</article>")
    return "\n".join(parts)


def build_faq_html(
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
    article = _faq_article_html(_FAQ_QA)
    extra = faq_page_json_ld(questions=_FAQ_QA)
    return build_legal_document_html(
        article_html=article,
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
