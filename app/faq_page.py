"""Public /faq — server-rendered FAQ with FAQPage JSON-LD."""
from __future__ import annotations

import html

from .legal_document_page import build_legal_document_html
from .seo import SUPPORT_EMAIL, breadcrumb_json_ld, faq_page_json_ld, organization_json_ld_graph, site_base_url, web_page_json_ld

# (section_title, [(question, answer), ...])
_FAQ_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Product",
        [
            (
                "What does Cartozo.ai do?",
                "Cartozo.ai optimizes product feeds for Google Merchant Center and similar channels. It maps your CSV fields, detects likely data gaps, improves titles and descriptions around shopper search intent, scores feed quality, and exports a Merchant-ready CSV you can review before upload.",
            ),
            (
                "Is Cartozo.ai only for Google Merchant Center?",
                "Cartozo.ai is designed primarily for Google Merchant Center and Google Shopping feed workflows. The CSV export follows Google's common product data spec, which many teams also reuse elsewhere.",
            ),
            (
                "Does Cartozo.ai rewrite titles only, or descriptions too?",
                "Both. You choose which fields to run through the intent → score → assemble pipeline. Many teams optimize titles and descriptions together.",
            ),
            (
                "Does Cartozo.ai support bulk catalogs?",
                "Yes. Cartozo.ai is built for batch CSV processing. Plan limits apply to how many products you can process per billing period—see the pricing page.",
            ),
            (
                "Does Cartozo.ai work without technical setup?",
                "Yes. Upload a UTF-8 CSV in the browser. No API integration is required to start reviewing and exporting optimized feed data.",
            ),
            (
                "Does Cartozo.ai replace a feed management platform?",
                "No. Cartozo.ai focuses on feed content quality—titles, descriptions, validation, and Merchant-ready export. It is not a full PIM, inventory, or multichannel syndication platform.",
            ),
        ],
    ),
    (
        "Google Merchant Center",
        [
            (
                "Can Cartozo.ai fix Google Merchant Center disapprovals?",
                "Cartozo.ai can help you find and fix many feed-data issues that cause disapprovals—missing attributes, weak titles, identifier problems, and similar. It does not guarantee approval; Google makes the final decision.",
            ),
            (
                "Can Cartozo.ai help with missing GTIN?",
                "It helps you spot rows with missing or invalid identifiers during mapping and review, but you must supply correct GTIN values from your product source data. See our guide on fixing missing GTIN.",
            ),
            (
                "Can Cartozo.ai validate required feed fields?",
                "Yes. Cartozo maps your columns to Merchant-style fields and surfaces validation signals during review so you can fix gaps before export.",
            ),
            (
                "Does Cartozo.ai guarantee Merchant Center approval?",
                "No. Cartozo.ai is designed to improve feed quality and make issues easier to fix. Approval depends on Google's policies, your website, and account status.",
            ),
            (
                "What product feed fields are important for Google Shopping?",
                "High-impact fields include id, title, description, link, image_link, availability, price, brand, condition, and identifiers (GTIN/MPN). See the feed structure page for a reference table.",
            ),
        ],
    ),
    (
        "Workflow",
        [
            (
                "What file format can I upload?",
                "UTF-8 CSV. Cartozo accepts standard comma-separated exports from Merchant Center, PIMs, or spreadsheets.",
            ),
            (
                "Do I need a specific CSV template?",
                "No fixed template is required. Cartozo maps your existing columns to Merchant fields during upload. A consistent export from your source system works best.",
            ),
            (
                "Can I review changes before export?",
                "Yes. Review is a core part of the workflow—you approve optimized titles and descriptions before downloading the export.",
            ),
            (
                "Can I export a Merchant-ready CSV?",
                "Yes. Cartozo exports CSV formatted for Google Merchant product data workflows after your review.",
            ),
            (
                "Can I regenerate individual products?",
                "Yes. You can regenerate or adjust individual rows during batch review instead of reprocessing the entire catalog when needed.",
            ),
        ],
    ),
    (
        "Pricing",
        [
            (
                "What is included in each plan?",
                "Plans differ by monthly product volume and features. Basic ($5/mo), Starter ($19/mo), Growth ($49/mo), and Pro ($99/mo)—see the pricing page for current limits and details.",
            ),
            (
                "What happens if I exceed my product limit?",
                "Processing may be limited until your plan resets or you upgrade. Check the pricing page and your account settings for current limits.",
            ),
            (
                "Can agencies use Cartozo.ai for multiple clients?",
                "Yes. Agencies often run separate client feeds through the same workflow. Use your internal process to keep client data separated and reviewed before delivery.",
            ),
        ],
    ),
    (
        "Data and security",
        [
            (
                "Is my product data used for training?",
                "Cartozo.ai processes your data to provide the service. For categories, retention, subprocessors, and security, read the Privacy Policy.",
            ),
            (
                "Is my data sold or shared?",
                "No—we do not sell your product feed data. Sharing is limited to what is needed to operate the service, as described in the Privacy Policy.",
            ),
            (
                "How long is uploaded feed data retained?",
                "Retention depends on your account activity and our policies. See the Privacy Policy for details on storage and deletion.",
            ),
            (
                "Who can I contact for support?",
                f"Email {SUPPORT_EMAIL} for product, billing, or technical questions.",
            ),
        ],
    ),
]


def all_faq_pairs() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for _, pairs in _FAQ_SECTIONS:
        out.extend(pairs)
    return out


def _faq_article_html() -> str:
    parts: list[str] = [
        '<article class="legal-doc">',
        "<h1>Frequently asked questions</h1>",
        '<p class="legal-lead">Answers about Cartozo.ai, Google Merchant Center feeds, workflow, pricing, and data handling.</p>',
    ]
    idx = 0
    for section_title, pairs in _FAQ_SECTIONS:
        parts.append(f'<section aria-labelledby="faq-sec-{idx}">')
        parts.append(f'  <h2 id="faq-sec-{idx}">{html.escape(section_title)}</h2>')
        for q, a in pairs:
            parts.append(f'  <h3 id="faq-q{idx}">{html.escape(q)}</h3>')
            # Allow simple internal links in answers
            safe = html.escape(a)
            safe = safe.replace("/feed-structure", '<a href="/feed-structure">/feed-structure</a>')
            safe = safe.replace("/pricing", '<a href="/pricing">pricing page</a>')
            safe = safe.replace("Privacy Policy", '<a href="/privacy">Privacy Policy</a>')
            parts.append(f"  <p>{safe}</p>")
            idx += 1
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
    base = site_base_url().rstrip("/")
    extra = (
        organization_json_ld_graph()
        + breadcrumb_json_ld(items=[("Home", f"{base}/"), ("FAQ", canonical_url)])
        + web_page_json_ld(url=canonical_url, name=meta_title, description=meta_description)
        + faq_page_json_ld(questions=all_faq_pairs())
    )
    return build_legal_document_html(
        article_html=_faq_article_html(),
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
