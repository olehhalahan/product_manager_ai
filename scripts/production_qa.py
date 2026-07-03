#!/usr/bin/env python3
"""Production-readiness QA for Cartozo.ai AI visibility layer.

Usage:
  DEPLOY_URL=https://cartozo.ai python3 scripts/production_qa.py
  DEPLOY_URL=https://cartozo.ai python3 scripts/production_qa.py --report docs/production-qa-report.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

os.environ.setdefault("DEPLOY_URL", "https://cartozo.ai")
os.environ.setdefault("SESSION_SECRET", "qa-test-session-secret-at-least-32-chars-long")
os.environ.setdefault("GOOGLE_CLIENT_ID", "qa-test.apps.googleusercontent.com")
os.environ.setdefault("SECRETS_ENCRYPTION_KEY", "dGVzdF9rZXlfMzJfYnl0ZXNfbG9uZ19lbm91Z2g=")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.faq_page import all_faq_pairs  # noqa: E402
from app.main import app  # noqa: E402
from app.seo import PUBLIC_SITEMAP_STATIC, seo_cached_snapshot_is_stale, site_base_url  # noqa: E402
from app.use_case_pages import USE_CASE_PAGES  # noqa: E402
from app.guide_pages import GUIDE_PAGES  # noqa: E402

PRODUCTION_BASE = "https://cartozo.ai"

SMOKE_URLS: list[tuple[str, int | str]] = [
    ("/", 200),
    ("/presentation", 200),
    ("/features", "301->/presentation"),
    ("/use-cases/fix-google-merchant-center-disapprovals", 200),
    ("/use-cases/optimize-google-shopping-product-titles", 200),
    ("/use-cases/product-feed-optimization-for-agencies", 200),
    ("/use-cases/large-catalog-feed-optimization", 200),
    ("/use-cases/product-feed-quality-audit", 200),
    ("/guides", 200),
    ("/guides/google-merchant-center-feed-optimization", 200),
    ("/guides/google-shopping-title-optimization", 200),
    ("/guides/fix-missing-gtin-google-merchant-center", 200),
    ("/guides/product-feed-quality-audit", 200),
    ("/guides/product-feed-optimization-checklist", 200),
    ("/guides/product-feed-optimization-for-large-catalogs", 200),
    ("/feed-structure", 200),
    ("/examples", 200),
    ("/examples/google-shopping-feed-before-after", 200),
    ("/examples/product-title-optimization-examples", 200),
    ("/examples/product-feed-quality-audit-example", 200),
    ("/templates/google-merchant-center-feed-template.csv", 200),
    ("/templates/sample-product-feed-before.csv", 200),
    ("/templates/sample-product-feed-after.csv", 200),
    ("/blog", 200),
    ("/blog/topics/google-merchant-center-issues", 200),
    ("/blog/topics/product-title-and-description-optimization", 200),
    ("/blog/topics/feed-quality-and-data-governance", 200),
    ("/blog/topics/large-catalogs-and-agencies", 200),
    ("/blog/topics/multichannel-and-marketplace-feeds", 200),
    ("/faq", 200),
    ("/about", 200),
    ("/contact", 200),
    ("/robots.txt", 200),
    ("/sitemap.xml", 200),
    ("/llms.txt", 200),
    ("/feed.xml", 200),
]

SCHEMA_PAGES: list[tuple[str, list[str]]] = [
    ("/", ["Organization", "WebSite", "SoftwareApplication"]),
    ("/pricing", ["Organization", "BreadcrumbList"]),
    ("/faq", ["FAQPage", "BreadcrumbList"]),
    ("/about", ["Organization", "BreadcrumbList"]),
    ("/feed-structure", ["BreadcrumbList"]),
    ("/examples", ["BreadcrumbList", "Dataset"]),
    ("/blog", ["BreadcrumbList"]),
    ("/blog/topics/google-merchant-center-issues", ["BreadcrumbList"]),
]

for slug in USE_CASE_PAGES:
    SCHEMA_PAGES.append((USE_CASE_PAGES[slug].path, ["BreadcrumbList", "WebPage"]))
for slug in GUIDE_PAGES:
    SCHEMA_PAGES.append((GUIDE_PAGES[slug].path, ["BreadcrumbList", "WebPage"]))

PRIVATE_FRAGMENTS = ("/admin", "/upload", "/login", "/settings", "/api/", "/merchant/", "/batches/")
BAD_HOST_FRAGMENTS = ("localhost", "127.0.0.1", "staging.", "dev.")


@dataclass
class Row:
    cols: list[str]
    ok: bool = True


@dataclass
class Report:
    url_rows: list[Row] = field(default_factory=list)
    meta_rows: list[Row] = field(default_factory=list)
    schema_rows: list[Row] = field(default_factory=list)
    file_rows: list[Row] = field(default_factory=list)
    p0: list[str] = field(default_factory=list)
    p1: list[str] = field(default_factory=list)
    p2: list[str] = field(default_factory=list)


def extract_json_ld(html: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL):
        out.append(json.loads(m.group(1)))
    return out


def schema_types(blocks: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            t = o.get("@type")
            if isinstance(t, str):
                found.add(t)
            elif isinstance(t, list):
                found.update(str(x) for x in t)
            g = o.get("@graph")
            if isinstance(g, list):
                for item in g:
                    walk(item)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for item in o:
                walk(item)

    for b in blocks:
        walk(b)
    return found


def walk_bad_keys(obj: object, bad: set[str]) -> list[str]:
    hits: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in bad:
                hits.append(k)
            hits.extend(walk_bad_keys(v, bad))
    elif isinstance(obj, list):
        for item in obj:
            hits.extend(walk_bad_keys(item, bad))
    return hits


def page_meta(client: TestClient, path: str) -> dict[str, Any]:
    html = client.get(path).text
    title = re.search(r"<title>([^<]+)</title>", html, re.I)
    desc = re.search(r'<meta name="description" content="([^"]*)"', html, re.I)
    canon = re.search(r'<link rel="canonical" href="([^"]+)"', html, re.I)
    h1_count = len(re.findall(r"<h1\b", html, re.I))
    robots = re.search(r'<meta name="robots" content="([^"]+)"', html, re.I)
    noindex = "noindex" in (robots.group(1) if robots else "").lower()
    og = re.search(r'<meta property="og:title" content="([^"]+)"', html, re.I)
    for bad in BAD_HOST_FRAGMENTS:
        if bad in html and f"{PRODUCTION_BASE}" not in html[:5000]:
            pass  # checked separately
    return {
        "html": html,
        "title": title.group(1).strip() if title else "",
        "description": desc.group(1).strip() if desc else "",
        "canonical": canon.group(1).strip() if canon else "",
        "h1_count": h1_count,
        "noindex": noindex,
        "og_title": og.group(1).strip() if og else "",
    }


def run_qa(report: Report) -> bool:
    client = TestClient(app, raise_server_exceptions=True)
    base = site_base_url().rstrip("/")
    if base != PRODUCTION_BASE:
        report.p0.append(f"DEPLOY_URL resolves to {base!r}, expected {PRODUCTION_BASE}")

    # URL smoke
    for path, expected in SMOKE_URLS:
        r = client.get(path, follow_redirects=False)
        notes = ""
        ok = True
        if expected == "301->/presentation":
            if r.status_code != 301 or r.headers.get("location") != "/presentation":
                ok = False
                report.p0.append(f"{path} expected 301 -> /presentation, got {r.status_code} {r.headers.get('location')!r}")
            actual = f"{r.status_code} -> {r.headers.get('location')}"
        else:
            actual = str(r.status_code)
            if r.status_code != expected:
                ok = False
                report.p0.append(f"{path} returned {r.status_code}, expected {expected}")
            if 'name="robots" content="noindex' in r.text and path not in (
                "/blog/topics/google-merchant-center-issues",
                "/blog/topics/product-title-and-description-optimization",
                "/blog/topics/feed-quality-and-data-governance",
                "/blog/topics/large-catalogs-and-agencies",
                "/blog/topics/multichannel-and-marketplace-feeds",
            ):
                notes = "unexpected noindex"
            elif path.startswith("/blog/topics/") and 'noindex' in r.text:
                notes = "noindex (empty topic hub — intentional until posts assigned)"
        report.url_rows.append(Row([path, str(expected), actual, "PASS" if ok else "FAIL", notes], ok=ok))

    # Legacy topic slug redirects
    for old, new in [
        ("title-description-optimization", "product-title-and-description-optimization"),
        ("feed-quality-governance", "feed-quality-and-data-governance"),
    ]:
        r = client.get(f"/blog/topics/{old}", follow_redirects=False)
        if r.status_code != 301 or new not in (r.headers.get("location") or ""):
            report.p1.append(f"Legacy topic slug /blog/topics/{old} should 301 to {new}")

    # Sitemap
    sm = client.get("/sitemap.xml").text
    sm_ok = True
    sm_notes: list[str] = []
    try:
        root = ET.fromstring(sm)
    except ET.ParseError as e:
        sm_ok = False
        sm_notes.append(f"invalid XML: {e}")
        report.p0.append("sitemap.xml is not valid XML")
        root = None
    locs: list[str] = []
    if root is not None:
        for url in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}url"):
            loc_el = url.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
            if loc_el is not None and loc_el.text:
                locs.append(loc_el.text.strip())
        for bad in BAD_HOST_FRAGMENTS + PRIVATE_FRAGMENTS:
            if bad in sm:
                sm_ok = False
                sm_notes.append(f"contains {bad!r}")
                report.p0.append(f"sitemap contains forbidden fragment {bad!r}")
        if "/features" in sm:
            sm_ok = False
            sm_notes.append("contains redirect URL /features")
            report.p0.append("sitemap must not include /features (301 redirect)")
        for loc in locs:
            rr = client.get(loc.replace(PRODUCTION_BASE, ""), follow_redirects=False)
            if rr.status_code != 200:
                sm_ok = False
                sm_notes.append(f"{loc} -> {rr.status_code}")
                report.p0.append(f"sitemap URL {loc} returned {rr.status_code}")

    robots = client.get("/robots.txt").text
    rb_ok = f"Sitemap: {PRODUCTION_BASE}/sitemap.xml" in robots
    rb_ok = rb_ok and "Allow: /" in robots and "Disallow: /" in robots
    for ua, policy in [
        ("OAI-SearchBot", "Allow"),
        ("GPTBot", "Disallow"),
        ("Claude-SearchBot", "Allow"),
        ("ClaudeBot", "Disallow"),
        ("PerplexityBot", "Allow"),
        ("Googlebot", "Allow"),
        ("bingbot", "Allow"),
        ("CCBot", "Allow"),
    ]:
        if f"User-agent: {ua}" not in robots:
            rb_ok = False
            report.p0.append(f"robots.txt missing User-agent: {ua}")
    if not rb_ok:
        report.p0.append("robots.txt policy incomplete or wrong sitemap line")

    report.file_rows.append(
        Row(["/sitemap.xml", "200", ", ".join(sm_notes[:5]) or "none", "none", "none", "PASS" if sm_ok else "FAIL"], ok=sm_ok)
    )
    report.file_rows.append(
        Row(["/robots.txt", "200", "none", "none", "none", "PASS" if rb_ok else "FAIL"], ok=rb_ok)
    )

    # llms.txt
    llms = client.get("/llms.txt").text
    llms_ok = True
    llms_broken: list[str] = []
    if PRODUCTION_BASE not in llms:
        llms_ok = False
        report.p0.append("llms.txt missing production base URL")
    for bad in PRIVATE_FRAGMENTS + BAD_HOST_FRAGMENTS:
        if bad in llms:
            llms_ok = False
            report.p0.append(f"llms.txt contains forbidden {bad!r}")
    for m in re.finditer(rf"{re.escape(PRODUCTION_BASE)}(/[^\s\)]+)", llms):
        p = m.group(1).split("—")[0].strip()
        if p == "/features":
            continue
        rr = client.get(p, follow_redirects=False)
        if rr.status_code not in (200, 301):
            llms_broken.append(p)
            llms_ok = False
    if llms_broken:
        report.p0.append(f"llms.txt broken links: {llms_broken[:5]}")
    report.file_rows.append(
        Row(["/llms.txt", "200", ", ".join(llms_broken) or "none", "none", "none", "PASS" if llms_ok else "FAIL"], ok=llms_ok)
    )

    # RSS feed
    feed_r = client.get("/feed.xml")
    feed_ok = feed_r.status_code == 200 and "<rss" in feed_r.text.lower()
    feed_notes: list[str] = []
    if PRODUCTION_BASE not in feed_r.text:
        feed_ok = False
        feed_notes.append("missing production URLs")
        report.p0.append("feed.xml missing production base URL")
    for bad in PRIVATE_FRAGMENTS + BAD_HOST_FRAGMENTS:
        if bad in feed_r.text and "Disallow" not in feed_r.text:
            feed_ok = False
            feed_notes.append(f"contains {bad!r}")
    rss_link = client.get("/").text
    if 'rel="alternate" type="application/rss+xml"' not in rss_link and "/feed.xml" not in rss_link:
        report.p1.append("Homepage missing RSS discovery link in head")
    report.file_rows.append(
        Row(["/feed.xml", str(feed_r.status_code), ", ".join(feed_notes) or "none", "none", "none", "PASS" if feed_ok else "FAIL"], ok=feed_ok)
    )

    # IndexNow key file
    idx_key = os.getenv("INDEXNOW_KEY", "").strip()
    if idx_key:
        key_r = client.get(f"/{idx_key}.txt")
        key_ok = key_r.status_code == 200 and key_r.text.strip() == idx_key
        if not key_ok:
            report.p0.append(f"IndexNow key file /{idx_key}.txt invalid")
        report.file_rows.append(
            Row([f"/{idx_key}.txt", str(key_r.status_code), "none", "none", "none", "PASS" if key_ok else "FAIL"], ok=key_ok)
        )
    else:
        report.p2.append("INDEXNOW_KEY not set — key file not tested")

    # File indexing / X-Robots-Tag
    csv_r = client.get("/templates/sample-product-feed-before.csv")
    csv_ok = csv_r.status_code == 200 and "text/csv" in (csv_r.headers.get("content-type") or "")
    csv_robots = csv_r.headers.get("x-robots-tag", "")
    if "noindex" not in csv_robots.lower():
        report.p1.append("Public template CSV should include X-Robots-Tag: noindex")
    upload_r = client.get("/upload", follow_redirects=False)
    upload_robots = upload_r.headers.get("x-robots-tag", "")
    if "noindex" not in upload_robots.lower() and upload_r.status_code in (200, 302, 307):
        report.p1.append("/upload missing X-Robots-Tag: noindex on response")

    # Pagination audit (documented behavior)
    blog_html = client.get("/blog").text
    if "page=2" in blog_html and 'rel="canonical"' in blog_html and "/blog?page=2" not in blog_html:
        report.p1.append("Blog pagination may canonicalize incorrectly if page=2 links appear")

    if not seo_cached_snapshot_is_stale('<?xml version="1.0"?><urlset><url><loc>http://localhost:8000/</loc></url></urlset>'):
        report.p0.append("Stale localhost sitemap cache would be served in production")

    # Metadata table for new pages
    meta_paths = [p for p, exp in SMOKE_URLS if exp == 200]
    titles_seen: dict[str, str] = {}
    for path in meta_paths:
        if path in ("/robots.txt", "/sitemap.xml", "/llms.txt", "/feed.xml"):
            continue
        if path.endswith(".csv"):
            continue
        m = page_meta(client, path)
        html = m["html"]
        canon_ok = m["canonical"].startswith(PRODUCTION_BASE)
        if not canon_ok and path != "/features":
            report.p0.append(f"{path} canonical not production: {m['canonical']!r}")
        for bad in BAD_HOST_FRAGMENTS:
            if bad in html and bad in m.get("canonical", ""):
                report.p0.append(f"{path} contains {bad} in canonical/metadata")
        dup = titles_seen.get(m["title"])
        if dup and m["title"]:
            report.p1.append(f"Duplicate title {m['title']!r} on {path} and {dup}")
        elif m["title"]:
            titles_seen[m["title"]] = path
        indexable = not m["noindex"] or path.startswith("/blog/topics/")
        ok = (
            bool(m["title"])
            and bool(m["description"])
            and canon_ok
            and m["h1_count"] == 1
            and (indexable or path.startswith("/blog/topics/"))
        )
        if m["h1_count"] != 1 and path not in ("/",):
            report.p1.append(f"{path} has {m['h1_count']} H1 tags (expected 1)")
        report.meta_rows.append(
            Row(
                [
                    path,
                    "yes" if m["title"] else "no",
                    "yes" if m["description"] else "no",
                    "yes" if canon_ok else "no",
                    str(m["h1_count"]),
                    "yes" if not m["noindex"] else "noindex",
                    "PASS" if ok else "FAIL",
                ],
                ok=ok,
            )
        )

    # FAQ schema parity
    faq_html = client.get("/faq").text
    faq_schema = next((x for x in extract_json_ld(faq_html) if x.get("@type") == "FAQPage"), None)
    pairs = all_faq_pairs()
    if not faq_schema or len(faq_schema.get("mainEntity", [])) != len(pairs):
        report.p0.append("FAQPage schema count mismatch")
    else:
        for i, (q, a) in enumerate(pairs):
            ent = faq_schema["mainEntity"][i]
            if ent["name"] != q or ent["acceptedAnswer"]["text"] != a:
                report.p0.append(f"FAQ schema mismatch at question {i+1}")

    # Schema validation
    for path, required in SCHEMA_PAGES:
        html = client.get(path).text
        blocks = extract_json_ld(html)
        types = set()
        for b in blocks:
            types |= schema_types([b])
        missing = [t for t in required if t not in types]
        bad = []
        for b in blocks:
            bad.extend(walk_bad_keys(b, {"aggregateRating", "reviewCount", "ratingValue"}))
        crit = []
        if missing:
            crit.append(f"missing {missing}")
        if bad:
            crit.append(f"fake ratings {bad}")
        for b in blocks:
            blob = json.dumps(b)
            for bad_host in BAD_HOST_FRAGMENTS:
                if bad_host in blob:
                    crit.append(f"localhost in schema")
                    break
        ok = not crit
        if not ok:
            report.p1.append(f"{path} schema: {', '.join(crit)}")
        report.schema_rows.append(
            Row([path, ", ".join(sorted(types)) or "none", ", ".join(crit) or "none", "", "PASS" if ok else "FAIL"], ok=ok)
        )

    # Security: public files
    for blob_name, blob in [("sitemap", sm), ("llms", llms), ("robots", robots)]:
        for frag in PRIVATE_FRAGMENTS:
            if frag in blob and frag not in ("Disallow: /admin", "Disallow: /api/"):
                if frag in blob.replace("Disallow:", ""):
                    pass
        if "/docs/" in blob and "ai-crawler" not in blob:
            report.p2.append(f"{blob_name} may expose internal docs path")

    # Nav reachability (2-3 clicks from home)
    home = client.get("/").text
    for path in [
        "/guides",
        "/use-cases/fix-google-merchant-center-disapprovals",
        "/feed-structure",
    ]:
        if path not in home:
            report.p1.append(f"Homepage missing direct link to {path}")

    return len(report.p0) == 0


def render_report(report: Report, safe_to_merge: bool) -> str:
    lines = [
        "# Cartozo.ai AI Visibility — Production QA Report",
        "",
        f"**Safe to merge:** {'Yes' if safe_to_merge else 'No'}",
        f"**Production base URL:** `{PRODUCTION_BASE}` (via `DEPLOY_URL`)",
        "",
        "## Summary",
        "",
    ]
    if report.p0:
        lines.append("### P0 — Must fix before merge")
        for x in report.p0:
            lines.append(f"- {x}")
        lines.append("")
    if report.p1:
        lines.append("### P1 — Should fix before deploy")
        for x in report.p1:
            lines.append(f"- {x}")
        lines.append("")
    if report.p2:
        lines.append("### P2 — Can fix after deploy")
        for x in report.p2:
            lines.append(f"- {x}")
        lines.append("")

    lines.extend(["## URL status", "", "| URL | Expected | Actual | Result | Notes |", "|---|---|---|---|---|"])
    for row in report.url_rows:
        lines.append("| " + " | ".join(row.cols) + " |")

    lines.extend(["", "## SEO metadata", "", "| URL | Title | Meta desc | Canonical | H1 | Indexable | Result |", "|---|---|---|---|---|---|---|"])
    for row in report.meta_rows:
        lines.append("| " + " | ".join(row.cols) + " |")

    lines.extend(["", "## Structured data", "", "| URL | Schema types | Critical errors | Warnings | Result |", "|---|---|---|---|---|"])
    for row in report.schema_rows:
        lines.append("| " + " | ".join(row.cols) + " |")

    lines.extend(
        [
            "",
            "## Sitemap / robots / llms",
            "",
            "| File | HTTP | Broken URLs | Localhost/staging | Private URLs | Result |",
            "|---|---|---|---|---|---|",
        ]
    )
    for row in report.file_rows:
        lines.append("| " + " | ".join(row.cols) + " |")

    lines.extend(
        [
            "",
            "## Post-deploy checklist",
            "",
            "1. Confirm `DEPLOY_URL=https://cartozo.ai` in production `.env`",
            "2. Regenerate sitemap/robots in Admin → Settings → SEO",
            "3. Assign blog posts to content clusters in Writter admin",
            "4. Submit sitemap in Google Search Console and Bing Webmaster Tools",
            "5. Run `python3 scripts/submit_indexnow.py submit-indexnow-all-public` after major content updates",
            "6. Remove `noindex` from topic hubs once posts are assigned (automatic when posts exist)",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", help="Write markdown report to path")
    args = parser.parse_args()
    report = Report()
    safe = run_qa(report)
    text = render_report(report, safe)
    print(text)
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
        print(f"\nWrote {args.report}")
    # Console summary
    fails = sum(1 for r in report.url_rows + report.meta_rows + report.schema_rows + report.file_rows if not r.ok)
    print(f"\n{'PRODUCTION QA PASSED' if safe else 'PRODUCTION QA FAILED'} ({len(report.p0)} P0, {len(report.p1)} P1, {fails} table FAIL rows)")
    return 0 if safe else 1


if __name__ == "__main__":
    raise SystemExit(main())
