"""Evergreen buyer guides for AI search visibility."""
from __future__ import annotations

from typing import Callable, Dict

from fastapi import Request
from fastapi.responses import HTMLResponse

from .answer_page import AnswerPageSpec, FaqItem, build_answer_page_html


def _guide_sections_checklist() -> list[tuple[str, str, str]]:
    return [
        (
            "checklist",
            "Feed optimization checklist",
            "<ul>"
            "<li>Confirm required fields: id, title, description, link, image_link, availability, price, brand, condition</li>"
            "<li>Validate GTIN/MPN rules for your product types</li>"
            "<li>Check title length and attribute coverage (brand, size, color where relevant)</li>"
            "<li>Review disapproved or limited products in Merchant Center</li>"
            "<li>Export, review, and re-upload in a controlled batch</li>"
            "</ul>",
        ),
        (
            "mistakes",
            "Common mistakes",
            "<ul>"
            "<li>Generic titles with no distinguishing attributes</li>"
            "<li>Missing or invalid GTINs on products that require them</li>"
            "<li>Descriptions copied from the homepage with no product specifics</li>"
            "<li>Inconsistent availability or price between feed and landing page</li>"
            "</ul>",
        ),
    ]


GUIDE_PAGES: Dict[str, AnswerPageSpec] = {
    "google-merchant-center-feed-optimization": AnswerPageSpec(
        path="/guides/google-merchant-center-feed-optimization",
        page_kind="guide",
        meta_title="Google Merchant Center Feed Optimization Guide — Cartozo.ai",
        meta_description="Step-by-step guide to optimizing a Google Merchant Center product feed: required fields, title quality, validation, and export workflow.",
        h1="Google Merchant Center feed optimization",
        direct_answer=(
            "Optimizing a Google Merchant Center feed means aligning your product data with Google's required attributes, strengthening titles and descriptions for shopper intent, and validating rows before upload. "
            "This guide covers a practical workflow teams can run before every major catalog push."
        ),
        who_for="E-commerce managers and feed specialists responsible for Google Shopping catalog quality.",
        problems=["Incomplete attributes", "Weak titles", "Manual QA bottlenecks", "Repeated disapprovals after upload"],
        how_helps=[
            "Upload CSV and map columns to Merchant fields",
            "Score and improve titles/descriptions in batch",
            "Review changes before export",
            "Download Merchant-ready CSV",
        ],
        example_before="id,title,description,price\nSKU1,Shoe,Good shoe,29.99 USD",
        example_after="id,title,description,price\nSKU1,Men's Trail Shoe Blue 42 — Waterproof,Waterproof men's trail shoe with rubber outsole…,29.99 USD",
        limitations=["Does not replace Merchant Center policy review", "Site and landing page issues may remain outside the feed"],
        guide_sections=[
            ("summary", "Quick summary", "<p>Start with a CSV export, map fields, fix high-impact attribute gaps, improve titles, validate, then upload in batches.</p>"),
            ("steps", "Step-by-step process", "<ol><li>Export current feed from Merchant Center or your PIM</li><li>Map columns to required Merchant attributes</li><li>Fix missing GTIN, brand, image_link, and availability issues</li><li>Improve titles and descriptions for search intent</li><li>Review flagged rows and export Merchant-ready CSV</li><li>Upload and monitor disapprovals in Merchant Center</li></ol>"),
        ]
        + _guide_sections_checklist(),
        faq=[
            FaqItem("How often should I optimize my feed?", "Many teams review monthly or before major campaign pushes; high-change catalogs may need weekly checks on disapproved items."),
        ],
        related_links=[("/use-cases/fix-google-merchant-center-disapprovals", "Fix disapprovals use case"), ("/feed-structure", "Feed structure reference")],
    ),
    "google-shopping-title-optimization": AnswerPageSpec(
        path="/guides/google-shopping-title-optimization",
        page_kind="guide",
        meta_title="Google Shopping Title Optimization Guide — Cartozo.ai",
        meta_description="Practical guide to optimizing Google Shopping product titles: attributes, intent, examples, and a review checklist.",
        h1="Google Shopping title optimization",
        direct_answer=(
            "Strong Shopping titles include the product type, key attributes (brand, model, size, color), and language that matches how shoppers search. "
            "Avoid keyword stuffing and keep titles readable within Merchant field limits."
        ),
        who_for="Catalog managers improving click relevance in Google Shopping.",
        problems=["Generic titles", "Missing attributes", "Inconsistent patterns across categories"],
        how_helps=["Intent-aware title assembly from mapped feed data", "Batch review and export", "Quality scoring to prioritize weak titles"],
        example_before="title: Laptop",
        example_after="title: Acme Book 14\" Laptop 16GB RAM 512GB SSD — Silver",
        limitations=["No guaranteed CTR lift", "Category-specific conventions may vary"],
        guide_sections=[
            ("structure", "Recommended title structure", "<p>Brand + product type + key attributes + differentiator. Example: <em>Brand Model ProductType Size Color — Feature</em>.</p>"),
            ("examples", "Example table", "<table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'><tr><th>Weak</th><th>Stronger</th></tr><tr><td>Red dress</td><td>Brand A Women's Midi Dress Red Size M — Cotton</td></tr><tr><td>Phone case</td><td>Brand B iPhone 15 Pro Case Black — Shockproof</td></tr></table>"),
        ]
        + _guide_sections_checklist(),
        faq=[FaqItem("Should I put every keyword in the title?", "No. Prioritize clarity and accurate attributes over keyword lists.")],
        related_links=[("/use-cases/optimize-google-shopping-product-titles", "Title optimization use case")],
    ),
    "fix-missing-gtin-google-merchant-center": AnswerPageSpec(
        path="/guides/fix-missing-gtin-google-merchant-center",
        page_kind="guide",
        meta_title="Fix Missing GTIN in Google Merchant Center — Cartozo.ai",
        meta_description="How to find and fix missing or invalid GTIN values in Google Merchant Center product feeds, including identifier_exists and MPN fallbacks.",
        h1="Fix missing GTIN in Google Merchant Center",
        direct_answer=(
            "Missing GTIN errors usually mean a product requires a valid Global Trade Item Number but your feed row is empty or invalid. "
            "Fix by adding the correct GTIN, using identifier_exists=no with brand+MPN where eligible, or correcting product type classification."
        ),
        who_for="Feed managers resolving GTIN-related disapprovals in standard product catalogs.",
        problems=["Blank gtin column", "Invalid check digits", "Wrong product type for handmade/custom items"],
        how_helps=["Highlights rows with missing identifiers during mapping and review", "Supports batch export after fixes", "Pairs with title/description improvements in the same workflow"],
        example_before="id,title,gtin,brand\nA1,Widget,,Acme",
        example_after="id,title,gtin,brand\nA1,Widget,1234567890123,Acme",
        limitations=["Cartozo.ai cannot invent GTINs—you must source valid values from suppliers or barcodes", "identifier_exists rules depend on product type"],
        guide_sections=[
            ("why", "Why GTIN matters", "<p>Google uses GTINs to match products and reduce duplicates. Missing values often trigger disapprovals for standard catalog items.</p>"),
            ("fix", "How to fix", "<ol><li>Confirm whether the SKU truly has a GTIN</li><li>Add gtin column values from supplier data</li><li>For eligible custom products, use identifier_exists and brand+MPN per Google's rules</li><li>Re-export and validate before upload</li></ol>"),
        ],
        faq=[FaqItem("Does Cartozo.ai generate GTINs?", "No. You must provide valid GTINs from your product source data.")],
        related_links=[("/use-cases/fix-google-merchant-center-disapprovals", "Fix disapprovals"), ("/feed-structure", "Feed fields")],
    ),
    "product-feed-quality-audit": AnswerPageSpec(
        path="/guides/product-feed-quality-audit",
        page_kind="guide",
        meta_title="Product Feed Quality Audit Guide — Cartozo.ai",
        meta_description="Checklist and process for auditing ecommerce product feed quality before Google Merchant Center upload.",
        h1="Product feed quality audit",
        direct_answer=(
            "A feed quality audit reviews completeness, accuracy, and relevance of product data before it reaches Google Merchant Center. "
            "Focus on required fields, identifier coverage, title strength, image links, price/availability consistency, and category mapping."
        ),
        who_for="Teams running pre-launch or quarterly catalog reviews.",
        problems=["Unknown data gaps", "No scoring model", "Audit results without a fix workflow"],
        how_helps=["Upload and map feed for structured review", "Quality scoring on products", "Export improved CSV after review"],
        example_before="Audit spreadsheet with manual color-coding across 20 columns.",
        example_after="Scored export with prioritized weak rows and reviewed fixes ready for Merchant Center.",
        limitations=["Audits uploaded data only", "Does not replace live site QA"],
        guide_sections=_guide_sections_checklist()
        + [
            (
                "how-cartozo",
                "How Cartozo.ai helps",
                "<p>Upload your CSV, map fields, run batch optimization, review scored rows, and export a Merchant-ready file—turning the audit into an actionable workflow.</p>",
            ),
        ],
        faq=[FaqItem("How long does an audit take?", "Depends on catalog size; scoring helps you start with the weakest products first.")],
        related_links=[("/use-cases/product-feed-quality-audit", "Feed quality audit use case")],
    ),
    "product-feed-optimization-checklist": AnswerPageSpec(
        path="/guides/product-feed-optimization-checklist",
        page_kind="guide",
        meta_title="Product Feed Optimization Checklist — Cartozo.ai",
        meta_description="Downloadable-style checklist for optimizing Google Shopping product feeds: fields, titles, identifiers, images, and export steps.",
        h1="Product feed optimization checklist",
        direct_answer=(
            "Use this checklist before every Merchant Center upload: validate required fields, identifiers, titles, descriptions, images, pricing, availability, and category data—then review changes in a controlled export."
        ),
        who_for="Operators who want a repeatable pre-upload QA process.",
        problems=["Skipped validation steps", "Repeated upload failures", "No standard review process"],
        how_helps=["Combines checklist steps with upload → map → optimize → export in Cartozo.ai"],
        example_before="Team uploads raw supplier CSV directly to Merchant Center.",
        example_after="Checklist completed, scored export reviewed, batch uploaded with fewer errors.",
        limitations=["Checklist covers feed data, not ad account structure"],
        guide_sections=_guide_sections_checklist(),
        faq=[FaqItem("Can I use this for non-Google channels?", "The checklist focuses on Google Merchant-style fields; other channels may require extra attributes.")],
        related_links=[("/guides/google-merchant-center-feed-optimization", "Full optimization guide")],
    ),
    "product-feed-optimization-for-large-catalogs": AnswerPageSpec(
        path="/guides/product-feed-optimization-for-large-catalogs",
        page_kind="guide",
        meta_title="Product Feed Optimization for Large Catalogs — Cartozo.ai",
        meta_description="How to optimize large Google Shopping catalogs in batches: prioritization, scoring, review workflow, and Merchant-ready export.",
        h1="Product feed optimization for large catalogs",
        direct_answer=(
            "Large catalogs need prioritization: fix high-traffic and high-error SKUs first, standardize title patterns by category, and batch validation before export. "
            "Cartozo.ai supports bulk CSV processing with quality scoring and review workflows."
        ),
        who_for="Retailers and marketplaces with thousands+ SKUs.",
        problems=["Manual edits do not scale", "Hard to prioritize fixes", "Long QA cycles"],
        how_helps=["Batch processing within plan limits", "Quality scores to rank weak products", "Export after review"],
        example_before="50,000-row feed with inconsistent supplier data.",
        example_after="Scored batches by category, top 5,000 weak titles improved and exported for phased Merchant upload.",
        limitations=["Plan product limits apply", "May require supplier-side identifier cleanup"],
        guide_sections=[
            ("prioritize", "Prioritization framework", "<ol><li>Fix disapproved/active revenue SKUs first</li><li>Standardize title templates by category</li><li>Resolve identifier gaps in bulk</li><li>Roll out in phased exports</li></ol>"),
        ]
        + _guide_sections_checklist(),
        faq=[FaqItem("What catalog size can Cartozo.ai handle?", "See pricing plans for monthly product limits; large catalogs are typically processed in batches.")],
        related_links=[("/use-cases/large-catalog-feed-optimization", "Large catalog use case"), ("/pricing", "Pricing")],
    ),
}


def register_guide_routes(app) -> None:
    def _handler(spec: AnswerPageSpec) -> Callable:
        def view(request: Request):
            return HTMLResponse(content=build_answer_page_html(spec))

        return view

    for slug, spec in GUIDE_PAGES.items():
        app.get(spec.path, response_class=HTMLResponse, name=f"guide_{slug.replace('-', '_')}")(_handler(spec))

    @app.get("/guides", response_class=HTMLResponse, include_in_schema=False)
    def guides_index(request: Request):
        from .seo import site_base_url

        base = site_base_url().rstrip("/")
        links = "".join(
            f'<li><a href="{spec.path}">{spec.h1}</a><p>{spec.meta_description}</p></li>'
            for spec in GUIDE_PAGES.values()
        )
        html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/><title>Guides — Cartozo.ai</title>
<link rel="canonical" href="{base}/guides"/><meta name="description" content="Guides for Google Merchant Center feed optimization, titles, GTIN, and feed quality audits."/>
</head><body><main style="max-width:720px;margin:40px auto;padding:0 20px;font-family:Inter,sans-serif">
<h1>Guides</h1><ul>{links}</ul><p><a href="/">Home</a></p></main></body></html>"""
        return HTMLResponse(content=html)
