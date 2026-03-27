"""Shared HTML shell for legal documents (Terms, Privacy, Cookies, etc.)."""
from __future__ import annotations

import html

from .public_nav import HP_FOOTER_CSS, HP_NAV_CSS, public_site_footer_html, public_site_nav_html, public_site_theme_toggle_script


def _legal_seo_extra(canonical_url: str, ot: str, od: str, og_image: str) -> str:
    cu = html.escape(canonical_url, quote=True)
    lines = [
        f'<link rel="canonical" href="{cu}"/>',
        f'<meta property="og:url" content="{cu}"/>',
        '<meta property="og:type" content="website"/>',
    ]
    if (og_image or "").strip():
        oi = html.escape(og_image.strip(), quote=True)
        lines.extend(
            [
                f'<meta property="og:image" content="{oi}"/>',
                f'<meta name="twitter:image" content="{oi}"/>',
            ]
        )
    lines.extend(
        [
            '<meta name="twitter:card" content="summary_large_image"/>',
            f'<meta name="twitter:title" content="{ot}"/>',
            f'<meta name="twitter:description" content="{od}"/>',
        ]
    )
    return "\n".join(lines)


def build_legal_document_html(
    *,
    article_html: str,
    meta_title: str,
    meta_description: str,
    og_title: str,
    og_description: str,
    canonical_url: str,
    og_image: str = "",
    extra_head: str = "",
    gtm_head: str,
    gtm_body: str,
) -> str:
    mt = html.escape(meta_title)
    md = html.escape(meta_description)
    ot = html.escape(og_title)
    od = html.escape(og_description)
    seo_extra = _legal_seo_extra(canonical_url, ot, od, og_image)
    xh = extra_head or ""

    return (
        f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
{gtm_head}
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{mt}</title>
<meta name="description" content="{md}"/>
<meta property="og:title" content="{ot}"/>
<meta property="og:description" content="{od}"/>
<meta name="robots" content="index,follow"/>
{seo_extra}{xh}
<script>try{{document.documentElement.setAttribute('data-theme',localStorage.getItem('hp-theme')||'dark')}}catch(e){{}}</script>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet"/>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{
  font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;
  background:#060711;color:#e5e7eb;line-height:1.6;
  -webkit-font-smoothing:antialiased;
}}
[data-theme=light] body{{background:#fafbfc;color:#0f172a}}
a{{color:#818cf8}}
[data-theme=light] a{{color:#4f46e5}}

.t-bg{{position:fixed;inset:0;z-index:0;pointer-events:none;
  background:radial-gradient(ellipse 70% 45% at 50% -15%,rgba(94,106,210,.14),transparent);
}}
.t-wrap{{position:relative;z-index:1;max-width:720px;margin:0 auto;padding:88px 24px 64px;box-sizing:border-box}}

@@HP_NAV_STYLES@@

.legal-doc h1{{font-size:clamp(1.65rem,3.5vw,2.1rem);font-weight:700;letter-spacing:-.03em;margin-bottom:8px}}
.legal-updated{{font-size:.88rem;color:rgba(229,231,235,.5);margin-bottom:22px}}
[data-theme=light] .legal-updated{{color:rgba(15,23,42,.5)}}
.legal-lead{{font-size:1.05rem;margin-bottom:28px;color:rgba(229,231,235,.85)}}
[data-theme=light] .legal-lead{{color:rgba(15,23,42,.85)}}
.legal-doc section{{margin-bottom:26px}}
.legal-doc h2{{font-size:1.05rem;font-weight:600;margin-bottom:10px;letter-spacing:-.02em}}
.legal-doc p{{margin-bottom:10px;font-size:.94rem;color:rgba(229,231,235,.82)}}
[data-theme=light] .legal-doc p{{color:rgba(15,23,42,.82)}}
.legal-doc ul{{margin:8px 0 12px 1.15rem;font-size:.94rem;color:rgba(229,231,235,.82)}}
[data-theme=light] .legal-doc ul{{color:rgba(15,23,42,.82)}}
.legal-doc li{{margin-bottom:6px}}

.t-foot-wrap{{margin-top:40px}}
</style>
</head>
<body>
{gtm_body}
<div class="t-bg" aria-hidden="true"></div>

@@PUBLIC_NAV@@

<div class="t-wrap">
{article_html}
  <div class="t-foot-wrap">@@PUBLIC_SITE_FOOTER@@</div>
</div>

__THEME_INLINE__
</body>
</html>
"""
    ).replace("@@HP_NAV_STYLES@@", HP_NAV_CSS + HP_FOOTER_CSS).replace(
        "@@PUBLIC_NAV@@", public_site_nav_html(feed_structure_href="/#feed-structure")
    ).replace("@@PUBLIC_SITE_FOOTER@@", public_site_footer_html(feed_structure_href="/#feed-structure")).replace(
        "__THEME_INLINE__",
        "<script>" + public_site_theme_toggle_script().strip() + "</script>",
    )
