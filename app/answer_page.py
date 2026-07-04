"""Reusable SSR builder for answer-ready marketing pages (use cases & guides)."""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .gtm import GTM_BODY, GTM_HEAD
from .air_design import site_page_shell_css
from .public_nav import HP_FOOTER_CSS, HP_NAV_CSS, public_site_footer_html, public_site_nav_html, public_site_theme_toggle_script
from .seo import (
    BRAND_NAME,
    SUPPORT_EMAIL,
    breadcrumb_json_ld,
    faq_page_json_ld,
    head_canonical_social,
    organization_json_ld_graph,
    rss_feed_link_tag,
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
{seo}{rss_feed_link_tag()}{json_ld}
<script src="/static/csrf.js"></script>
<script>try{{document.documentElement.setAttribute('data-theme',localStorage.getItem('hp-theme')||'dark')}}catch(e){{}}</script>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:var(--hp-font);background:var(--hp-bg,#100904);color:var(--hp-text,#ffedd7);line-height:1.5;-webkit-font-smoothing:antialiased}}
{site_page_shell_css()}
.ap-box h2,.ap-faq-item h3{{font-size:14px;font-weight:500;text-transform:uppercase;letter-spacing:.04em;margin-bottom:10px;color:var(--hp-text)}}
.ap-box ul,.ap-box p{{font-size:16px;font-weight:400;color:var(--hp-text)}}
.ap-example{{display:grid;gap:12px;margin:16px 0}}
@media(min-width:640px){{.ap-example{{grid-template-columns:1fr 1fr}}}}
.ap-ex-label{{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--hp-muted);margin-bottom:6px;font-weight:500}}
.ap-related a{{color:var(--hp-link);text-decoration:none;border-bottom:1px solid currentColor;font-size:12px;text-transform:uppercase;font-weight:500}}
{HP_NAV_CSS}
{HP_FOOTER_CSS}
</style>
</head>
<body>
{GTM_BODY}
{public_site_nav_html()}

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

{public_site_footer_html()}
<script>{public_site_theme_toggle_script().strip()}</script>
<script src="/static/page-transition.js"></script>
</body>
</html>"""
