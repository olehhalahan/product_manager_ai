"""Shared HTML shell for legal documents (Terms, Privacy, Cookies, etc.)."""
from __future__ import annotations

import html

from .public_nav import public_site_footer_html, public_site_nav_html, public_site_styles_block, public_site_theme_toggle_script
from .seo import rss_feed_link_tag


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
{rss_feed_link_tag()}
<script>try{{document.documentElement.setAttribute('data-theme',localStorage.getItem('hp-theme')||'dark')}}catch(e){{}}</script>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{
  font-family:var(--hp-font);
  background:var(--hp-bg,#100904);color:var(--hp-text,#ffedd7);line-height:1.5;
  font-weight:500;font-size:16px;
  -webkit-font-smoothing:antialiased;
}}
a{{color:var(--hp-link,#dc5000);text-decoration:none;border-bottom:1px solid currentColor}}
a:hover{{opacity:.85}}

.t-bg{{position:fixed;inset:0;z-index:0;pointer-events:none;background:var(--hp-bg,#100904)}}
.t-wrap{{position:relative;z-index:1;max-width:720px;margin:0 auto;padding:96px 24px 48px;box-sizing:border-box}}

{{PUBLIC_STYLES}}

.legal-doc h1{{font-size:clamp(1.5rem,3vw,41px);font-weight:500;letter-spacing:-.01em;margin-bottom:12px;text-transform:uppercase;line-height:.9;color:var(--hp-text)}}
.legal-updated{{font-size:11px;color:var(--hp-muted);margin-bottom:22px;text-transform:uppercase;font-family:Arial,sans-serif}}
.legal-lead{{font-size:18px;margin-bottom:28px;color:var(--hp-text);font-weight:400;line-height:1.33}}
.legal-doc section{{margin-bottom:26px;padding-top:24px;border-top:1px dashed var(--hp-border)}}
.legal-doc h2{{font-size:14px;font-weight:500;margin-bottom:10px;letter-spacing:.04em;text-transform:uppercase;color:var(--hp-text)}}
.legal-doc p{{margin-bottom:10px;font-size:16px;color:var(--hp-text);font-weight:400;line-height:1.5}}
.legal-doc ul{{margin:8px 0 12px 1.15rem;font-size:16px;color:var(--hp-text)}}
.legal-doc li{{margin-bottom:6px}}
</style>
</head>
<body>
{gtm_body}
<div class="t-bg" aria-hidden="true"></div>

{{PUBLIC_NAV}}

<div class="t-wrap">
{article_html}
</div>

{{PUBLIC_FOOTER}}

{{PUBLIC_THEME_SCRIPT}}
</body>
</html>
"""
    ).replace("{PUBLIC_STYLES}", public_site_styles_block()).replace(
        "{PUBLIC_NAV}", public_site_nav_html()
    ).replace("{PUBLIC_FOOTER}", public_site_footer_html()).replace(
        "{PUBLIC_THEME_SCRIPT}",
        "<script>" + public_site_theme_toggle_script().strip() + "</script>\n<script src=\"/static/page-transition.js\"></script>",
    )
