"""Jinja2 HTML banner for Playwright screenshot (1200×630)."""

from __future__ import annotations

import html
import os
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .themes import THEME_LABELS, layout_variant_for_slug, resolve_theme_key, theme_style

_pkg_dir = os.path.dirname(os.path.abspath(__file__))
_env = Environment(
    loader=FileSystemLoader(os.path.join(_pkg_dir, "templates")),
    autoescape=select_autoescape(["html", "xml"]),
)


def _safe_title(t: str) -> str:
    t = (t or "").strip()
    if len(t) > 180:
        t = t[:177] + "…"
    return t


def render_banner_html(
    *,
    title: str,
    slug: str,
    article_type: str,
    topic: str,
    keywords: str,
    meta_description: str,
    category_label: str = "",
    layout_override: str | None = None,
) -> str:
    theme_key = resolve_theme_key(title, topic, keywords, article_type)
    layout = (layout_override or "").strip().lower()
    if layout not in ("a", "b", "c"):
        layout = layout_variant_for_slug(slug)
    sty = theme_style(theme_key)
    kw = (keywords or "").split(",")[0].strip()[:80] if keywords else ""
    hook = (meta_description or "").strip()
    if len(hook) > 140:
        hook = hook[:137] + "…"
    cat = (category_label or "").strip() or THEME_LABELS.get(theme_key, "")
    tpl = _env.get_template("banner.html")
    return tpl.render(
        title_html=html.escape(_safe_title(title)),
        layout=layout,
        theme_class=f"theme-{theme_key}",
        article_type_html=html.escape((article_type or "").strip()[:64]),
        category_html=html.escape(cat[:64]),
        primary_kw_html=html.escape(kw),
        hook_html=html.escape(hook) if hook else "",
        accent=sty["accent"],
        grad0=sty["g0"],
        grad1=sty["g1"],
    )
