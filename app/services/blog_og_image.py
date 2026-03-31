"""Generate and persist Open Graph / hero PNGs for blog articles (HTML → Playwright → static file)."""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict

from ..blog_banner import render_banner_html
from ..blog_banner.screenshot import banner_dimensions, html_to_png_bytes
from ..db import get_db
from ..db_models import BlogArticle
from . import db_repository as repo

_log = logging.getLogger("uvicorn.error")

BLOG_OG_TEMPLATE_VERSION = "1"

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def blog_images_dir() -> str:
    d = os.path.join(_PROJECT_ROOT, "static", "blog-images")
    os.makedirs(d, exist_ok=True)
    return d


def public_image_path_for_slug(slug: str) -> str:
    safe = _safe_slug_segment(slug)
    return f"/static/blog-images/{safe}.png"


def fs_path_for_slug(slug: str) -> str:
    return os.path.join(blog_images_dir(), f"{_safe_slug_segment(slug)}.png")


def _safe_slug_segment(slug: str) -> str:
    raw = (slug or "article").strip().lower()
    out = []
    for ch in raw:
        if ch.isalnum() or ch in "-_":
            out.append(ch)
        elif ch in " /.":
            out.append("-")
    s = "".join(out).strip("-")
    while "--" in s:
        s = s.replace("--", "-")
    return (s[:180] or "article")


def blog_article_needs_og_banner(row: BlogArticle) -> bool:
    """Published article missing a successful on-disk OG/hero PNG — queue generation."""
    if (getattr(row, "status", None) or "") != "published":
        return False
    u = (getattr(row, "image_url", None) or "").strip()
    st = (getattr(row, "image_generation_status", None) or "").strip()
    slug = getattr(row, "slug", None) or ""
    if st == "success" and u:
        try:
            return not os.path.isfile(fs_path_for_slug(slug))
        except Exception:
            return True
    return (not u) or (st != "success")


def compute_image_hash(row: BlogArticle) -> str:
    payload = "|".join(
        [
            BLOG_OG_TEMPLATE_VERSION,
            (row.title or "")[:500],
            row.slug or "",
            (row.keywords or "")[:500],
            row.article_type or "",
            (row.meta_description or "")[:400],
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_blog_og_image_for_article_id(article_id: int, *, force: bool = False) -> Dict[str, Any]:
    """
    Load article, render banner HTML, screenshot PNG, update DB.
    Does not raise — returns dict with success / error for callers and background tasks.
    """
    if os.getenv("BLOG_OG_IMAGE_DISABLE", "").strip().lower() in ("1", "true", "yes"):
        return {"success": False, "error": "BLOG_OG_IMAGE_DISABLE is set", "article_id": article_id}

    w, h = banner_dimensions()
    try:
        with get_db() as db:
            row = repo.get_blog_article_by_id(db, article_id)
            if not row:
                return {"success": False, "error": "Article not found", "article_id": article_id}
            slug = row.slug or ""
            content_hash = compute_image_hash(row)
            rel = public_image_path_for_slug(slug)
            fs_path = fs_path_for_slug(slug)

            if not force and row.image_url and row.image_generation_status == "success":
                if (row.image_hash or "") == content_hash and os.path.isfile(fs_path):
                    return {
                        "success": True,
                        "skipped": True,
                        "image_url": row.image_url,
                        "width": w,
                        "height": h,
                        "article_id": article_id,
                    }

            repo.update_blog_article(
                db,
                row,
                image_generation_status="pending",
            )
            title = row.title or ""
            article_type = row.article_type or ""
            topic = row.topic or ""
            keywords = row.keywords or ""
            meta_description = row.meta_description or ""

        html = render_banner_html(
            title=title,
            slug=slug,
            article_type=article_type,
            topic=topic,
            keywords=keywords,
            meta_description=meta_description,
            category_label=(topic or "")[:80],
        )
        png = html_to_png_bytes(html, width=w, height=h)
        if not png:
            with get_db() as db:
                row2 = repo.get_blog_article_by_id(db, article_id)
                if row2:
                    repo.update_blog_article(
                        db,
                        row2,
                        image_url=rel if os.path.isfile(fs_path_for_slug(slug)) else None,
                        image_generation_status="failed",
                        image_template_version=BLOG_OG_TEMPLATE_VERSION,
                        image_hash=content_hash,
                    )
            return {
                "success": False,
                "error": "Screenshot failed — run on server: python -m playwright install chromium (and ensure playwright package is installed).",
                "article_id": article_id,
            }

        fs_path2 = fs_path_for_slug(slug)
        tmp_path = fs_path2 + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(png)
        os.replace(tmp_path, fs_path2)

        now = datetime.now(timezone.utc)
        with get_db() as db:
            row3 = repo.get_blog_article_by_id(db, article_id)
            if row3:
                repo.update_blog_article(
                    db,
                    row3,
                    image_url=rel,
                    image_generation_status="success",
                    image_template_version=BLOG_OG_TEMPLATE_VERSION,
                    image_generated_at=now,
                    image_hash=content_hash,
                )

        return {
            "success": True,
            "image_url": rel,
            "width": w,
            "height": h,
            "article_id": article_id,
        }
    except Exception as e:
        _log.exception("blog OG image generation article_id=%s", article_id)
        try:
            with get_db() as db:
                rowe = repo.get_blog_article_by_id(db, article_id)
                if rowe:
                    repo.update_blog_article(db, rowe, image_generation_status="failed")
        except Exception:
            _log.exception("blog OG image failed status update article_id=%s", article_id)
        return {"success": False, "error": str(e)[:500], "article_id": article_id}


def generate_missing_blog_og_images(*, limit: int = 200) -> Dict[str, Any]:
    with get_db() as db:
        rows = repo.list_blog_articles_needing_og_image(db, limit=limit)
        ids = [r.id for r in rows]
    results = []
    ok = 0
    failed = 0
    for aid in ids:
        out = generate_blog_og_image_for_article_id(aid, force=False)
        results.append(out)
        if out.get("success"):
            ok += 1
        else:
            failed += 1
    return {"processed": len(ids), "success": ok, "failed": failed, "results": results[:50]}
