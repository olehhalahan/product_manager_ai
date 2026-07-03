"""High-intent use-case landing pages for AI search visibility."""
from __future__ import annotations

from typing import Callable, Dict

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .answer_page import AnswerPageSpec, FaqItem, build_answer_page_html


def _common_faq() -> list[FaqItem]:
    return [
        FaqItem(
            "Does Cartozo.ai guarantee Google Merchant Center approval?",
            "No. Cartozo.ai is designed to help you find and fix common feed data issues and improve titles and descriptions, but Google makes the final approval decision.",
        ),
        FaqItem(
            "What file format do I upload?",
            "UTF-8 CSV. Cartozo maps your columns to Google Merchant fields and lets you review changes before export.",
        ),
    ]


USE_CASE_PAGES: Dict[str, AnswerPageSpec] = {
    "fix-google-merchant-center-disapprovals": AnswerPageSpec(
        path="/use-cases/fix-google-merchant-center-disapprovals",
        meta_title="Fix Google Merchant Center Disapprovals — Cartozo.ai",
        meta_description="Learn how to diagnose and fix common Google Merchant Center product disapprovals with feed validation, clearer titles, and Merchant-ready CSV export.",
        h1="Fix Google Merchant Center disapprovals",
        direct_answer=(
            "Google Merchant Center disapprovals often come from missing required attributes, weak titles, invalid GTINs, or policy mismatches in your product feed. "
            "Cartozo.ai helps you upload a CSV, detect likely issues, improve titles and descriptions around shopper search intent, score feed quality, and export a Merchant-ready file for review."
        ),
        who_for="E-commerce managers, performance marketers, and feed specialists who manage Google Shopping catalogs and need a structured way to reduce disapprovals.",
        problems=[
            "Products stuck in disapproved or limited status in Merchant Center",
            "Unclear error messages spread across many SKUs",
            "Manual spreadsheet fixes that do not scale",
            "Weak titles that fail relevance or attribute checks",
        ],
        how_helps=[
            "Upload your product CSV and map fields to Google Merchant attributes",
            "Run validation and quality scoring before you export",
            "Improve titles and descriptions with intent-aware assembly, not generic rewriting",
            "Review row-level changes and export a Merchant-ready CSV",
        ],
        example_before="title: Blue shoe\ngtin: (empty)\ndescription: Nice product",
        example_after="title: Men's Running Shoe Blue Size 42 — Breathable Mesh\ngtin: 1234567890123\ndescription: Lightweight men's running shoe with breathable mesh upper…",
        limitations=[
            "Cartozo.ai does not replace Merchant Center policy review or account-level suspensions",
            "Some disapprovals require website, landing page, or policy changes outside the feed",
            "Approval is decided by Google, not by Cartozo.ai",
        ],
        faq=_common_faq()
        + [
            FaqItem(
                "Can Cartozo.ai fix all disapproval reasons?",
                "It can help with many data-quality and attribute issues in the feed itself. Policy, landing page, or account issues may still need separate fixes in Merchant Center or on your store.",
            ),
        ],
        related_links=[
            ("/guides/fix-missing-gtin-google-merchant-center", "Fix missing GTIN guide"),
            ("/guides/product-feed-quality-audit", "Product feed quality audit"),
            ("/how-it-works", "How Cartozo.ai works"),
        ],
    ),
    "optimize-google-shopping-product-titles": AnswerPageSpec(
        path="/use-cases/optimize-google-shopping-product-titles",
        meta_title="Optimize Google Shopping Product Titles — Cartozo.ai",
        meta_description="Improve weak Google Shopping product titles with search-intent positioning, feed mapping, quality scoring, and Merchant-ready CSV export.",
        h1="Optimize Google Shopping product titles",
        direct_answer=(
            "Weak Shopping titles often miss key attributes, shopper intent, or Merchant field limits. "
            "Cartozo.ai analyzes your feed, infers likely search intents, scores options, and assembles clearer titles and aligned descriptions you can review before export."
        ),
        who_for="Brands and agencies that need stronger product titles across large Google Shopping feeds without manual copywriting per SKU.",
        problems=[
            "Generic titles like “Blue T-Shirt” with low relevance",
            "Missing brand, size, color, or model in the title",
            "Inconsistent title patterns across categories",
            "Manual title rewrites that do not scale",
        ],
        how_helps=[
            "Detects title gaps against common Merchant expectations",
            "Uses intent scoring to prioritize stronger phrasing",
            "Keeps titles grounded in your mapped product data",
            "Lets you review and export updated rows in bulk",
        ],
        example_before="title: Widget",
        example_after="title: Acme Pro Widget 500ml — Stainless Steel, Dishwasher Safe",
        limitations=[
            "Cartozo.ai does not guarantee higher CTR or ROAS",
            "Titles must still comply with Google Shopping policies",
            "Very custom naming rules may need manual review",
        ],
        faq=_common_faq(),
        related_links=[
            ("/guides/google-shopping-title-optimization", "Google Shopping title optimization guide"),
            ("/feed-structure", "Product feed structure"),
        ],
    ),
    "product-feed-optimization-for-agencies": AnswerPageSpec(
        path="/use-cases/product-feed-optimization-for-agencies",
        meta_title="Product Feed Optimization for Agencies — Cartozo.ai",
        meta_description="How marketing agencies can optimize client Google Shopping feeds in batches with review workflows, quality scoring, and Merchant-ready CSV export.",
        h1="Product feed optimization for agencies",
        direct_answer=(
            "Agencies managing multiple Google Shopping clients need repeatable feed cleanup without endless spreadsheet work. "
            "Cartozo.ai helps teams upload client CSVs, map fields, batch-optimize titles and descriptions, score quality, and export review-ready Merchant files."
        ),
        who_for="Performance marketing agencies, feed consultants, and e-commerce studios handling client Google Merchant Center catalogs.",
        problems=[
            "Repeating the same feed cleanup workflow for every client",
            "Hard-to-audit manual edits in shared spreadsheets",
            "Slow turnaround when a client sends a new export",
            "Inconsistent quality across account managers",
        ],
        how_helps=[
            "Standardizes upload → map → optimize → review → export for each client feed",
            "Supports bulk catalogs with batch processing",
            "Provides before/after quality signals for client reporting",
            "Exports Merchant-ready CSV for your existing workflow",
        ],
        example_before="Agency receives 12,000-row client export with inconsistent titles and missing GTINs.",
        example_after="Team maps fields once, runs batch optimization, reviews flagged rows, exports cleaned CSV with scored improvements.",
        limitations=[
            "Each client account still needs its own Merchant Center connection for publishing where applicable",
            "Cartozo.ai is not a full feed management platform or PIM",
            "Client-specific business rules may require manual review",
        ],
        faq=_common_faq()
        + [
            FaqItem(
                "Can agencies use Cartozo.ai for multiple clients?",
                "Yes. Teams can process separate client feeds in batches. Use your internal workflow to keep client data separated and review exports before delivery.",
            ),
        ],
        related_links=[
            ("/pricing", "Agency-friendly pricing"),
            ("/use-cases/large-catalog-feed-optimization", "Large catalog optimization"),
        ],
    ),
    "large-catalog-feed-optimization": AnswerPageSpec(
        path="/use-cases/large-catalog-feed-optimization",
        meta_title="Large Catalog Feed Optimization — Cartozo.ai",
        meta_description="Optimize large Google Shopping product catalogs in batches: map fields, improve titles and descriptions, score quality, and export Merchant-ready CSV.",
        h1="Large catalog feed optimization",
        direct_answer=(
            "Large SKU catalogs make manual feed cleanup slow and error-prone. "
            "Cartozo.ai is designed to process big CSV uploads in batches, apply intent-aware title and description improvements, score feed quality, and export a Merchant-ready file you can review at scale."
        ),
        who_for="Retailers and marketplaces with thousands of SKUs in Google Merchant Center or Google Shopping campaigns.",
        problems=[
            "Spreadsheet edits break down after a few thousand rows",
            "Hard to prioritize which products to fix first",
            "Inconsistent attributes across categories and suppliers",
            "Long turnaround before a clean export reaches Merchant Center",
        ],
        how_helps=[
            "Batch processing for large CSV uploads within plan limits",
            "Quality scoring to highlight weak products first",
            "Structured mapping from your columns to Merchant fields",
            "Export path designed for Merchant-ready CSV review",
        ],
        example_before="18,000 SKUs with mixed languages, missing GTINs, and short generic titles.",
        example_after="Prioritized batch run on top-impact rows, scored improvements, export of reviewed Merchant-ready CSV subset or full catalog per plan.",
        limitations=[
            "Plan limits apply to product volume processed per billing period",
            "Extremely wide or malformed CSVs may need preprocessing",
            "Cartozo.ai focuses on feed content quality, not warehouse or inventory systems",
        ],
        faq=_common_faq(),
        related_links=[
            ("/guides/product-feed-optimization-for-large-catalogs", "Large catalog optimization guide"),
            ("/pricing", "Plans and product limits"),
        ],
    ),
    "product-feed-quality-audit": AnswerPageSpec(
        path="/use-cases/product-feed-quality-audit",
        meta_title="Product Feed Quality Audit — Cartozo.ai",
        meta_description="Run a practical product feed quality audit: check required fields, title strength, attribute coverage, and export improvements for Google Merchant Center.",
        h1="Product feed quality audit",
        direct_answer=(
            "A product feed quality audit checks whether your catalog has the attributes, titles, and descriptions Google Shopping needs. "
            "Cartozo.ai helps you upload a CSV, map fields, surface likely gaps, score products, and export an improved Merchant-ready file after review."
        ),
        who_for="E-commerce teams preparing for Merchant Center uploads, campaign launches, or quarterly catalog cleanup.",
        problems=[
            "No clear view of feed completeness before launch",
            "Unknown share of rows missing GTIN, brand, or category data",
            "Titles and descriptions too weak to evaluate manually at scale",
            "Audit findings trapped in spreadsheets without a fix path",
        ],
        how_helps=[
            "Maps your CSV to Merchant-style fields for a structured review",
            "Scores products to show where quality is weakest",
            "Combines audit signals with optimization workflow in one tool",
            "Exports reviewed improvements instead of stopping at a checklist",
        ],
        example_before="Audit finds 34% of rows missing GTIN and 61% with titles under 40 characters.",
        example_after="Prioritized fixes applied to high-traffic SKUs, rescored export ready for Merchant Center upload.",
        limitations=[
            "Cartozo.ai audits feed content you upload; it does not crawl your live storefront by default",
            "Scores reflect feed data quality signals, not live ad performance",
            "Some issues require changes outside the CSV (site policy, landing pages)",
        ],
        faq=_common_faq(),
        related_links=[
            ("/guides/product-feed-quality-audit", "Feed quality audit guide"),
            ("/guides/product-feed-optimization-checklist", "Optimization checklist"),
        ],
    ),
}


def register_use_case_routes(app) -> None:
    def _handler(spec: AnswerPageSpec) -> Callable:
        def view(request: Request):
            return HTMLResponse(content=build_answer_page_html(spec))

        return view

    for slug, spec in USE_CASE_PAGES.items():
        app.get(spec.path, response_class=HTMLResponse, name=f"use_case_{slug.replace('-', '_')}")(_handler(spec))
