"""Reusable SSR builder for answer-ready marketing pages (use cases & guides)."""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .gtm import GTM_BODY, GTM_HEAD
from .public_nav import HP_FOOTER_CSS, HP_NAV_CSS, public_site_footer_html, public_site_nav_html, public_site_theme_toggle_script
from .seo import (
    BRAND_NAME,
    SUPPORT_EMAIL,
    breadcrumb_json_ld,
    faq_page_json_ld,
    head_canonical_social,
    organization_json_ld_graph,
    site_base_url,
    web_page_json_ld,
)


@dataclass
class FaqItem:
    question: str
    answer: str


@dataclass
class AnswerPageSpec:
    path: str
    meta_title: str
    meta_description: str
    h1: str
    direct_answer: str
    who_for: str
    problems: List[str]
    how_helps: List[str]
    example_before: str
    example_after: str
    limitations: List[str]
    faq: List[FaqItem] = field(default_factory=list)
    related_links: List[Tuple[str, str]] = field(default_factory=list)
    guide_sections: List[Tuple[str, str, str]] = field(default_factory=list)  # id, title, html
    page_kind: str = "use-case"  # use-case | guide
    date_published: str = "2026-07-03"
    date_modified: str = "2026-07-03"


def _esc(s: str) -> str:
    return html.escape(s or "", quote=False)


def _esc_attr(s: str) -> str:
    return html.escape(s or "", quote=True)


def _list_html(items: List[str]) -> str:
    if not items:
        return ""
    return "<ul>" + "".join(f"<li>{_esc(x)}</li>" for x in items) + "</ul>"


def _faq_html(faq: List[FaqItem]) -> str:
    if not faq:
        return ""
    parts = ['<section class="ap-faq" aria-labelledby="ap-faq-h"><h2 id="ap-faq-h">FAQ</h2>']
    for i, item in enumerate(faq):
        parts.append(f'<div class="ap-faq-item"><h3 id="ap-fq{i}">{_esc(item.question)}</h3><p>{_esc(item.answer)}</p></div>')
    parts.append("</section>")
    return "\n".join(parts)


def build_answer_page_html(spec: AnswerPageSpec, *, og_image: str = "") -> str:
    base = site_base_url().rstrip("/")
    canonical = f"{base}{spec.path}"
    crumbs = [("Home", f"{base}/"), (spec.h1, canonical)]
    if spec.page_kind == "guide":
        crumbs.insert(1, ("Guides", f"{base}/guides"))

    breadcrumb_ld = breadcrumb_json_ld(items=crumbs)
    org_ld = organization_json_ld_graph()
    page_ld = web_page_json_ld(
        url=canonical,
        name=spec.meta_title,
        description=spec.meta_description,
        date_published=spec.date_published,
        date_modified=spec.date_modified,
    )
    faq_ld = faq_page_json_ld(questions=[(f.question, f.answer) for f in spec.faq]) if spec.faq else ""
    json_ld = org_ld + breadcrumb_ld + page_ld + faq_ld

    seo = head_canonical_social(
        canonical_url=canonical,
        og_title=spec.meta_title,
        og_description=spec.meta_description,
        og_image=og_image,
        og_site_name=BRAND_NAME,
        og_type="website",
    )

    toc = ""
    guide_body = ""
    if spec.guide_sections:
        toc_items = "".join(f'<li><a href="#{_esc_attr(sid)}">{_esc(title)}</a></li>' for sid, title, _ in spec.guide_sections)
        toc = f'<nav class="ap-toc" aria-label="Table of contents"><h2>Contents</h2><ol>{toc_items}</ol></nav>'
        for sid, title, body_html in spec.guide_sections:
            guide_body += f'<section id="{_esc_attr(sid)}" class="ap-section"><h2>{_esc(title)}</h2>{body_html}</section>'

    related = ""
    if spec.related_links:
        links = "".join(f'<li><a href="{_esc_attr(href)}">{_esc(label)}</a></li>' for href, label in spec.related_links)
        related = f'<section class="ap-related"><h2>Related pages</h2><ul>{links}</ul></section>'

    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
{GTM_HEAD}
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{_esc(spec.meta_title)}</title>
<meta name="description" content="{_esc(spec.meta_description)}"/>
<meta name="robots" content="index,follow"/>
{seo}{json_ld}
<script src="/static/csrf.js"></script>
<script>try{{document.documentElement.setAttribute('data-theme',localStorage.getItem('hp-theme')||'dark')}}catch(e){{}}</script>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet"/>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Inter',system-ui,sans-serif;background:#060711;color:#e5e7eb;line-height:1.65;-webkit-font-smoothing:antialiased}}
[data-theme=light] body{{background:#fafbfc;color:#0f172a}}
a{{color:#818cf8}}
[data-theme=light] a{{color:#4f46e5}}
.ap-wrap{{max-width:760px;margin:0 auto;padding:96px 24px 64px}}
.ap-bc{{font-size:.85rem;color:rgba(229,231,235,.55);margin-bottom:20px}}
[data-theme=light] .ap-bc{{color:rgba(15,23,42,.55)}}
.ap-bc a{{color:inherit;text-decoration:none}}
.ap-bc a:hover{{text-decoration:underline}}
.ap-lead{{font-size:1.05rem;margin:16px 0 28px;color:rgba(229,231,235,.9)}}
[data-theme=light] .ap-lead{{color:rgba(15,23,42,.88)}}
.ap-box{{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08);border-radius:12px;padding:20px 22px;margin:20px 0}}
[data-theme=light] .ap-box{{background:#fff;border-color:rgba(15,23,42,.1)}}
.ap-box h2{{font-size:1rem;margin-bottom:10px}}
.ap-box ul{{margin:8px 0 0 1.1rem;font-size:.94rem}}
.ap-box li{{margin-bottom:6px}}
.ap-example{{display:grid;gap:12px;margin:16px 0}}
@media(min-width:640px){{.ap-example{{grid-template-columns:1fr 1fr}}}}
.ap-ex-label{{font-size:.75rem;text-transform:uppercase;letter-spacing:.08em;color:rgba(229,231,235,.5);margin-bottom:4px}}
.ap-ex pre{{background:#111827;border-radius:8px;padding:12px;font-size:.78rem;overflow:auto;white-space:pre-wrap;word-break:break-word}}
[data-theme=light] .ap-ex pre{{background:#f1f5f9;color:#0f172a}}
.ap-section{{margin:32px 0}}
.ap-section h2{{font-size:1.15rem;margin-bottom:12px}}
.ap-section p,.ap-section li{{font-size:.94rem;color:rgba(229,231,235,.85)}}
[data-theme=light] .ap-section p,[data-theme=light] .ap-section li{{color:rgba(15,23,42,.82)}}
.ap-toc{{margin:24px 0;padding:16px 20px;border-radius:10px;background:rgba(79,70,229,.08);border:1px solid rgba(129,140,248,.2)}}
.ap-toc ol{{margin:8px 0 0 1.2rem;font-size:.9rem}}
.ap-toc li{{margin-bottom:4px}}
.ap-faq{{margin-top:36px}}
.ap-faq h2{{font-size:1.2rem;margin-bottom:16px}}
.ap-faq-item{{margin-bottom:18px}}
.ap-faq-item h3{{font-size:.98rem;margin-bottom:6px}}
.ap-cta{{margin:36px 0;padding:24px;border-radius:12px;background:linear-gradient(135deg,rgba(79,70,229,.15),rgba(34,211,238,.08));border:1px solid rgba(129,140,248,.25);text-align:center}}
.ap-cta a{{display:inline-block;margin:8px 6px 0;padding:12px 22px;border-radius:8px;font-weight:600;text-decoration:none;background:#4f46e5;color:#fff}}
.ap-cta a.secondary{{background:transparent;border:1px solid rgba(255,255,255,.2);color:inherit}}
.ap-related{{margin-top:28px;font-size:.92rem}}
.ap-related ul{{margin:8px 0 0 1.1rem}}
.ap-h1{{font-size:clamp(1.6rem,3.5vw,2.1rem);font-weight:700;letter-spacing:-.03em;line-height:1.15}}
{HP_NAV_CSS}
{HP_FOOTER_CSS}
</style>
</head>
<body>
{GTM_BODY}
{public_site_nav_html(feed_structure_href="/feed-structure")}

<main class="ap-wrap">
  <nav class="ap-bc" aria-label="Breadcrumb">
    <a href="/">Home</a>
    {' · <a href="/guides">Guides</a>' if spec.page_kind == 'guide' else ''}
    · {_esc(spec.h1)}
  </nav>
  <h1 class="ap-h1">{_esc(spec.h1)}</h1>
  <p class="ap-lead">{_esc(spec.direct_answer)}</p>

  {toc}
  {guide_body}

  <div class="ap-box"><h2>Who this is for</h2><p>{_esc(spec.who_for)}</p></div>
  <div class="ap-box"><h2>Problems it solves</h2>{_list_html(spec.problems)}</div>
  <div class="ap-box"><h2>How Cartozo.ai helps</h2>{_list_html(spec.how_helps)}</div>

  <div class="ap-example">
    <div class="ap-ex"><div class="ap-ex-label">Before</div><pre>{_esc(spec.example_before)}</pre></div>
    <div class="ap-ex"><div class="ap-ex-label">After (example)</div><pre>{_esc(spec.example_after)}</pre></div>
  </div>

  <div class="ap-box"><h2>Limitations</h2>{_list_html(spec.limitations)}</div>

  {_faq_html(spec.faq)}
  {related}

  <div class="ap-cta">
    <p>Ready to improve your Google Shopping feed?</p>
    <a href="/login">Upload your feed</a>
    <a href="/pricing" class="secondary">View pricing</a>
    <a href="/contact" class="secondary">Contact support</a>
  </div>
</main>

<div style="max-width:760px;margin:0 auto;padding:0 24px 48px">
  {public_site_footer_html(feed_structure_href="/feed-structure")}
</div>
<script>{public_site_theme_toggle_script().strip()}</script>
<script src="/static/page-transition.js"></script>
</body>
</html>"""
