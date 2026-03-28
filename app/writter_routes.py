"""
Writter admin UI + public blog + APIs. Admin-only for management routes.
"""
from __future__ import annotations

import html as html_module
import json
import logging
import math
import os
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .auth import get_current_user, is_admin, require_admin_http, require_admin_redirect
from .db import get_db
from .services import db_repository as repo
from .services.db_repository import get_settings
from .admin_nav import ADMIN_MERCHANT_SCRIPT, ADMIN_THEME_SCRIPT, admin_top_nav_html
from .public_nav import public_site_nav_html
from .seo import (
    blog_posting_json_ld,
    canonical_url_blog_article,
    canonical_url_for_request,
    head_canonical_social,
)
from .writter_new_article_page import render_writter_new_article_html

_log = logging.getLogger("uvicorn.error")
from .services.writter_service import (
    ARTICLE_TYPE_LABELS,
    MIN_QUALITY_AUTO_PUBLISH,
    PRIMARY_GOAL_LABELS,
    VALID_ARTICLE_TYPES,
    VALID_PRIMARY_GOALS,
    build_article_plan,
    build_outline_headings,
    build_visual_options,
    conversion_blocks_html,
    ensure_unique_slug,
    estimate_article_quality,
    extended_creation_blocked_message,
    generate_admin_blog_insights,
    generate_article_with_ai,
    generate_ctr_variants,
    get_writter_type_prompt,
    gsc_feedback_suggestions,
    inject_internal_links,
    publish_blocked_by_quality,
    refresh_article_partial,
    route_cheap_visual,
    RULE_PRESET_MESSAGES,
    run_seo_quality_audit,
    score_article_opportunity,
    suggest_auto_article_brief,
    suggest_future_topics_keywords_only,
    suggest_internal_link_placements,
    slugify,
)

router = APIRouter(tags=["writter"])

# Auto article: number of draft variants saved; user picks one to publish via /auto-article/finalize.
_AUTO_ARTICLE_VARIANTS = 5

_WRITTER_SCREENSHOT_DIR = Path(__file__).resolve().parent.parent / "static" / "uploads" / "writter"
_WRITTER_SCREENSHOT_MAX_BYTES = 5 * 1024 * 1024
_WRITTER_SCREENSHOT_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _blog_article_end_cta_html() -> str:
    """Default CTA block at the end of every public article (links to upload)."""
    return """<section class="blog-article-end-cta writter-cta" aria-labelledby="blog-end-cta-title">
  <h2 id="blog-end-cta-title" class="blog-article-end-cta-title">Ready to optimize your feed?</h2>
  <p class="blog-article-end-cta-sub">Upload your product catalog and improve titles, descriptions, and visibility with AI.</p>
  <a href="/upload" class="blog-article-end-cta-btn">Get Started Now</a>
</section>"""


def _blog_public_subtitle_html(meta_plain: str, title_plain: str) -> str:
    """Secondary line under H1 from meta description (premium blog layout)."""
    m = (meta_plain or "").strip()
    t = (title_plain or "").strip()
    if not m or m.lower() == t.lower():
        return ""
    if len(m) > 200:
        m = m[:197] + "…"
    return f'<p class="blog-article-subtitle">{html_module.escape(m)}</p>'


def _strip_trailing_writter_cta_block(html: str) -> str:
    """Drop trailing writter-cta block so the page template end CTA is not duplicated."""
    if not html:
        return ""
    s = html.rstrip()
    pat = re.compile(
        r"(?is)(?:"
        r"<section\b[^>]*\bwritter-cta\b[^>]*>.*?</section>"
        r"|<div\b[^>]*\bwritter-cta\b[^>]*>.*?</div>"
        r"|<p\b[^>]*\bwritter-cta\b[^>]*>.*?</p>"
        r")\s*$"
    )
    return pat.sub("", s).rstrip()


def _admin_ai_insights_valid(ins: Any) -> bool:
    if not isinstance(ins, dict):
        return False
    try:
        qs = int(ins.get("quality_score", -1))
    except (TypeError, ValueError):
        return False
    return 0 <= qs <= 100


def _merge_metrics_with_admin_ai_insights(
    metrics: Dict[str, Any],
    *,
    api_key: Optional[str],
    title: str,
    meta_description: str,
    topic: str,
    keywords: str,
    article_type: str,
    content_html: str,
    views: int,
    sessions: int,
    avg_time_s: float,
    avg_scroll: float,
    cta_clicks: int,
    internal_links_n: int,
) -> Dict[str, Any]:
    """Persist OpenAI admin sidebar narrative; call only after full article generation/regeneration."""
    m = dict(metrics) if isinstance(metrics, dict) else {}
    if not api_key:
        return m
    ins = generate_admin_blog_insights(
        api_key,
        title=title,
        meta_description=meta_description,
        topic=topic,
        keywords=keywords,
        article_type=article_type,
        content_html=content_html,
        metrics_json=m,
        views=views,
        sessions=sessions,
        avg_time_s=avg_time_s,
        avg_scroll=avg_scroll,
        cta_clicks=cta_clicks,
        internal_links_n=internal_links_n,
    )
    if ins:
        m["admin_ai_insights"] = ins
    return m


def _only_dict(v: Any) -> dict:
    """JSON columns may deserialize to list/str; review UI must not crash on .get()."""
    return v if isinstance(v, dict) else {}


def _sanitize_for_json(obj: Any) -> Any:
    """Replace nan/inf and walk nested structures so json.dumps never raises."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return str(obj)
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    return obj


def _fmt_table_date(val: Any) -> str:
    """Short YYYY-MM-DD for list cells (avoids wrapped ISO timestamps)."""
    s = str(val) if val is not None else "—"
    if s == "—":
        return s
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return s[:19].replace("T", " ")


def _json_snippet_for_pre(obj: Any, limit: int) -> str:
    try:
        clean = _sanitize_for_json(obj)
        s = json.dumps(clean, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError, OverflowError):
        s = repr(obj)
    return html_module.escape(s[:limit])


def _json_literal_for_script(value: Any) -> str:
    """
    Serialize as JSON for embedding inside <script>. Escapes '<' so '</script>' in strings
    cannot close the script tag and break the page.
    """
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")


def _merge_refresh_html(action: str, html: str, patches: Dict[str, str]) -> str:
    if action == "intro" and patches.get("content_html_prefix"):
        stripped = re.sub(r"^\s*<section\b[^>]*>[\s\S]*?</section>", "", html or "", count=1, flags=re.I)
        return patches["content_html_prefix"] + stripped
    if action == "clarity" and patches.get("content_html"):
        return patches["content_html"]
    if action == "cta" and patches.get("cta_html"):
        return (html or "") + "\n" + patches["cta_html"]
    if action == "faq" and patches.get("faq_html"):
        return (html or "") + "\n" + patches["faq_html"]
    if action == "evidence" and patches.get("evidence_html"):
        return (html or "") + "\n" + patches["evidence_html"]
    return html or ""


def _settings_openai_key() -> str:
    with get_db() as db:
        s = get_settings(db)
    return (s.get("openai_api_key") or "").strip()


def _admin_shell_nav(active: str) -> str:
    return f"""<nav class="wt-admin-nav">
  <a href="/admin/onboarding-analytics" class="{'active' if active == 'dash' else ''}">Dashboard</a>
  <a href="/admin/writter" class="{'active' if active == 'writter' else ''}">Writter</a>
  <a href="/admin/writter/clusters" class="{'active' if active == 'clusters' else ''}">Clusters</a>
  <a href="/admin/contact-results">Contact results</a>
  <a href="/settings">Settings</a>
</nav>"""


def _writter_article_missing_html(article_id: int) -> HTMLResponse:
    """Browser-friendly 404 when blog_articles row does not exist (avoids raw JSON error page)."""
    aid = int(article_id)
    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Article not found — Writter</title>
  <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
  <link rel="stylesheet" href="/static/styles.css" />
  <style>
  body {{ margin:0; font-family:Inter,system-ui,sans-serif; background:#0B0F19; color:#E5E7EB; min-height:100vh; }}
  .wt-box {{ max-width:560px; margin:48px auto; padding:0 24px 80px; }}
  </style>
</head>
<body>
  {admin_top_nav_html("writter")}
  <div class="wt-box">
    <h1 style="font-size:1.25rem;margin:0 0 12px;">Article not found</h1>
    <p style="color:#94a3b8;line-height:1.5;">No row with id <strong>{aid}</strong> in this database (wrong URL or different environment).</p>
    <p style="color:#94a3b8;line-height:1.5;">Use <strong>Writter →</strong> the article title links to Review for each id.</p>
    <p style="margin-top:20px;"><a href="/admin/writter" style="color:#818cf8;font-weight:600;">← All articles</a></p>
  </div>
  {ADMIN_THEME_SCRIPT.strip()}
</body>
</html>"""
    return HTMLResponse(content=html, status_code=404)


def _writter_review_show_exception_ui(request: Request) -> bool:
    """Show exception text on the error page (localhost or WRITTER_REVIEW_DEBUG_UI=1)."""
    if os.getenv("WRITTER_REVIEW_DEBUG_UI", "").lower() in ("1", "true", "yes"):
        return True
    host = (request.url.hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1")


def _writter_review_error_html(
    request: Request, article_id: int, exc: Exception, request_id: str
) -> HTMLResponse:
    """500 page with correlation id; optional traceback on localhost / WRITTER_REVIEW_DEBUG_UI."""
    detail = ""
    if _writter_review_show_exception_ui(request):
        tb = traceback.format_exc()
        msg = f"{type(exc).__name__}: {exc}"
        safe_msg = html_module.escape(msg[:4000])
        safe_tb = html_module.escape(tb[-12000:])
        detail = f"""
    <p style="color:#fca5a5;font-family:ui-monospace,monospace;font-size:.82rem;word-break:break-word;">{safe_msg}</p>
    <details style="margin-top:12px;"><summary style="cursor:pointer;color:#94a3b8;">Traceback</summary>
    <pre style="font-size:.72rem;overflow:auto;max-height:360px;background:#111827;padding:12px;border-radius:8px;color:#cbd5e1;">{safe_tb}</pre>
    </details>"""
    aid = int(article_id)
    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Review error — Writter</title>
  <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
  <link rel="stylesheet" href="/static/styles.css" />
  <style>
  body {{ margin:0; font-family:Inter,system-ui,sans-serif; background:#0B0F19; color:#E5E7EB; min-height:100vh; }}
  .wt-box {{ max-width:640px; margin:48px auto; padding:0 24px 80px; }}
  .wt-rid {{ font-family:ui-monospace,monospace; font-size:.85rem; color:#94a3b8; }}
  </style>
</head>
<body>
  {admin_top_nav_html("writter")}
  <div class="wt-box">
    <h1 style="font-size:1.25rem;margin:0 0 12px;">Review page failed to render</h1>
    <p class="wt-rid">Request id: <strong style="color:#e5e7eb;">{html_module.escape(request_id)}</strong> · article id: <strong>{aid}</strong></p>
    <p style="color:#94a3b8;line-height:1.5;">Search server logs for this request id (uvicorn / <code>writter review FAILED</code>).</p>
    {detail}
    <p style="margin-top:20px;"><a href="/admin/writter" style="color:#818cf8;font-weight:600;">← All articles</a></p>
  </div>
  {ADMIN_THEME_SCRIPT.strip()}
</body>
</html>"""
    return HTMLResponse(content=html, status_code=500)


@router.get("/admin/writter", response_class=HTMLResponse)
async def writter_list_page(request: Request):
    redir = require_admin_redirect(request, "/admin/writter")
    if redir:
        return redir
    with get_db() as db:
        rows = repo.list_blog_articles_admin(db)
        future_rows = repo.list_writter_future_articles(db)
    tr = ""
    for r in rows:
        title_esc = html_module.escape(r.get("title") or "")
        slug_esc = html_module.escape(r.get("slug") or "")
        aid = int(r.get("id") or 0)
        st = (r.get("status") or "").strip()
        kw = html_module.escape(r.get("keywords") or "")
        pub = r.get("published_at") or r.get("created_at") or "—"
        views = r.get("views") or 0
        if aid:
            title_cell = f'<a href="/admin/writter/article/{aid}/review">{title_esc}</a>'
            if st == "draft":
                title_cell += ' <span style="color:#64748b;font-size:.75rem;">(draft)</span>'
            else:
                title_cell += (
                    f' <a href="/blog/{slug_esc}" target="_blank" rel="noopener" '
                    'style="color:#94a3b8;font-size:.82rem;margin-left:6px;">View live</a>'
                )
        else:
            title_cell = title_esc
        action_opts = '<option value="" selected disabled>Actions…</option>'
        if st != "published":
            action_opts += '<option value="publish">Publish</option>'
        if st == "published":
            action_opts += '<option value="unpublish">Unpublish</option>'
        action_opts += '<option value="delete">Delete…</option>'
        st_esc = html_module.escape(st or "")
        pill_mod = "wt-pill-published" if st == "published" else "wt-pill-draft"
        atype = html_module.escape((r.get("article_type") or "")[:32])
        m = r.get("metrics_json") or {}
        seo = m.get("seo_qa") if isinstance(m, dict) else {}
        scores = (seo.get("scores") or {}) if isinstance(seo, dict) else {}
        ov = scores.get("overall")
        qcell = html_module.escape(str(ov)) if isinstance(ov, int) else "—"
        lu = r.get("updated_at") or r.get("created_at") or "—"
        lu_disp = _fmt_table_date(lu)
        pub_disp = _fmt_table_date(pub)
        cid = r.get("cluster_id")
        cstr = html_module.escape(str(cid)) if cid else "—"
        rf = html_module.escape((r.get("writter_refresh_status") or "")[:28] or "—")
        tr += f"""<tr data-article-id="{aid}">
  <td class="wt-col-title">{title_cell}</td>
  <td class="wt-col-dt">{html_module.escape(pub_disp)}</td>
  <td class="wt-col-keywords" title="{kw}">{kw}</td>
  <td class="wt-col-type">{atype}</td>
  <td class="wt-col-q">{qcell}</td>
  <td class="wt-col-cluster">{cstr}</td>
  <td class="wt-col-refresh" title="{rf}">{rf}</td>
  <td class="wt-col-views">{views}</td>
  <td class="wt-col-dt wt-muted">{html_module.escape(lu_disp)}</td>
  <td class="wt-status-cell"><span class="wt-pill {pill_mod}">{st_esc}</span></td>
  <td class="wt-actions-cell">
    <select class="wt-dd" data-id="{aid}" aria-label="Article actions">{action_opts}</select>
  </td>
</tr>"""
    if not tr:
        tr = '<tr><td colspan="11" class="wt-empty">No articles yet. Create one.</td></tr>'

    tr_f = ""
    for fr in future_rows:
        fid = int(fr.get("id") or 0)
        topic_esc = html_module.escape((fr.get("topic") or "")[:200])
        kw_esc = html_module.escape((fr.get("keywords") or "")[:160])
        at_esc = html_module.escape((fr.get("article_type") or "")[:32])
        st = (fr.get("status") or "").strip()
        st_esc = html_module.escape(st)
        gen_id = fr.get("generated_article_id")
        gen_cell = (
            f'<a href="/admin/writter/article/{int(gen_id)}/review">#{int(gen_id)}</a>'
            if gen_id
            else "—"
        )
        rationale = ""
        bj = fr.get("briefing_json") if isinstance(fr.get("briefing_json"), dict) else {}
        if isinstance(bj, dict) and bj.get("rationale"):
            rationale = html_module.escape(str(bj.get("rationale"))[:200])
        pill = "wt-pill-draft"
        if st == "approved":
            pill = "wt-pill-published"
        elif st == "done":
            pill = "wt-pill-published"
        elif st == "rejected":
            pill = "wt-pill-draft"
        disabled = "disabled" if st == "done" else ""
        gen_disabled = "disabled" if st == "done" or st != "approved" else ""
        gen_title = (
            ""
            if st == "approved"
            else (' title="Approve this row first"' if st != "done" else "")
        )
        tr_f += f"""<tr data-future-id="{fid}">
  <td class="wt-col-title">{topic_esc}</td>
  <td class="wt-col-keywords" title="{kw_esc}">{kw_esc}</td>
  <td class="wt-col-type">{at_esc}</td>
  <td class="wt-status-cell"><span class="wt-pill {pill}">{st_esc}</span></td>
  <td class="wt-col-dt">{gen_cell}</td>
  <td class="wt-fut-rationale" style="font-size:.82rem;color:#94a3b8;max-width:14rem;">{rationale or "—"}</td>
  <td class="wt-actions-cell wt-fut-actions-cell">
    <div class="wt-fut-act-stack" role="group" aria-label="Queue row actions">
      <div class="wt-fut-act-row">
        <span class="wt-fut-act-h">Review</span>
        <div class="wt-fut-act-pair">
          <button type="button" class="wt-btn wt-btn-sm wt-btn-fut" data-fut="approve" data-id="{fid}" {disabled}>Approve</button>
          <button type="button" class="wt-btn wt-btn-sm wt-btn-secondary wt-btn-fut" data-fut="reject" data-id="{fid}" {disabled}>Reject</button>
        </div>
      </div>
      <div class="wt-fut-act-row">
        <span class="wt-fut-act-h">AI</span>
        <div class="wt-fut-act-pair">
          <button type="button" class="wt-btn wt-btn-sm wt-btn-secondary wt-btn-fut" data-fut="regen" data-id="{fid}" {disabled}>Regenerate</button>
          <button type="button" class="wt-btn wt-btn-sm wt-btn-gen wt-btn-fut" data-fut="gen" data-id="{fid}" {gen_disabled}{gen_title}>Generate</button>
        </div>
      </div>
    </div>
  </td>
</tr>"""
    if not tr_f:
        tr_f = '<tr><td colspan="7" class="wt-empty">No queued ideas yet. Click <strong>Refresh queue</strong> to generate suggestions.</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Writter — Cartozo.ai</title>
  <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
  <link rel="stylesheet" href="/static/styles.css" />
  <style>
  body {{ margin:0; font-family:Inter,system-ui,sans-serif; background:#0B0F19; color:#E5E7EB; min-height:100vh; display:flex; flex-direction:column; }}
  [data-theme="light"] body {{ background:#f8fafc; color:#0f172a; }}
  .wt-layout {{ flex:1; display:flex; min-height:0; }}
  .wt-side {{ width:240px; background:#0a0e18; border-right:1px solid rgba(255,255,255,.08); padding:24px 16px; }}
  [data-theme="light"] .wt-side {{ background:#fff; border-color:rgba(15,23,42,.1); }}
  .wt-admin-nav a {{ display:block; padding:10px 14px; border-radius:8px; color:#9ca3af; text-decoration:none; font-size:.9rem; }}
  .wt-admin-nav a:hover {{ background:rgba(255,255,255,.05); color:#fff; }}
  .wt-admin-nav a.active {{ background:rgba(79,70,229,.15); color:#818cf8; font-weight:600; }}
  [data-theme="light"] .wt-admin-nav a {{ color:#64748b; }}
  [data-theme="light"] .wt-admin-nav a.active {{ color:#4F46E5; }}
  .wt-main {{ flex:1; min-width:0; padding:32px clamp(16px,3vw,40px); }}
  .wt-h1 {{ font-size:1.6rem; font-weight:700; margin:0 0 8px; }}
  .wt-toolbar {{ margin:24px 0; display:flex; gap:12px; align-items:center; }}
  .wt-btn {{ display:inline-flex; align-items:center; gap:8px; padding:10px 18px; border-radius:8px; background:#4F46E5; color:#fff; font-weight:600; text-decoration:none; border:none; cursor:pointer; font-size:.9rem; }}
  .wt-btn:hover {{ filter:brightness(1.05); }}
  .wt-table-wrap {{ width:100%; overflow-x:auto; -webkit-overflow-scrolling:touch; padding-inline-end:20px; box-sizing:border-box; }}
  table.wt-table {{ width:100%; min-width:1120px; border-collapse:collapse; font-size:.9rem; table-layout:fixed; }}
  .wt-table th {{ text-align:left; padding:12px 10px; color:#9ca3af; font-size:.72rem; text-transform:uppercase; letter-spacing:.05em; border-bottom:1px solid rgba(255,255,255,.1); vertical-align:bottom; }}
  .wt-table td {{ padding:12px 10px; border-bottom:1px solid rgba(255,255,255,.06); vertical-align:top; }}
  .wt-table a {{ color:#22D3EE; }}
  .wt-col-title {{ width:34%; min-width:260px; line-height:1.45; word-wrap:break-word; overflow-wrap:anywhere; }}
  .wt-col-dt {{ width:7.5rem; white-space:nowrap; font-size:.82rem; font-variant-numeric:tabular-nums; color:#cbd5e1; }}
  .wt-col-keywords {{ width:14%; max-width:14rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#9ca3af; }}
  .wt-col-type {{ width:8rem; }}
  .wt-col-q {{ width:4.5rem; text-align:center; }}
  .wt-col-cluster {{ width:5rem; }}
  .wt-col-refresh {{ width:6.5rem; max-width:6.5rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#9ca3af; font-size:.85rem; }}
  .wt-col-views {{ width:3.5rem; text-align:right; font-variant-numeric:tabular-nums; }}
  .wt-muted {{ color:#9ca3af; }}
  .wt-pill {{ font-size:.75rem; padding:4px 10px; border-radius:99px; background:rgba(148,163,184,.15); }}
  .wt-pill-published {{ background:rgba(74,222,128,.12); color:#4ade80; }}
  .wt-pill-draft {{ background:rgba(251,191,36,.12); color:#fbbf24; }}
  .wt-status-cell {{ vertical-align:top; white-space:nowrap; width:6.5rem; }}
  .wt-actions-cell {{ vertical-align:top; width:12rem; min-width:12rem; text-align:right; padding-inline-end:4px !important; }}
  .wt-fut-actions-cell {{ width:15.5rem; min-width:15.5rem; text-align:left; padding-inline-start:10px !important; padding-inline-end:10px !important; }}
  .wt-fut-act-stack {{ display:flex; flex-direction:column; gap:10px; align-items:stretch; }}
  .wt-fut-act-row {{ display:flex; flex-direction:column; gap:5px; }}
  .wt-fut-act-h {{ font-size:.62rem; font-weight:700; letter-spacing:.07em; text-transform:uppercase; color:#64748b; }}
  [data-theme="light"] .wt-fut-act-h {{ color:#94a3b8; }}
  .wt-fut-act-pair {{ display:grid; grid-template-columns:1fr 1fr; gap:6px; }}
  .wt-fut-act-pair .wt-btn-sm {{ margin:0; width:100%; box-sizing:border-box; justify-content:center; }}
  .wt-btn-gen {{ background:linear-gradient(180deg, #0ea5e9 0%, #0284c7 100%) !important; color:#fff !important; box-shadow:0 1px 0 rgba(255,255,255,.12) inset; }}
  .wt-btn-gen:hover:not(:disabled) {{ filter:brightness(1.06); }}
  .wt-btn-gen:disabled {{ opacity:.45; cursor:not-allowed; filter:none; }}
  [data-theme="light"] .wt-btn-gen {{ background:linear-gradient(180deg, #38bdf8 0%, #0ea5e9 100%) !important; color:#0f172a !important; box-shadow:none; }}
  [data-theme="light"] .wt-btn-gen:disabled {{ opacity:.4; }}
  .wt-th-actions {{ text-align:right; }}
  .wt-th-fut-actions {{ text-align:left; vertical-align:bottom; }}
  .wt-dd {{
    width:100%;
    max-width:100%;
    min-width:0;
    box-sizing:border-box;
    padding:9px 32px 9px 12px;
    border-radius:10px;
    border:1px solid rgba(255,255,255,.12);
    background-color:#111827;
    background-image:
      linear-gradient(180deg, rgba(255,255,255,.06) 0%, rgba(255,255,255,.02) 100%),
      url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12' fill='none'%3E%3Cpath d='M3 4.5L6 7.5L9 4.5' stroke='%2394a3b8' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
    background-repeat:no-repeat, no-repeat;
    background-position:0 0, right 10px center;
    background-size:auto, 12px 12px;
    color:#e5e7eb; font-size:.8rem; font-weight:500;
    cursor:pointer;
    appearance:none;
    box-shadow:0 1px 0 rgba(255,255,255,.04) inset;
    transition:border-color .15s, box-shadow .15s;
  }}
  .wt-dd:hover {{ border-color:rgba(129,140,248,.35); box-shadow:0 0 0 1px rgba(129,140,248,.12); }}
  .wt-dd:focus {{ outline:none; border-color:rgba(129,140,248,.55); box-shadow:0 0 0 3px rgba(79,70,229,.2); }}
  [data-theme="light"] .wt-dd {{
    background-color:#f8fafc;
    background-image:
      linear-gradient(180deg, #fff 0%, #f1f5f9 100%),
      url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12' fill='none'%3E%3Cpath d='M3 4.5L6 7.5L9 4.5' stroke='%2364748b' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
    background-repeat:no-repeat, no-repeat;
    background-position:0 0, right 10px center;
    background-size:auto, 12px 12px;
    border-color:rgba(15,23,42,.12);
    color:#0f172a;
    box-shadow:0 1px 2px rgba(15,23,42,.06);
  }}
  [data-theme="light"] .wt-dd:hover {{ border-color:rgba(79,70,229,.35); }}
  .wt-empty {{ text-align:center; color:#6b7280; padding:40px; }}
  .wt-loading {{ position:fixed; inset:0; z-index:9999; background:rgba(11,15,25,.72); display:none; align-items:center; justify-content:center; backdrop-filter:blur(4px); }}
  .wt-loading.wt-loading--on {{ display:flex; }}
  .wt-loading-box {{ background:#111827; border:1px solid rgba(255,255,255,.1); border-radius:16px; padding:32px 40px; text-align:center; max-width:360px; box-shadow:0 24px 48px rgba(0,0,0,.4); }}
  [data-theme="light"] .wt-loading-box {{ background:#fff; border-color:rgba(15,23,42,.12); }}
  .wt-spinner {{ width:44px; height:44px; border:3px solid rgba(129,140,248,.25); border-top-color:#818cf8; border-radius:50%; margin:0 auto 16px; animation:wtspin .85s linear infinite; }}
  @keyframes wtspin {{ to {{ transform: rotate(360deg); }} }}
  .wt-loading-box p {{ margin:0; color:#e5e7eb; font-weight:600; }}
  [data-theme="light"] .wt-loading-box p {{ color:#0f172a; }}
  .wt-loading-sub {{ font-size:.85rem !important; font-weight:400 !important; color:#94a3b8 !important; margin-top:8px !important; }}
  .wt-tabs {{ display:flex; gap:8px; margin:20px 0 12px; flex-wrap:wrap; align-items:center; }}
  .wt-tab {{ padding:8px 18px; border-radius:8px; border:1px solid rgba(255,255,255,.12); background:transparent; color:#94a3b8; cursor:pointer; font-weight:600; font-size:.9rem; }}
  .wt-tab:hover {{ color:#e5e7eb; border-color:rgba(129,140,248,.35); }}
  .wt-tab.wt-tab--on {{ background:rgba(79,70,229,.22); color:#c7d2fe; border-color:rgba(129,140,248,.45); }}
  [data-theme="light"] .wt-tab {{ border-color:rgba(15,23,42,.15); color:#64748b; }}
  [data-theme="light"] .wt-tab.wt-tab--on {{ color:#4F46E5; background:rgba(79,70,229,.1); }}
  .wt-tab-panel {{ display:none; }}
  .wt-tab-panel.wt-on {{ display:block; }}
  table.wt-future-table {{ min-width:900px; }}
  .wt-btn-sm {{ padding:6px 10px; font-size:.75rem; margin:2px; }}
  .wt-btn-secondary {{ background:#334155 !important; }}
  [data-theme="light"] .wt-btn-secondary {{ background:#e2e8f0 !important; color:#0f172a !important; }}
  </style>
</head>
<body>
  {admin_top_nav_html("writter")}
  <div id="wtLoading" class="wt-loading" role="dialog" aria-modal="true" aria-labelledby="wtLoadTitle" aria-hidden="true">
    <div class="wt-loading-box">
      <div class="wt-spinner" aria-hidden="true"></div>
      <p id="wtLoadTitle">Please wait…</p>
      <p id="wtLoadSub" class="wt-loading-sub">Working…</p>
    </div>
  </div>
  <div class="wt-layout">
    <aside class="wt-side">
      <div style="margin-bottom:20px;"><a href="/"><img src="/assets/logo-light.png" alt="Cartozo" style="height:26px;" class="logo-light"/><img src="/assets/logo-dark.png" alt="Cartozo" style="height:26px;display:none" class="logo-dark"/></a></div>
      <span style="font-size:.65rem;font-weight:700;letter-spacing:.08em;color:#64748b;display:block;margin-bottom:12px;">ADMIN</span>
      {_admin_shell_nav("writter")}
    </aside>
    <main class="wt-main">
      <h1 class="wt-h1">Writter</h1>
      <p style="color:#9ca3af;margin:0 0 8px;">SEO articles — list and analytics</p>
      <div class="wt-toolbar" style="flex-wrap:wrap;">
        <a class="wt-btn" href="/admin/writter/new">+ Create New Article</a>
        <button type="button" class="wt-btn wt-btn-secondary" id="wtBtnRefreshQueue">Refresh queue</button>
        <button type="button" class="wt-btn wt-btn-secondary" id="wtBtnAddFiveTopics" title="Adds 5 rows: AI suggests only topic + keywords (no article bodies)">+ 5 topics</button>
      </div>
      <div class="wt-tabs" role="tablist">
        <button type="button" class="wt-tab wt-tab--on" id="wtTabArticles" role="tab" aria-selected="true">Articles</button>
        <button type="button" class="wt-tab" id="wtTabFuture" role="tab" aria-selected="false">Future articles</button>
      </div>
      <p id="wtFutureHint" style="display:none;color:#94a3b8;font-size:.88rem;margin:0 0 12px;max-width:52rem;">
        <strong>Refresh queue</strong> and <strong>+ 5 topics</strong> only add a short topic line and keywords (ideas for the queue), not article bodies. Approve rows you want, then click <strong>Generate</strong> to draft and publish when SEO overall score is at least {MIN_QUALITY_AUTO_PUBLISH}. <strong>Regenerate</strong> replaces one row with a new full AI brief.
      </p>
      <div id="panelArticles" class="wt-tab-panel wt-on" role="tabpanel">
      <div class="wt-table-wrap">
      <table class="wt-table">
        <thead><tr>
          <th class="wt-col-title">Title</th>
          <th class="wt-col-dt">Published</th>
          <th class="wt-col-keywords">Keywords</th>
          <th class="wt-col-type">Type</th>
          <th class="wt-col-q">Quality</th>
          <th class="wt-col-cluster">Cluster</th>
          <th class="wt-col-refresh">Refresh</th>
          <th class="wt-col-views">Views</th>
          <th class="wt-col-dt">Updated</th>
          <th class="wt-status-cell">Status</th>
          <th class="wt-th-actions wt-actions-cell">Actions</th>
        </tr></thead>
        <tbody>{tr}</tbody>
      </table>
      </div>
      </div>
      <div id="panelFuture" class="wt-tab-panel" role="tabpanel">
      <div class="wt-table-wrap">
      <table class="wt-table wt-future-table">
        <thead><tr>
          <th class="wt-col-title">Topic</th>
          <th class="wt-col-keywords">Keywords</th>
          <th class="wt-col-type">Type</th>
          <th class="wt-status-cell">Status</th>
          <th class="wt-col-dt">Article</th>
          <th>Notes</th>
          <th class="wt-th-fut-actions wt-fut-actions-cell">Actions</th>
        </tr></thead>
        <tbody id="wtFutureTbody">{tr_f}</tbody>
      </table>
      </div>
      </div>
    </main>
  </div>
  <script>
  {ADMIN_THEME_SCRIPT.strip()}
  {ADMIN_MERCHANT_SCRIPT.strip()}
  (function() {{
    var tabA = document.getElementById('wtTabArticles');
    var tabF = document.getElementById('wtTabFuture');
    var pA = document.getElementById('panelArticles');
    var pF = document.getElementById('panelFuture');
    var hint = document.getElementById('wtFutureHint');
    function showArticles() {{
      if (tabA) {{ tabA.classList.add('wt-tab--on'); tabA.setAttribute('aria-selected', 'true'); }}
      if (tabF) {{ tabF.classList.remove('wt-tab--on'); tabF.setAttribute('aria-selected', 'false'); }}
      if (pA) {{ pA.classList.add('wt-on'); }}
      if (pF) {{ pF.classList.remove('wt-on'); }}
      if (hint) hint.style.display = 'none';
    }}
    function showFuture() {{
      if (tabF) {{ tabF.classList.add('wt-tab--on'); tabF.setAttribute('aria-selected', 'true'); }}
      if (tabA) {{ tabA.classList.remove('wt-tab--on'); tabA.setAttribute('aria-selected', 'false'); }}
      if (pF) {{ pF.classList.add('wt-on'); }}
      if (pA) {{ pA.classList.remove('wt-on'); }}
      if (hint) hint.style.display = 'block';
    }}
    if (tabA) tabA.addEventListener('click', showArticles);
    if (tabF) tabF.addEventListener('click', showFuture);
    var load = document.getElementById('wtLoading');
    var loadTitle = document.getElementById('wtLoadTitle');
    var loadSub = document.getElementById('wtLoadSub');
    function setLoad(on, mode) {{
      if (!load) return;
      load.classList.toggle('wt-loading--on', !!on);
      load.setAttribute('aria-hidden', on ? 'false' : 'true');
      if (!on) {{
        if (loadTitle) loadTitle.textContent = 'Please wait…';
        if (loadSub) loadSub.textContent = 'Working…';
        return;
      }}
      if (mode === 'topics') {{
        if (loadTitle) loadTitle.textContent = 'Suggesting topics…';
        if (loadSub) loadSub.textContent = 'Only titles and keywords for the queue — no full articles.';
      }} else {{
        if (loadTitle) loadTitle.textContent = 'Refreshing queue…';
        if (loadSub) loadSub.textContent = 'Replacing pending ideas (titles + keywords only).';
      }}
    }}
    var btnQ = document.getElementById('wtBtnRefreshQueue');
    if (btnQ) btnQ.addEventListener('click', function() {{
      setLoad(true, 'refresh');
      fetch('/api/admin/writter/future-articles/refresh', {{ method: 'POST', credentials: 'same-origin' }})
        .then(function(r) {{ if (!r.ok) return r.text().then(function(t) {{ throw new Error(t || r.status); }}); return r.json(); }})
        .then(function() {{ location.reload(); }})
        .catch(function(e) {{ alert(e.message || 'Failed'); setLoad(false); }});
    }});
    var btn5 = document.getElementById('wtBtnAddFiveTopics');
    if (btn5) btn5.addEventListener('click', function() {{
      setLoad(true, 'topics');
      fetch('/api/admin/writter/future-articles/add-topics?count=5', {{ method: 'POST', credentials: 'same-origin' }})
        .then(function(r) {{ if (!r.ok) return r.text().then(function(t) {{ throw new Error(t || r.status); }}); return r.json(); }})
        .then(function() {{ location.reload(); }})
        .catch(function(e) {{ alert(e.message || 'Failed'); setLoad(false); }});
    }});
    document.querySelectorAll('.wt-btn-fut').forEach(function(b) {{
      b.addEventListener('click', function() {{
        var id = b.getAttribute('data-id');
        var act = b.getAttribute('data-fut');
        if (!id || !act || b.disabled) return;
        var path = '';
        if (act === 'approve') path = '/api/admin/writter/future-articles/' + encodeURIComponent(id) + '/approve';
        else if (act === 'reject') path = '/api/admin/writter/future-articles/' + encodeURIComponent(id) + '/reject';
        else if (act === 'regen') path = '/api/admin/writter/future-articles/' + encodeURIComponent(id) + '/regenerate';
        else if (act === 'gen') {{
          if (!confirm('Generate and publish this article? (Requires SEO quality ≥ {MIN_QUALITY_AUTO_PUBLISH} — otherwise saved as draft.)')) return;
          path = '/api/admin/writter/future-articles/' + encodeURIComponent(id) + '/generate';
        }} else return;
        setLoad(true);
        fetch(path, {{ method: 'POST', credentials: 'same-origin', headers: {{ 'Accept': 'application/json' }} }})
          .then(function(r) {{ if (!r.ok) return r.text().then(function(t) {{ throw new Error(t || r.status); }}); return r.json(); }})
          .then(function(d) {{
            if (d.warning) alert(d.warning);
            if (d.id && act === 'gen') {{
              window.location.href = '/admin/writter/article/' + d.id + '/review';
              return;
            }}
            location.reload();
          }})
          .catch(function(e) {{ alert(e.message || 'Failed'); setLoad(false); }});
      }});
    }});
  }})();
  document.querySelectorAll('.wt-dd').forEach(function(sel) {{
    sel.addEventListener('change', function() {{
      var v = this.value;
      var id = this.getAttribute('data-id');
      if (!v || !id) return;
      var reset = function() {{ sel.selectedIndex = 0; }};
      if (v === 'delete') {{
        if (!confirm('Delete this article permanently? This cannot be undone.')) {{ reset(); return; }}
        fetch('/api/admin/writter/articles/' + encodeURIComponent(id), {{
          method: 'DELETE',
          credentials: 'same-origin',
          headers: {{ 'Accept': 'application/json' }}
        }}).then(function(r) {{
          if (!r.ok) return r.text().then(function(t) {{ throw new Error(t || r.status); }});
          location.reload();
        }}).catch(function(e) {{ alert(e.message || 'Delete failed'); reset(); }});
        return;
      }}
      var body = v === 'publish' ? {{ status: 'published' }} : {{ status: 'draft' }};
      fetch('/api/admin/writter/articles/' + encodeURIComponent(id), {{
        method: 'PUT',
        credentials: 'same-origin',
        headers: {{ 'Content-Type': 'application/json', 'Accept': 'application/json' }},
        body: JSON.stringify(body)
      }}).then(function(r) {{
        if (!r.ok) return r.text().then(function(t) {{ throw new Error(t || r.status); }});
        location.reload();
      }}).catch(function(e) {{ alert(e.message || 'Update failed'); reset(); }});
    }});
  }});
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)


@router.get("/admin/writter/new", response_class=HTMLResponse)
async def writter_new_page(request: Request):
    redir = require_admin_redirect(request, "/admin/writter/new")
    if redir:
        return redir
    opts = "".join(
        f'<option value="{k}">{html_module.escape(v)}</option>'
        for k, v in ARTICLE_TYPE_LABELS.items()
    )
    goal_opts = "".join(
        f'<option value="{k}">{html_module.escape(v)}</option>'
        for k, v in PRIMARY_GOAL_LABELS.items()
    )
    preset_ids = list(RULE_PRESET_MESSAGES.keys())
    preset_label_short = {
        "preset_internal_links": "Use internal links automatically",
        "preset_mention_product": "Mention product in solution section",
        "preset_practical_tone": "Keep tone practical",
        "preset_no_hype": "Avoid hype language",
        "preset_faq_if_relevant": "Add FAQ if relevant",
        "preset_cta_end": "Add CTA near the end",
    }
    preset_checks = "".join(
        f'<label class="wt-inline-row"><input type="checkbox" class="preset-cb" data-preset="{html_module.escape(pid)}" id="pr_{pid}" checked /> '
        f"{html_module.escape(preset_label_short.get(pid, pid))}</label>"
        for pid in preset_ids
    )
    html = render_writter_new_article_html(
        article_type_options=opts,
        primary_goal_options=goal_opts,
        preset_checkboxes=preset_checks,
        admin_top_nav=admin_top_nav_html("writter"),
        admin_shell_nav=_admin_shell_nav("writter"),
        theme_script=ADMIN_THEME_SCRIPT.strip(),
        merchant_script=ADMIN_MERCHANT_SCRIPT.strip(),
    )
    return HTMLResponse(content=html)


@router.get("/admin/writter/article/{article_id}/review", response_class=HTMLResponse)
async def writter_article_review(request: Request, article_id: int):
    redir = require_admin_redirect(request, f"/admin/writter/article/{article_id}/review")
    if redir:
        return redir
    req_id = uuid.uuid4().hex[:12]
    _log.debug("writter review start article_id=%s req_id=%s", article_id, req_id)
    try:
        with get_db() as db:
            row = repo.get_blog_article_by_id(db, article_id)
            if not row:
                _log.info("writter review: article not found id=%s req_id=%s", article_id, req_id)
                return _writter_article_missing_html(article_id)
            # Snapshot while Session is open — avoids DetachedInstanceError after `with` exits.
            art = repo.blog_article_to_dict(row)

        title_esc = html_module.escape(art.get("title") or "")
        slug_raw = art.get("slug") or ""
        slug_esc = html_module.escape(slug_raw)
        status = (art.get("status") or "").strip()
        kw_esc = html_module.escape(art.get("keywords") or "")
        topic_esc = html_module.escape(art.get("topic") or "")
        content = art.get("content_html") or ""
        metrics = _only_dict(art.get("metrics_json") or {})
        m_imp = html_module.escape(str(metrics.get("estimated_impressions", "—")))
        m_ctr = metrics.get("estimated_ctr")
        if m_ctr is not None:
            try:
                m_ctr_s = html_module.escape(str(round(float(m_ctr), 4)))
            except (TypeError, ValueError):
                m_ctr_s = html_module.escape(str(m_ctr))
        else:
            m_ctr_s = "—"
        m_clk = html_module.escape(str(metrics.get("estimated_clicks", "—")))
        m_conv = html_module.escape(str(metrics.get("potential_conversions", "—")))
        seo = _only_dict(metrics.get("seo_qa"))
        scores = _only_dict(seo.get("scores"))
        verdict_esc = html_module.escape(str(seo.get("verdict") or "—"))
        plan = _only_dict(art.get("planning_json"))
        opp = plan.get("opportunity")
        val_sc = opp.get("estimated_value_score") if isinstance(opp, dict) else None
        val_cell = html_module.escape(str(val_sc)) if val_sc is not None else "—"
        seo_block = ""
        if scores:
            seo_block = f"""
          <h2 style="font-size:1rem;color:#94a3b8;margin:24px 0 8px;">SEO QA</h2>
          <p class="wt-meta">Verdict: <strong style="color:#e5e7eb;">{verdict_esc}</strong></p>
          <div class="wt-metrics" style="grid-template-columns:repeat(5,1fr);">
            <div class="wt-mc"><span>SEO</span><strong>{scores.get("seo", "—")}</strong></div>
            <div class="wt-mc"><span>Readability</span><strong>{scores.get("readability", "—")}</strong></div>
            <div class="wt-mc"><span>Originality</span><strong>{scores.get("originality", "—")}</strong></div>
            <div class="wt-mc"><span>Evidence</span><strong>{scores.get("evidence", "—")}</strong></div>
            <div class="wt-mc"><span>Product fit</span><strong>{scores.get("product_relevance", "—")}</strong></div>
          </div>"""
        plan_block = ""
        if isinstance(opp, dict) and opp:
            plan_block = f"""
          <h2 style="font-size:1rem;color:#94a3b8;margin:24px 0 8px;">Opportunity (pre-generation)</h2>
          <p class="wt-meta">Estimated value score: <strong>{val_cell}</strong> · Difficulty: {html_module.escape(str(opp.get("estimated_difficulty", "—")))}</p>
          <pre style="font-size:.78rem;background:#111827;padding:14px;border-radius:10px;overflow:auto;max-height:200px;color:#cbd5e1;">{_json_snippet_for_pre(opp, 6000)}</pre>"""
    
        is_draft = status == "draft"
        publish_block = ""
        if is_draft:
            publish_block = f"""
          <button type="button" class="wt-btn" id="wtPublishBtn">Publish</button>
          <p style="color:#94a3b8;font-size:.88rem;margin:12px 0 0;">Publishing makes this URL public: <code style="color:#22D3EE;">/blog/{slug_esc}</code></p>"""
        live_block = ""
        if status == "published":
            live_block = f'<a class="wt-btn wt-btn-live" href="/blog/{slug_esc}" target="_blank" rel="noopener">View live article</a>'
    
        status_badge = f'<span class="wt-pill" style="background:rgba(251,191,36,.15);color:#fbbf24;">Draft</span>' if is_draft else '<span class="wt-pill" style="background:rgba(74,222,128,.15);color:#4ade80;">Published</span>'
    
        gsc = _only_dict(metrics.get("gsc"))
        gsc_sug = metrics.get("gsc_suggestions")
        if gsc_sug is None:
            gsc_sug = {}
        ctr_v = _only_dict(metrics.get("ctr_variants"))
        gsc_panel = ""
        if isinstance(gsc, dict) and gsc:
            gsc_panel = f"""
          <h2 style="font-size:1rem;color:#94a3b8;margin:24px 0 8px;">Search Console (imported)</h2>
          <p class="wt-meta">Impressions: {html_module.escape(str(gsc.get("impressions", "—")))} · Clicks: {html_module.escape(str(gsc.get("clicks", "—")))} · CTR: {html_module.escape(str(gsc.get("ctr", "—")))} · Avg pos: {html_module.escape(str(gsc.get("avg_position", "—")))}</p>
          <pre style="font-size:.75rem;background:#111827;padding:12px;border-radius:8px;overflow:auto;max-height:120px;">{_json_snippet_for_pre(gsc_sug, 4000)}</pre>"""
        ctr_panel = ""
        if isinstance(ctr_v, dict) and ctr_v:
            ctr_panel = f"""
          <h2 style="font-size:1rem;color:#94a3b8;margin:24px 0 8px;">CTR variants (stored)</h2>
          <pre style="font-size:.75rem;background:#111827;padding:12px;border-radius:8px;overflow:auto;max-height:180px;">{_json_snippet_for_pre(ctr_v, 8000)}</pre>"""
    
        aid = int(article_id)
        toolbox = f"""
          <h2 style="font-size:1rem;color:#94a3b8;margin:24px 0 8px;">Editor &amp; growth tools</h2>
          <p class="wt-meta"><a href="/admin/writter/article/{aid}/edit">Open HTML editor</a> · <a href="/admin/writter/clusters">Content clusters</a></p>
          <div style="display:flex;flex-wrap:wrap;gap:8px;margin:12px 0;">
            <button type="button" class="wt-btn" style="padding:8px 14px;font-size:.82rem;" id="wtCtrBtn">Generate CTR variants</button>
            <button type="button" class="wt-btn" style="padding:8px 14px;font-size:.82rem;background:#334155;" id="wtConvBtn">Append conversion blocks</button>
            <select id="wtRefreshSel" style="padding:8px;border-radius:8px;background:#111827;color:#e5e7eb;border:1px solid rgba(255,255,255,.12);">
              <option value="">Refresh action…</option>
              <option value="intro">Regenerate intro</option>
              <option value="title">Improve title + meta</option>
              <option value="cta">Improve CTA</option>
              <option value="faq">Add FAQ</option>
              <option value="evidence">Add evidence block</option>
              <option value="clarity">Rewrite for clarity</option>
            </select>
            <button type="button" class="wt-btn" style="padding:8px 14px;font-size:.82rem;" id="wtRefreshGo">Run</button>
          </div>
          <p class="wt-meta">GSC import (JSON body: impressions, clicks, ctr, avg_position, queries[])</p>
          <textarea id="wtGscJson" placeholder='{{"impressions":1200,"clicks":18,"ctr":0.015,"avg_position":12.4,"queries":[{{"query":"example"}}]}}' style="width:100%;min-height:72px;font-size:.8rem;border-radius:8px;padding:10px;background:#111827;color:#e5e7eb;border:1px solid rgba(255,255,255,.12);box-sizing:border-box;"></textarea>
          <button type="button" class="wt-btn" style="margin-top:8px;padding:8px 14px;font-size:.82rem;" id="wtGscBtn">Import GSC metrics</button>
          <p class="wt-meta" style="margin-top:12px;">Version history: <button type="button" class="wt-btn" style="padding:6px 12px;font-size:.78rem;background:#334155;" id="wtVerLoad">Load versions</button></p>
          <pre id="wtVerOut" style="display:none;font-size:.72rem;background:#111827;padding:12px;border-radius:8px;max-height:160px;overflow:auto;"></pre>
          <p class="wt-err" id="wtToolErr" style="margin-top:8px;"></p>"""
    
        # Article HTML is concatenated, not f-interpolated: `{`/`}` in SVG/CSS/JS break f-string parsing.
        _body_html = content if isinstance(content, str) else str(content or "")
        html = (
            f"""<!DOCTYPE html>
    <html lang="en" data-theme="dark">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>Review — {title_esc} — Writter</title>
      <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
      <link rel="stylesheet" href="/static/styles.css" />
      <style>
      body {{ margin:0; font-family:Inter,system-ui,sans-serif; background:#0B0F19; color:#E5E7EB; min-height:100vh; display:flex; flex-direction:column; }}
      [data-theme="light"] body {{ background:#f8fafc; color:#0f172a; }}
      .wt-layout {{ flex:1; display:flex; min-height:0; }}
      .wt-side {{ width:240px; background:#0a0e18; border-right:1px solid rgba(255,255,255,.08); padding:24px 16px; flex-shrink:0; }}
      [data-theme="light"] .wt-side {{ background:#fff; border-color:rgba(15,23,42,.1); }}
      .wt-admin-nav a {{ display:block; padding:10px 14px; border-radius:8px; color:#9ca3af; text-decoration:none; font-size:.9rem; }}
      .wt-admin-nav a:hover {{ background:rgba(255,255,255,.05); color:#fff; }}
      .wt-admin-nav a.active {{ background:rgba(79,70,229,.15); color:#818cf8; font-weight:600; }}
      .wt-main {{ flex:1; padding:32px clamp(16px,4vw,40px) 80px; max-width:900px; margin-inline:auto; width:100%; min-width:0; }}
      .wt-toolbar-r {{ display:flex; flex-wrap:wrap; gap:12px; align-items:center; margin-bottom:20px; }}
      .wt-review-topbar {{ display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:12px 16px; margin-bottom:16px; width:100%; }}
      .wt-review-breadcrumb {{ display:flex; flex-wrap:wrap; align-items:center; gap:8px; min-width:0; }}
      .wt-review-topbar-actions {{ flex-shrink:0; margin-left:auto; }}
      .wt-btn-live {{ background:#0ea5e9 !important; padding:8px 16px !important; font-size:.85rem !important; }}
      .wt-btn {{ display:inline-flex; align-items:center; gap:8px; padding:10px 18px; border-radius:8px; background:#4F46E5; color:#fff; font-weight:600; text-decoration:none; border:none; cursor:pointer; font-size:.9rem; }}
      .wt-btn:hover {{ filter:brightness(1.05); }}
      .wt-btn:disabled {{ opacity:.55; cursor:not-allowed; }}
      .wt-preview {{ border:1px solid rgba(255,255,255,.1); border-radius:12px; padding:clamp(16px,3vw,28px); background:#111827; margin-top:16px; max-width:min(900px,100%); margin-inline:auto; box-sizing:border-box; }}
      [data-theme="light"] .wt-preview {{ background:#fff; border-color:rgba(15,23,42,.1); }}
      .wt-meta {{ color:#94a3b8; font-size:.88rem; margin:8px 0 0; }}
      .wt-metrics {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-top:16px; }}
      @media(max-width:700px){{ .wt-metrics{{ grid-template-columns:1fr 1fr; }} }}
      .wt-mc {{ background:rgba(79,70,229,.08); border-radius:10px; padding:10px 12px; font-size:.85rem; }}
      .wt-mc span {{ display:block; color:#64748b; font-size:.72rem; }}
      .wt-err {{ color:#f87171; margin-top:8px; }}
      .wt-pill {{ font-size:.75rem; padding:4px 10px; border-radius:99px; }}
      </style>
    </head>
    <body>
      {admin_top_nav_html("writter")}
      <div class="wt-layout">
        <aside class="wt-side">
          <div style="margin-bottom:16px;"><a href="/admin/writter">← All articles</a></div>
          {_admin_shell_nav("writter")}
        </aside>
        <main class="wt-main">
          <div class="wt-toolbar-r wt-review-topbar">
            <div class="wt-review-breadcrumb">
              <a href="/admin/writter" style="color:#94a3b8;">Writter</a>
              <span>/</span>
              <span>Review</span>
              {status_badge}
            </div>
            <div class="wt-review-topbar-actions">{live_block}</div>
          </div>
          <h1 style="font-size:1.5rem;margin:0 0 8px;">{title_esc}</h1>
          <p class="wt-meta">Slug: <code>{slug_esc}</code> · Keywords: {kw_esc}</p>
          <p class="wt-meta">Topic: {topic_esc}</p>
          <div class="wt-metrics">
            <div class="wt-mc"><span>Est. impressions</span><strong>{m_imp}</strong></div>
            <div class="wt-mc"><span>Est. CTR</span><strong>{m_ctr_s}</strong></div>
            <div class="wt-mc"><span>Est. clicks</span><strong>{m_clk}</strong></div>
            <div class="wt-mc"><span>Potential conversions</span><strong>{m_conv}</strong></div>
          </div>
          {plan_block}
          {seo_block}
          {gsc_panel}
          {ctr_panel}
          {toolbox}
          <div class="wt-toolbar-r" style="margin-top:20px;">
            {publish_block}
          </div>
          <p class="wt-err" id="wtPubErr"></p>
          <h2 style="font-size:1rem;color:#94a3b8;margin:24px 0 8px;">Preview</h2>
          <div class="wt-preview"><div class="content writter-article">"""
            + _body_html
            + f"""</div></div>
        </main>
      </div>
      <script>
      {ADMIN_THEME_SCRIPT.strip()}
      {ADMIN_MERCHANT_SCRIPT.strip()}
      (function() {{
        var aid = {article_id};
        function toolErr(t) {{ var e = document.getElementById('wtToolErr'); if (e) e.textContent = t || ''; }}
        var ctrB = document.getElementById('wtCtrBtn');
        if (ctrB) ctrB.onclick = function() {{
          toolErr(''); ctrB.disabled = true;
          fetch('/api/admin/writter/articles/' + aid + '/ctr-variants', {{ method: 'POST', credentials: 'same-origin' }})
            .then(function(r) {{ if (!r.ok) return r.text().then(function(t) {{ throw new Error(t); }}); return r.json(); }})
            .then(function() {{ location.reload(); }})
            .catch(function(e) {{ toolErr(e.message || 'Failed'); ctrB.disabled = false; }});
        }};
        var convB = document.getElementById('wtConvBtn');
        if (convB) convB.onclick = function() {{
          toolErr(''); convB.disabled = true;
          fetch('/api/admin/writter/articles/' + aid + '/conversion-blocks', {{ method: 'POST', credentials: 'same-origin' }})
            .then(function(r) {{ if (!r.ok) return r.text().then(function(t) {{ throw new Error(t); }}); return r.json(); }})
            .then(function() {{ location.reload(); }})
            .catch(function(e) {{ toolErr(e.message || 'Failed'); convB.disabled = false; }});
        }};
        var rfGo = document.getElementById('wtRefreshGo');
        if (rfGo) rfGo.onclick = function() {{
          var sel = document.getElementById('wtRefreshSel');
          var a = sel && sel.value;
          if (!a) return;
          toolErr(''); rfGo.disabled = true;
          fetch('/api/admin/writter/articles/' + aid + '/refresh', {{
            method: 'POST', credentials: 'same-origin',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ action: a }})
          }}).then(function(r) {{ if (!r.ok) return r.text().then(function(t) {{ throw new Error(t); }}); return r.json(); }})
            .then(function() {{ location.reload(); }})
            .catch(function(e) {{ toolErr(e.message || 'Failed'); rfGo.disabled = false; }});
        }};
        var gscB = document.getElementById('wtGscBtn');
        if (gscB) gscB.onclick = function() {{
          toolErr(''); var raw = document.getElementById('wtGscJson').value;
          var j; try {{ j = JSON.parse(raw); }} catch(e) {{ toolErr('Invalid JSON'); return; }}
          gscB.disabled = true;
          fetch('/api/admin/writter/articles/' + aid + '/gsc', {{
            method: 'POST', credentials: 'same-origin',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify(j)
          }}).then(function(r) {{ if (!r.ok) return r.text().then(function(t) {{ throw new Error(t); }}); return r.json(); }})
            .then(function() {{ location.reload(); }})
            .catch(function(e) {{ toolErr(e.message || 'Failed'); gscB.disabled = false; }});
        }};
        var vLoad = document.getElementById('wtVerLoad');
        if (vLoad) vLoad.onclick = function() {{
          fetch('/api/admin/writter/articles/' + aid + '/versions', {{ credentials: 'same-origin' }})
            .then(function(r) {{ return r.json(); }})
            .then(function(d) {{
              var el = document.getElementById('wtVerOut');
              el.style.display = 'block';
              el.textContent = JSON.stringify(d.versions || [], null, 2);
            }});
        }};
      }})();
      (function() {{
        var btn = document.getElementById('wtPublishBtn');
        if (!btn) return;
        btn.onclick = function() {{
          var err = document.getElementById('wtPubErr');
          if (err) err.textContent = '';
          btn.disabled = true;
          btn.textContent = 'Publishing…';
          fetch('/api/admin/writter/articles/{article_id}', {{
            method: 'PUT',
            credentials: 'same-origin',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ status: 'published' }})
          }}).then(function(r) {{
            if (!r.ok) return r.text().then(function(t) {{ throw new Error(t); }});
            return r.json();
          }}).then(function() {{ location.reload(); }})
          .catch(function(e) {{
            if (err) err.textContent = e.message || 'Failed';
            btn.disabled = false;
            btn.textContent = 'Publish';
          }});
        }};
      }})();
      </script>
    </body>
    </html>"""
        )
        return HTMLResponse(content=html)
    except Exception as e:
        u = get_current_user(request)
        em = (u or {}).get("email") or ""
        _log.exception(
            "writter review FAILED article_id=%s req_id=%s email=%s path=%s",
            article_id,
            req_id,
            em,
            request.url.path,
        )
        return _writter_review_error_html(request, article_id, e, req_id)


class RuleItem(BaseModel):
    kind: str
    url: Optional[str] = None
    value: Optional[str] = None


class ScreenshotEvidenceItem(BaseModel):
    """Product screenshot URL plus editor context so the model places images deliberately."""

    url: str = Field(..., min_length=1)
    caption: str = ""


class EvidencePayload(BaseModel):
    use_product_screenshots: bool = False
    add_diagram: bool = False
    add_metrics: bool = False
    add_use_case: bool = False
    screenshot_urls: List[str] = Field(default_factory=list)
    screenshots: List[ScreenshotEvidenceItem] = Field(default_factory=list)
    product_screen_ids: List[str] = Field(default_factory=list)
    metrics_manual: str = ""
    customer_scenario: str = ""
    quote: str = ""
    diagram_note: str = ""
    recommended_proof_plan: Optional[List[str]] = None


class CreateArticleBody(BaseModel):
    article_type: str = Field(..., description="Writter article type key")
    topic: str
    keywords: str = ""
    primary_goal: str = "organic_traffic"
    audience: str = ""
    country_language: str = ""
    business_goal: str = ""
    generation_mode: str = "standard"
    evidence: EvidencePayload = Field(default_factory=EvidencePayload)
    rules: List[RuleItem] = Field(default_factory=list)
    rule_presets: List[str] = Field(default_factory=list)
    visual_mode: str = "auto"
    visual_description: str = ""
    visual_index: int = 0
    visual_seed: int = 0
    visual_layout: str = "horizontal"
    publish: bool = False
    outline_sections: Optional[List[str]] = None
    article_plan_json: Optional[Dict[str, Any]] = None


class OpportunityScoreBody(BaseModel):
    topic: str
    keywords: str = ""
    article_type: str = "informational"
    primary_goal: str = "organic_traffic"
    audience: str = ""
    country_language: str = ""
    business_goal: str = ""


class ArticlePlanBody(BaseModel):
    topic: str
    keywords: str = ""
    article_type: str = "informational"
    primary_goal: str = "organic_traffic"
    audience: str = ""
    country_language: str = ""
    business_goal: str = ""


class UpdateArticleBody(BaseModel):
    title: Optional[str] = None
    content_html: Optional[str] = None
    meta_description: Optional[str] = None
    status: Optional[str] = None
    version_note: Optional[str] = None
    change_summary: Optional[str] = None


class BatchCreateBody(BaseModel):
    articles: List[CreateArticleBody] = Field(..., max_length=50)


class AnalyticsBody(BaseModel):
    time_ms: Optional[int] = None
    scroll_pct: Optional[float] = None
    cta_click: bool = False


class ClusterCreateBody(BaseModel):
    slug: str
    name: str
    description: str = ""


class ArticleClusterBody(BaseModel):
    cluster_id: Optional[int] = None
    cluster_role: str = "supporting"


class RefreshActionBody(BaseModel):
    action: str


class GscImportBody(BaseModel):
    impressions: float = 0
    clicks: float = 0
    ctr: float = 0
    avg_position: float = 0
    queries: List[Dict[str, Any]] = Field(default_factory=list)


class RestoreVersionBody(BaseModel):
    version_id: int


class CheapVisualBody(BaseModel):
    description: str = ""
    topic: str = ""
    keywords: str = ""
    seed: int = 0


class FinalizeAutoArticleBody(BaseModel):
    article_id: int
    batch_id: str
    delete_siblings: bool = True


@router.get("/api/admin/writter/visual-options")
async def api_visual_options(
    request: Request,
    topic: str = "",
    keywords: str = "",
    seed: int = 0,
    layout: str = "horizontal",
):
    require_admin_http(request)
    opts = build_visual_options(topic, keywords, seed=seed, layout=layout)
    return JSONResponse({"options": opts})


@router.post("/api/admin/writter/opportunity-score")
async def api_opportunity_score(request: Request, body: OpportunityScoreBody):
    require_admin_http(request)
    at = (body.article_type or "informational").strip()
    if at not in VALID_ARTICLE_TYPES:
        raise HTTPException(400, detail=f"Invalid article_type: {at}")
    with get_db() as db:
        siblings = repo.get_published_slugs_titles_excluding(db, exclude_slug=None, limit=500)
        icount = len(siblings)
        dup = repo.count_blog_articles_same_topic(db, body.topic)
    pg = (body.primary_goal or "organic_traffic").strip()
    if pg not in VALID_PRIMARY_GOALS:
        pg = "organic_traffic"
    out = score_article_opportunity(
        topic=body.topic,
        keywords=body.keywords,
        article_type=at,
        audience=body.audience,
        country_language=body.country_language,
        business_goal=body.business_goal,
        internal_article_count=icount,
        primary_goal=pg,
    )
    out["duplicate_topic_count"] = dup
    out["published_articles_for_linking"] = icount
    return JSONResponse(out)


@router.post("/api/admin/writter/article-plan")
async def api_article_plan(request: Request, body: ArticlePlanBody):
    """Full smart plan: audience, outline, proof, visual hint, CTA direction, opportunity, internal links."""
    require_admin_http(request)
    at = (body.article_type or "informational").strip()
    if at not in VALID_ARTICLE_TYPES:
        raise HTTPException(400, detail=f"Invalid article_type: {at}")
    pg = (body.primary_goal or "organic_traffic").strip()
    if pg not in VALID_PRIMARY_GOALS:
        pg = "organic_traffic"
    with get_db() as db:
        settings = get_settings(db)
        defaults = {
            "writter_default_country_language": settings.get("writter_default_country_language") or "",
            "writter_default_audience": settings.get("writter_default_audience") or "",
            "writter_default_cta": settings.get("writter_default_cta") or "",
        }
        siblings = repo.get_published_slugs_titles_excluding(db, exclude_slug=None, limit=40)
        icount = len(siblings)
        link_sug = suggest_internal_link_placements(body.topic, body.keywords, siblings, limit=8)
    plan = build_article_plan(
        topic=body.topic,
        keywords=body.keywords,
        article_type=at,
        primary_goal=pg,
        audience_override=body.audience,
        country_language_override=body.country_language,
        business_goal_override=body.business_goal,
        settings_defaults=defaults,
        internal_article_count=icount,
        internal_link_suggestions=link_sug,
    )
    return JSONResponse(plan)


@router.post("/api/admin/writter/upload-screenshots")
async def api_upload_writter_screenshots(request: Request, files: List[UploadFile] = File(...)):
    """Admin-only: save product screenshots under /static/uploads/writter/ and return public URLs for evidence."""
    require_admin_http(request)
    if not files:
        raise HTTPException(400, detail="No files uploaded.")
    if len(files) > 20:
        raise HTTPException(400, detail="Too many files (max 20 per request).")
    _WRITTER_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    urls: List[str] = []
    for up in files:
        ct = ((up.content_type or "").split(";")[0]).strip().lower()
        if ct not in _WRITTER_SCREENSHOT_TYPES:
            raise HTTPException(
                400,
                detail=f"Unsupported image type: {ct or 'unknown'}. Use PNG, JPEG, WebP, or GIF.",
            )
        raw = await up.read()
        if len(raw) > _WRITTER_SCREENSHOT_MAX_BYTES:
            raise HTTPException(400, detail="Each image must be 5 MB or smaller.")
        ext = _WRITTER_SCREENSHOT_TYPES[ct]
        fname = f"{uuid.uuid4().hex}{ext}"
        out_path = _WRITTER_SCREENSHOT_DIR / fname
        out_path.write_bytes(raw)
        urls.append(f"/static/uploads/writter/{fname}")
    return JSONResponse({"urls": urls})


def _build_article_bundle(
    db: Any,
    body: CreateArticleBody,
    author_email: str,
    *,
    extra_user_instruction: str = "",
    visual_seed_effective: Optional[int] = None,
) -> Dict[str, Any]:
    """Generate HTML + metrics without inserting (used for retries before commit)."""
    at = body.article_type
    if at not in VALID_ARTICLE_TYPES:
        raise HTTPException(400, detail=f"Invalid article_type: {at}")

    mode = (body.generation_mode or "standard").strip().lower()
    if mode not in ("fast", "standard", "authority"):
        mode = "standard"

    pg = (body.primary_goal or "organic_traffic").strip()
    if pg not in VALID_PRIMARY_GOALS:
        pg = "organic_traffic"

    rules_payload: List[Dict[str, Any]] = []
    for pid in body.rule_presets or []:
        if pid in RULE_PRESET_MESSAGES:
            rules_payload.append({"kind": pid})
    for r in body.rules:
        d = {"kind": r.kind}
        if r.url:
            d["url"] = r.url
        if r.value is not None:
            d["value"] = r.value
        rules_payload.append(d)

    api_key = _settings_openai_key()
    settings = get_settings(db)
    type_prompt = get_writter_type_prompt(settings, at)
    siblings = repo.get_published_slugs_titles_excluding(db, exclude_slug=None, limit=40)
    icount = len(siblings)
    defaults = {
        "writter_default_country_language": settings.get("writter_default_country_language") or "",
        "writter_default_audience": settings.get("writter_default_audience") or "",
        "writter_default_cta": settings.get("writter_default_cta") or "",
    }

    full_plan: Optional[Dict[str, Any]] = None
    if isinstance(body.article_plan_json, dict) and body.article_plan_json:
        full_plan = body.article_plan_json
    link_sug = suggest_internal_link_placements(body.topic, body.keywords, siblings, limit=8)
    if not full_plan:
        full_plan = build_article_plan(
            topic=body.topic,
            keywords=body.keywords,
            article_type=at,
            primary_goal=pg,
            audience_override=body.audience,
            country_language_override=body.country_language,
            business_goal_override=body.business_goal,
            settings_defaults=defaults,
            internal_article_count=icount,
            internal_link_suggestions=link_sug,
        )
    opportunity = full_plan.get("opportunity") if isinstance(full_plan.get("opportunity"), dict) else {}
    if not opportunity:
        opportunity = score_article_opportunity(
            topic=body.topic,
            keywords=body.keywords,
            article_type=at,
            primary_goal=pg,
            audience=(body.audience or "").strip() or full_plan.get("inferred_audience") or "",
            country_language=(body.country_language or "").strip() or full_plan.get("country_language") or "",
            business_goal=(body.business_goal or "").strip() or full_plan.get("business_goal_interpretation") or "",
            internal_article_count=icount,
        )

    audience = (body.audience or "").strip() or (full_plan.get("inferred_audience") or "")
    country_language = (body.country_language or "").strip() or (full_plan.get("country_language") or "")
    business_goal = (body.business_goal or "").strip() or (full_plan.get("business_goal_interpretation") or "")
    link_sug = full_plan.get("internal_link_suggestions") or link_sug
    outline_sections = body.outline_sections or full_plan.get("blueprint_outline") or build_outline_headings(at, body.topic)

    opp_for_gen = dict(opportunity) if isinstance(opportunity, dict) else {}
    cta_dir = full_plan.get("cta_direction") if isinstance(full_plan, dict) else None
    if cta_dir:
        opp_for_gen["cta_direction"] = cta_dir

    evidence_dict = body.evidence.model_dump()
    rp = full_plan.get("recommended_proof") if isinstance(full_plan, dict) else None
    if rp and not evidence_dict.get("recommended_proof_plan"):
        evidence_dict["recommended_proof_plan"] = rp

    slug_base = slugify(body.topic, body.keywords)

    def exists(s: str) -> bool:
        return repo.slug_exists(db, s)

    final_slug = ensure_unique_slug(exists, slug_base)

    vseed = int(visual_seed_effective) if visual_seed_effective is not None else int(body.visual_seed or 0)

    vm = (body.visual_mode or "auto").strip().lower()
    if vm == "none":
        v: Dict[str, Any] = {"html": "", "label": ""}
        wrap = ""
    elif vm == "describe" and (body.visual_description or "").strip():
        cv = route_cheap_visual(
            body.visual_description or "",
            body.topic,
            body.keywords,
            seed=vseed,
        )
        v = {"html": cv.get("html") or "", "label": cv.get("label") or "Diagram"}
        wrap = f'<div class="writter-visual-wrap">{v["html"]}</div>' if v.get("html") else ""
    else:
        layout = body.visual_layout or "horizontal"
        rv = full_plan.get("recommended_visual") if isinstance(full_plan, dict) else None
        if isinstance(rv, dict) and rv.get("layout"):
            layout = str(rv["layout"])
        visuals = build_visual_options(
            body.topic,
            body.keywords,
            seed=vseed,
            layout=layout,
        )
        vi = max(0, min(body.visual_index, len(visuals) - 1)) if visuals else 0
        v = visuals[vi] if visuals else {"html": "", "label": ""}
        wrap = f'<div class="writter-visual-wrap">{v["html"]}</div>' if v.get("html") else ""

    payload, metrics = generate_article_with_ai(
        api_key=api_key,
        article_type=at,
        topic=body.topic,
        keywords=body.keywords,
        rules=rules_payload,
        internal_context=siblings,
        visual_label=v.get("label") or "",
        type_prompt_extra=type_prompt,
        generation_mode=mode,
        audience=audience,
        country_language=country_language,
        business_goal=business_goal,
        evidence=evidence_dict,
        opportunity_plan=opp_for_gen,
        internal_link_suggestions=link_sug,
        outline_sections=outline_sections,
        extra_user_instruction=extra_user_instruction,
    )

    inner = payload.get("content_html") or ""
    if wrap:
        full_html = wrap + inner
    else:
        full_html = inner
    full_html, used_links = inject_internal_links(full_html, siblings)

    h1 = (payload.get("h1") or body.topic or "").strip()
    seo_qa = run_seo_quality_audit(
        content_html=full_html,
        title=(payload.get("seo_title") or body.topic)[:500],
        meta_description=payload.get("meta_description") or "",
        slug=final_slug,
        keywords=body.keywords,
        h1=h1,
    )
    metrics["seo_qa"] = seo_qa
    metrics = _merge_metrics_with_admin_ai_insights(
        metrics,
        api_key=_settings_openai_key(),
        title=(payload.get("seo_title") or body.topic)[:500],
        meta_description=payload.get("meta_description") or "",
        topic=body.topic,
        keywords=body.keywords,
        article_type=at,
        content_html=full_html,
        views=0,
        sessions=0,
        avg_time_s=0.0,
        avg_scroll=0.0,
        cta_clicks=0,
        internal_links_n=len(used_links) if isinstance(used_links, list) else 0,
    )

    planning_json: Dict[str, Any] = {
        "inputs": {
            "topic": body.topic,
            "keywords": body.keywords,
            "article_type": at,
            "primary_goal": pg,
            "audience": audience,
            "country_language": country_language,
            "business_goal": business_goal,
            "generation_mode": mode,
            "visual_mode": body.visual_mode or "auto",
            "visual_description": body.visual_description or "",
            "visual_seed": vseed,
            "visual_index": int(body.visual_index or 0),
            "visual_layout": body.visual_layout or "horizontal",
            "rule_presets": body.rule_presets or [],
        },
        "article_plan": full_plan,
        "outline_sections": outline_sections,
        "evidence": evidence_dict,
        "opportunity": opportunity,
        "internal_link_suggestions": link_sug,
    }

    return {
        "payload": payload,
        "metrics": metrics,
        "full_html": full_html,
        "final_slug": final_slug,
        "v": v,
        "planning_json": planning_json,
        "used_links": used_links,
        "rules_payload": rules_payload,
        "at": at,
        "pg": pg,
        "mode": mode,
    }


def _create_article_from_body(body: CreateArticleBody, author_email: str) -> Dict[str, Any]:
    with get_db() as db:
        spam = extended_creation_blocked_message(
            same_topic_count=repo.count_blog_articles_same_topic(db, body.topic),
            same_primary_keyword_count=repo.count_articles_sharing_primary_keyword(db, body.keywords),
            author_24h_count=repo.count_articles_by_author_since(db, author_email, 24),
            similar_title_pairs=repo.count_near_duplicate_titles(db, body.topic),
        )
        if spam:
            raise HTTPException(400, detail=spam)

        b = _build_article_bundle(db, body, author_email)
        payload = b["payload"]
        metrics = b["metrics"]
        full_html = b["full_html"]
        final_slug = b["final_slug"]
        v = b["v"]
        planning_json = b["planning_json"]
        used_links = b["used_links"]
        rules_payload = b["rules_payload"]
        at = b["at"]

        now = datetime.now(timezone.utc)
        published_at = now if body.publish else None
        status = "published" if body.publish else "draft"

        if body.publish:
            blocked = publish_blocked_by_quality(metrics)
            if blocked:
                raise HTTPException(400, detail=blocked)

        row = repo.create_blog_article(
            db,
            slug=final_slug,
            title=payload.get("seo_title") or body.topic[:500],
            article_type=at,
            topic=body.topic,
            keywords=body.keywords,
            rules_json=rules_payload,
            content_html=full_html,
            meta_description=payload.get("meta_description") or "",
            structure_json=payload.get("structure_outline"),
            visual_html=v.get("html"),
            metrics_json=metrics,
            planning_json=planning_json,
            internal_links_json=used_links,
            status=status,
            author_email=author_email,
            published_at=published_at,
        )
        db.flush()
        out = repo.blog_article_to_dict(row)
        out["metrics"] = metrics
        return out


def _auto_article_stream_run(author_email: str):
    """
    Yield event dicts for SSE. Creates _AUTO_ARTICLE_VARIANTS drafts (same batch_id); user publishes one via finalize.
    """
    batch_id = uuid.uuid4().hex[:24]
    api_key = _settings_openai_key()
    with get_db() as db:
        existing = repo.list_blog_topics_and_titles(db)
        brief = suggest_auto_article_brief(api_key, existing_topics=existing)
        topic = brief["topic"]
        spam = extended_creation_blocked_message(
            same_topic_count=repo.count_blog_articles_same_topic(db, topic),
            same_primary_keyword_count=repo.count_articles_sharing_primary_keyword(db, brief.get("keywords") or ""),
            author_24h_count=repo.count_articles_by_author_since(db, author_email, 24),
            similar_title_pairs=repo.count_near_duplicate_titles(db, topic),
        )
        if spam:
            yield {"phase": "error", "detail": spam}
            return

        yield {
            "phase": "brief",
            "batch_id": batch_id,
            "topic": topic,
            "keywords": brief.get("keywords") or "",
            "article_type": brief["article_type"],
            "primary_goal": brief["primary_goal"],
            "rationale": brief.get("rationale") or "",
        }

        body = CreateArticleBody(
            article_type=brief["article_type"],
            topic=topic,
            keywords=brief.get("keywords") or "",
            primary_goal=brief["primary_goal"],
            audience="",
            country_language="",
            business_goal="",
            generation_mode="authority",
            evidence=EvidencePayload(),
            rules=[],
            rule_presets=list(RULE_PRESET_MESSAGES.keys()),
            visual_mode="auto",
            visual_description="",
            visual_index=0,
            visual_seed=0,
            visual_layout="horizontal",
            publish=False,
            outline_sections=None,
            article_plan_json=None,
        )

        candidates: List[Dict[str, Any]] = []
        for attempt in range(_AUTO_ARTICLE_VARIANTS):
            yield {
                "phase": "attempt_start",
                "attempt": attempt + 1,
                "total": _AUTO_ARTICLE_VARIANTS,
                "topic": topic,
            }
            extra_instr = ""
            if attempt > 0:
                extra_instr = (
                    "Alternative draft variant (same topic and keywords). Use different examples, "
                    "reframe or reorder sections where helpful, and vary internal link emphasis. "
                    "Keep authority depth and length targets."
                )
            bundle = _build_article_bundle(
                db,
                body,
                author_email,
                extra_user_instruction=extra_instr,
                visual_seed_effective=attempt,
            )
            planning = dict(bundle["planning_json"])
            planning["writter_auto_batch"] = {
                "batch_id": batch_id,
                "attempt": attempt + 1,
                "total": _AUTO_ARTICLE_VARIANTS,
            }
            payload = bundle["payload"]
            metrics = bundle["metrics"]
            seo = metrics.get("seo_qa") if isinstance(metrics.get("seo_qa"), dict) else {}
            scores = seo.get("scores") if isinstance(seo.get("scores"), dict) else {}
            overall = scores.get("overall")
            verdict = (seo.get("verdict") or "").strip()
            plain = re.sub(r"<[^>]+>", " ", bundle.get("full_html") or "")
            words = len(re.findall(r"\b\w+\b", plain))

            row = repo.create_blog_article(
                db,
                slug=bundle["final_slug"],
                title=payload.get("seo_title") or body.topic[:500],
                article_type=bundle["at"],
                topic=body.topic,
                keywords=body.keywords,
                rules_json=bundle["rules_payload"],
                content_html=bundle["full_html"],
                meta_description=payload.get("meta_description") or "",
                structure_json=payload.get("structure_outline"),
                visual_html=bundle["v"].get("html"),
                metrics_json=metrics,
                planning_json=planning,
                internal_links_json=bundle["used_links"],
                status="draft",
                author_email=author_email,
                published_at=None,
                auto_generation_batch_id=batch_id,
            )
            db.flush()
            cand = {
                "article_id": row.id,
                "attempt": attempt + 1,
                "overall": overall,
                "verdict": verdict,
                "title": (payload.get("seo_title") or body.topic)[:500],
                "word_count_approx": words,
            }
            candidates.append(cand)
            yield {"phase": "attempt_done", **cand}

        yield {"phase": "complete", "batch_id": batch_id, "brief": brief, "candidates": candidates}


def _generate_from_future_row(db: Any, row: Any, author_email: str) -> Dict[str, Any]:
    """Create + publish from an approved WritterFutureArticle row (quality gate 80)."""
    body = CreateArticleBody(
        article_type=(row.article_type or "informational").strip(),
        topic=(row.topic or "").strip(),
        keywords=(row.keywords or "").strip(),
        primary_goal=(row.primary_goal or "organic_traffic").strip(),
        audience="",
        country_language="",
        business_goal="",
        generation_mode="authority",
        evidence=EvidencePayload(),
        rules=[],
        rule_presets=list(RULE_PRESET_MESSAGES.keys()),
        visual_mode="auto",
        visual_description="",
        visual_index=0,
        visual_seed=0,
        visual_layout="horizontal",
        publish=True,
        outline_sections=None,
        article_plan_json=None,
    )
    spam = extended_creation_blocked_message(
        same_topic_count=repo.count_blog_articles_same_topic(db, body.topic),
        same_primary_keyword_count=repo.count_articles_sharing_primary_keyword(db, body.keywords),
        author_24h_count=repo.count_articles_by_author_since(db, author_email, 24),
        similar_title_pairs=repo.count_near_duplicate_titles(db, body.topic),
    )
    if spam:
        raise HTTPException(400, detail=spam)

    extra = ""
    last_bundle: Optional[Dict[str, Any]] = None
    last_metrics: Optional[Dict[str, Any]] = None
    for attempt in range(5):
        bundle = _build_article_bundle(
            db,
            body,
            author_email,
            extra_user_instruction=extra,
            visual_seed_effective=attempt,
        )
        last_bundle = bundle
        metrics = bundle["metrics"]
        last_metrics = metrics
        blocked = publish_blocked_by_quality(metrics, min_overall=MIN_QUALITY_AUTO_PUBLISH)
        ov = (metrics.get("seo_qa") or {}).get("scores", {}).get("overall")
        if not blocked and isinstance(ov, int) and ov >= MIN_QUALITY_AUTO_PUBLISH:
            payload = bundle["payload"]
            art = repo.create_blog_article(
                db,
                slug=bundle["final_slug"],
                title=payload.get("seo_title") or body.topic[:500],
                article_type=bundle["at"],
                topic=body.topic,
                keywords=body.keywords,
                rules_json=bundle["rules_payload"],
                content_html=bundle["full_html"],
                meta_description=payload.get("meta_description") or "",
                structure_json=payload.get("structure_outline"),
                visual_html=bundle["v"].get("html"),
                metrics_json=metrics,
                planning_json=bundle["planning_json"],
                internal_links_json=bundle["used_links"],
                status="published",
                author_email=author_email,
                published_at=datetime.now(timezone.utc),
            )
            db.flush()
            repo.update_writter_future_article(
                db,
                row,
                status="done",
                generated_article_id=art.id,
            )
            out = repo.blog_article_to_dict(art)
            out["metrics"] = metrics
            out["attempts_used"] = attempt + 1
            return out
        extra = (
            f"Previous draft overall SEO score was {ov}. Improve depth, examples, and internal links. "
            f"Target at least {MIN_QUALITY_AUTO_PUBLISH} overall."
        )

    assert last_bundle is not None and last_metrics is not None
    payload = last_bundle["payload"]
    art = repo.create_blog_article(
        db,
        slug=last_bundle["final_slug"],
        title=payload.get("seo_title") or body.topic[:500],
        article_type=last_bundle["at"],
        topic=body.topic,
        keywords=body.keywords,
        rules_json=last_bundle["rules_payload"],
        content_html=last_bundle["full_html"],
        meta_description=payload.get("meta_description") or "",
        structure_json=payload.get("structure_outline"),
        visual_html=last_bundle["v"].get("html"),
        metrics_json=last_metrics,
        planning_json=last_bundle["planning_json"],
        internal_links_json=last_bundle["used_links"],
        status="draft",
        author_email=author_email,
        published_at=None,
    )
    db.flush()
    repo.update_writter_future_article(
        db,
        row,
        status="approved",
        generated_article_id=art.id,
    )
    out = repo.blog_article_to_dict(art)
    out["metrics"] = last_metrics
    out["warning"] = (
        f"Saved as draft (score below {MIN_QUALITY_AUTO_PUBLISH} after 5 attempts). Edit and publish from Review."
    )
    out["attempts_used"] = 5
    return out


@router.post("/api/admin/writter/articles")
async def api_create_article(request: Request, body: CreateArticleBody):
    require_admin_http(request)
    user = get_current_user(request)
    email = (user.get("email") or "") if user else ""
    try:
        out = _create_article_from_body(body, email)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=str(e)[:500])
    return JSONResponse(out)


@router.post("/api/admin/writter/articles/batch")
async def api_batch_articles(request: Request, body: BatchCreateBody):
    require_admin_http(request)
    user = get_current_user(request)
    email = (user.get("email") or "") if user else ""
    results = []
    errors = []
    for i, item in enumerate(body.articles):
        try:
            results.append(_create_article_from_body(item, email))
        except Exception as e:
            errors.append({"index": i, "error": str(e)[:300]})
    return JSONResponse({"created": results, "errors": errors})


@router.post("/api/admin/writter/auto-article/stream")
async def api_auto_article_stream(request: Request):
    """Server-Sent Events: brief → per-attempt progress (title, score, word count) → complete with candidates."""
    require_admin_http(request)
    user = get_current_user(request)
    email = (user.get("email") or "") if user else ""

    def iter_sse():
        try:
            for ev in _auto_article_stream_run(email):
                yield f"data: {json.dumps(_sanitize_for_json(ev), ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps(_sanitize_for_json({'phase': 'error', 'detail': str(e)[:800]}), ensure_ascii=False)}\n\n"

    return StreamingResponse(
        iter_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/admin/writter/auto-article/finalize")
async def api_auto_article_finalize(request: Request, body: FinalizeAutoArticleBody):
    """Publish one chosen draft from an auto batch; optional delete other drafts in the batch."""
    require_admin_http(request)
    user = get_current_user(request)
    email = (user.get("email") or "") if user else ""
    with get_db() as db:
        row = repo.get_blog_article_by_id(db, body.article_id)
        if not row:
            raise HTTPException(404, detail="Not found")
        bid_row = (getattr(row, "auto_generation_batch_id", None) or "").strip()
        if bid_row != (body.batch_id or "").strip():
            raise HTTPException(400, detail="batch_id does not match this article")
        ae = (row.author_email or "").strip().lower()
        em = (email or "").strip().lower()
        if ae and em and ae != em:
            raise HTTPException(403, detail="This article was created under a different admin user")
        if (row.status or "") == "published":
            raise HTTPException(400, detail="Already published")
        metrics = row.metrics_json if isinstance(row.metrics_json, dict) else {}
        blocked = publish_blocked_by_quality(metrics, min_overall=42)
        if blocked:
            raise HTTPException(400, detail=blocked)
        now = datetime.now(timezone.utc)
        repo.update_blog_article(db, row, status="published", published_at=now)
        if body.delete_siblings:
            repo.delete_drafts_in_auto_batch_except(db, bid_row, body.article_id)
        out = repo.blog_article_to_dict(row)
    return JSONResponse(out)


@router.post("/api/admin/writter/auto-article")
async def api_auto_article(request: Request):
    """Non-streaming: runs full multi-variant run and returns the final `complete` payload (for scripts)."""
    require_admin_http(request)
    user = get_current_user(request)
    email = (user.get("email") or "") if user else ""
    try:
        last: Optional[Dict[str, Any]] = None
        for ev in _auto_article_stream_run(email):
            last = ev
            if ev.get("phase") == "error":
                raise HTTPException(400, detail=ev.get("detail", "Failed"))
        if not last or last.get("phase") != "complete":
            raise HTTPException(500, detail="Generation incomplete")
        return JSONResponse(last)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=str(e)[:500])


@router.get("/api/admin/writter/future-articles")
async def api_future_articles_list(request: Request):
    require_admin_http(request)
    with get_db() as db:
        rows = repo.list_writter_future_articles(db)
    return JSONResponse({"items": rows})


@router.post("/api/admin/writter/future-articles/refresh")
async def api_future_articles_refresh(request: Request):
    """Replace pending/rejected queue rows with new AI suggestions."""
    require_admin_http(request)
    api_key = _settings_openai_key()
    with get_db() as db:
        repo.delete_writter_future_articles_by_statuses(db, ("pending", "rejected"))
        existing = repo.list_blog_topics_and_titles(db)
        ideas = suggest_future_topics_keywords_only(api_key, existing_topics=existing, count=12)
        for idea in ideas:
            repo.insert_writter_future_article(
                db,
                topic=idea["topic"],
                keywords=idea.get("keywords") or "",
                article_type="informational",
                primary_goal="organic_traffic",
                briefing_json={"note": "topic+keywords only"},
                status="pending",
            )
        rows = repo.list_writter_future_articles(db)
    return JSONResponse({"items": rows})


@router.post("/api/admin/writter/future-articles/add-topics")
async def api_future_articles_add_topics(request: Request, count: int = 5):
    """Append new AI topic rows without clearing existing queue (default 5)."""
    require_admin_http(request)
    api_key = _settings_openai_key()
    n = max(1, min(15, int(count)))
    with get_db() as db:
        existing = repo.list_blog_topics_and_titles(db)
        existing.extend(repo.list_future_queue_topics(db))
        ideas = suggest_future_topics_keywords_only(api_key, existing_topics=existing, count=n)
        for idea in ideas:
            repo.insert_writter_future_article(
                db,
                topic=idea["topic"],
                keywords=idea.get("keywords") or "",
                article_type="informational",
                primary_goal="organic_traffic",
                briefing_json={"note": "topic+keywords only"},
                status="pending",
            )
        rows = repo.list_writter_future_articles(db)
    return JSONResponse({"items": rows})


@router.post("/api/admin/writter/future-articles/{row_id}/approve")
async def api_future_approve(request: Request, row_id: int):
    require_admin_http(request)
    with get_db() as db:
        row = repo.get_writter_future_article(db, row_id)
        if not row:
            raise HTTPException(404, detail="Not found")
        if (row.status or "") == "done":
            raise HTTPException(400, detail="Already generated")
        repo.update_writter_future_article(db, row, status="approved")
        item = repo.get_writter_future_article_dict(db, row_id)
    return JSONResponse({"item": item})


@router.post("/api/admin/writter/future-articles/{row_id}/reject")
async def api_future_reject(request: Request, row_id: int):
    require_admin_http(request)
    with get_db() as db:
        row = repo.get_writter_future_article(db, row_id)
        if not row:
            raise HTTPException(404, detail="Not found")
        if (row.status or "") == "done":
            raise HTTPException(400, detail="Already generated")
        repo.update_writter_future_article(db, row, status="rejected")
        item = repo.get_writter_future_article_dict(db, row_id)
    return JSONResponse({"item": item})


@router.post("/api/admin/writter/future-articles/{row_id}/regenerate")
async def api_future_regenerate(request: Request, row_id: int):
    """Replace this queue row with a new AI brief (same slot)."""
    require_admin_http(request)
    api_key = _settings_openai_key()
    with get_db() as db:
        row = repo.get_writter_future_article(db, row_id)
        if not row:
            raise HTTPException(404, detail="Not found")
        if (row.status or "") == "done":
            raise HTTPException(400, detail="Already generated")
        existing = repo.list_blog_topics_and_titles(db)
        extra = [row.topic or ""] if row.topic else []
        brief = suggest_auto_article_brief(api_key, existing_topics=existing + extra)
        repo.update_writter_future_article(
            db,
            row,
            topic=brief["topic"],
            keywords=brief.get("keywords") or "",
            article_type=brief["article_type"],
            primary_goal=brief["primary_goal"],
            briefing_json={"rationale": brief.get("rationale") or ""},
        )
        item = repo.get_writter_future_article_dict(db, row_id)
    return JSONResponse({"item": item})


@router.post("/api/admin/writter/future-articles/{row_id}/generate")
async def api_future_generate(request: Request, row_id: int):
    """Generate and publish from an approved queue row (SEO overall ≥ 80, else draft)."""
    require_admin_http(request)
    user = get_current_user(request)
    email = (user.get("email") or "") if user else ""
    try:
        with get_db() as db:
            row = repo.get_writter_future_article(db, row_id)
            if not row:
                raise HTTPException(404, detail="Not found")
            if (row.status or "") != "approved":
                raise HTTPException(400, detail="Approve this queue item first")
            out = _generate_from_future_row(db, row, email)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=str(e)[:500])
    return JSONResponse(out)


@router.get("/api/admin/writter/articles")
async def api_list_articles(request: Request):
    require_admin_http(request)
    with get_db() as db:
        rows = repo.list_blog_articles_admin(db)
    return JSONResponse({"articles": rows})


@router.put("/api/admin/writter/articles/{article_id}")
async def api_update_article(request: Request, article_id: int, body: UpdateArticleBody):
    require_admin_http(request)
    user = get_current_user(request)
    email = (user.get("email") or "") if user else ""
    with get_db() as db:
        row = repo.get_blog_article_by_id(db, article_id)
        if not row:
            raise HTTPException(404, detail="Not found")
        if body.status == "published":
            metrics = _only_dict(row.metrics_json or {})
            blocked = publish_blocked_by_quality(metrics)
            if blocked:
                raise HTTPException(400, detail=blocked)
        if (body.version_note or "").strip():
            repo.add_blog_article_version(
                db,
                article_id=row.id,
                title=row.title or "",
                content_html=row.content_html or "",
                meta_description=row.meta_description or "",
                author_email=email,
                note=(body.version_note or "").strip(),
                change_summary=(body.change_summary or "").strip()[:255],
            )
        repo.update_blog_article(
            db,
            row,
            title=body.title,
            content_html=body.content_html,
            meta_description=body.meta_description,
            status=body.status,
        )
        out = repo.blog_article_to_dict(row)
    return JSONResponse(out)


@router.delete("/api/admin/writter/articles/{article_id}")
async def api_delete_article(request: Request, article_id: int):
    require_admin_http(request)
    with get_db() as db:
        ok = repo.delete_blog_article(db, article_id)
    if not ok:
        raise HTTPException(404, detail="Not found")
    return JSONResponse({"ok": True})


def _regenerate_article_by_id(article_id: int) -> Dict[str, Any]:
    """Re-run AI generation for an existing article (same slug, topic, type, rules)."""
    api_key = _settings_openai_key()
    with get_db() as db:
        row = repo.get_blog_article_by_id(db, article_id)
        if not row:
            raise HTTPException(404, detail="Not found")
        at = row.article_type
        if at not in VALID_ARTICLE_TYPES:
            raise HTTPException(400, detail="Invalid article type on record")
        settings = get_settings(db)
        type_prompt = get_writter_type_prompt(settings, at)
        siblings = repo.get_published_slugs_titles_excluding(db, exclude_slug=row.slug, limit=40)
        icount = len(siblings)
        plan = row.planning_json if isinstance(row.planning_json, dict) else {}
        inputs = plan.get("inputs") if isinstance(plan.get("inputs"), dict) else {}
        evidence_dict = plan.get("evidence") if isinstance(plan.get("evidence"), dict) else {}
        full_plan = plan.get("article_plan") if isinstance(plan.get("article_plan"), dict) else {}
        pg = str(inputs.get("primary_goal") or "organic_traffic").strip()
        if pg not in VALID_PRIMARY_GOALS:
            pg = "organic_traffic"
        opp = plan.get("opportunity") if isinstance(plan.get("opportunity"), dict) else None
        if not opp:
            opp = score_article_opportunity(
                topic=row.topic or "",
                keywords=row.keywords or "",
                article_type=at,
                primary_goal=pg,
                audience=str(inputs.get("audience") or ""),
                country_language=str(inputs.get("country_language") or ""),
                business_goal=str(inputs.get("business_goal") or ""),
                internal_article_count=icount,
            )
        opp_for_gen = dict(opp) if isinstance(opp, dict) else {}
        cta_dir = full_plan.get("cta_direction") if isinstance(full_plan, dict) else None
        if cta_dir:
            opp_for_gen["cta_direction"] = cta_dir
        outline_sections = plan.get("outline_sections")
        if not outline_sections and isinstance(full_plan, dict) and full_plan.get("blueprint_outline"):
            outline_sections = full_plan.get("blueprint_outline")
        if not outline_sections:
            outline_sections = build_outline_headings(at, row.topic or "")
        mode = str(inputs.get("generation_mode") or "standard").strip().lower()
        if mode not in ("fast", "standard", "authority"):
            mode = "standard"
        raw_sug = plan.get("internal_link_suggestions")
        link_sug = raw_sug if isinstance(raw_sug, list) else suggest_internal_link_placements(
            row.topic or "", row.keywords or "", siblings, limit=8
        )

        vm = str(inputs.get("visual_mode") or "auto").strip().lower()
        seed = int(inputs.get("visual_seed") or 0)
        vi = int(inputs.get("visual_index") or 0)
        layout = str(inputs.get("visual_layout") or "horizontal")
        vdesc = str(inputs.get("visual_description") or "").strip()
        if vm == "none":
            v: Dict[str, Any] = {"html": "", "label": ""}
            wrap = ""
        elif vm == "describe" and vdesc:
            cv = route_cheap_visual(vdesc, row.topic or "", row.keywords or "", seed=seed)
            v = {"html": cv.get("html") or "", "label": cv.get("label") or "Diagram"}
            wrap = f'<div class="writter-visual-wrap">{v["html"]}</div>' if v.get("html") else ""
        else:
            rv = full_plan.get("recommended_visual") if isinstance(full_plan, dict) else None
            if isinstance(rv, dict) and rv.get("layout"):
                layout = str(rv["layout"])
            visuals = build_visual_options(row.topic or "", row.keywords or "", seed=seed, layout=layout)
            pick = max(0, min(vi, len(visuals) - 1)) if visuals else 0
            v = visuals[pick] if visuals else {"html": "", "label": ""}
            wrap = f'<div class="writter-visual-wrap">{v["html"]}</div>' if v.get("html") else ""

        rules = row.rules_json if isinstance(row.rules_json, list) else []
        payload, metrics = generate_article_with_ai(
            api_key=api_key,
            article_type=at,
            topic=row.topic or "",
            keywords=row.keywords or "",
            rules=rules,
            internal_context=siblings,
            visual_label=v.get("label") or "",
            type_prompt_extra=type_prompt,
            generation_mode=mode,
            audience=str(inputs.get("audience") or ""),
            country_language=str(inputs.get("country_language") or ""),
            business_goal=str(inputs.get("business_goal") or ""),
            evidence=evidence_dict,
            opportunity_plan=opp_for_gen,
            internal_link_suggestions=link_sug,
            outline_sections=outline_sections if isinstance(outline_sections, list) else None,
        )
        inner = payload.get("content_html") or ""
        if wrap:
            full_html = wrap + inner
        else:
            full_html = inner
        full_html, used_links = inject_internal_links(full_html, siblings)
        h1 = (payload.get("h1") or row.topic or "").strip()
        metrics["seo_qa"] = run_seo_quality_audit(
            content_html=full_html,
            title=(payload.get("seo_title") or row.title or "")[:500],
            meta_description=payload.get("meta_description") or "",
            slug=row.slug or "",
            keywords=row.keywords or "",
            h1=h1,
        )
        sess = int(row.analytics_sessions or 0)
        metrics = _merge_metrics_with_admin_ai_insights(
            metrics,
            api_key=api_key,
            title=(payload.get("seo_title") or row.title or "")[:500],
            meta_description=payload.get("meta_description") or "",
            topic=row.topic or "",
            keywords=row.keywords or "",
            article_type=at,
            content_html=full_html,
            views=int(row.views or 0),
            sessions=sess,
            avg_time_s=(row.total_time_ms or 0) / max(sess, 1) / 1000.0,
            avg_scroll=(row.total_scroll_pct or 0.0) / max(sess, 1),
            cta_clicks=int(row.cta_clicks or 0),
            internal_links_n=len(used_links) if isinstance(used_links, list) else 0,
        )
        new_title = (payload.get("seo_title") or row.title or "")[:500]
        planning_json: Dict[str, Any] = {
            "inputs": {
                "topic": row.topic or "",
                "keywords": row.keywords or "",
                "article_type": at,
                "primary_goal": pg,
                "audience": str(inputs.get("audience") or ""),
                "country_language": str(inputs.get("country_language") or ""),
                "business_goal": str(inputs.get("business_goal") or ""),
                "generation_mode": mode,
                "visual_mode": str(inputs.get("visual_mode") or "auto"),
                "visual_description": str(inputs.get("visual_description") or ""),
                "visual_seed": int(inputs.get("visual_seed") or 0),
                "visual_index": int(inputs.get("visual_index") or 0),
                "visual_layout": str(inputs.get("visual_layout") or "horizontal"),
                "rule_presets": inputs.get("rule_presets") if isinstance(inputs.get("rule_presets"), list) else [],
            },
            "article_plan": plan.get("article_plan") if isinstance(plan.get("article_plan"), dict) else {},
            "outline_sections": outline_sections if isinstance(outline_sections, list) else [],
            "evidence": evidence_dict,
            "opportunity": opp,
            "internal_link_suggestions": link_sug,
        }
        repo.update_blog_article(
            db,
            row,
            title=new_title,
            content_html=full_html,
            meta_description=payload.get("meta_description") or "",
            structure_json=payload.get("structure_outline"),
            visual_html=v.get("html"),
            metrics_json=metrics,
            planning_json=planning_json,
            internal_links_json=used_links,
        )
        slug = row.slug
        rid = row.id
    return {"ok": True, "slug": slug, "id": rid}


@router.post("/api/admin/writter/articles/{article_id}/regenerate")
async def api_regenerate_article(request: Request, article_id: int):
    require_admin_http(request)
    try:
        out = _regenerate_article_by_id(article_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=str(e)[:500])
    return JSONResponse(out)


@router.get("/articles/{slug}")
async def api_public_article_json(slug: str):
    """Compatibility alias per spec GET /articles/{{slug}}."""
    with get_db() as db:
        row = repo.get_blog_article_by_slug(db, slug)
        if not row or row.status != "published":
            raise HTTPException(404, detail="Not found")
        data = repo.blog_article_to_dict(row)
    return JSONResponse(data)


def _blog_index_page_html(
    rows: List[Dict[str, Any]],
    q_raw: str,
    *,
    canonical_url: str,
    meta_desc: str,
    page_title: str,
    og_image: str,
    og_site_name: str,
) -> str:
    """Public blog listing with keyword search (matches title, topic, keywords, meta)."""
    q_esc = html_module.escape(q_raw)
    cards: List[str] = []
    for r in rows:
        slug = html_module.escape((r.get("slug") or "").strip())
        title = html_module.escape((r.get("title") or "Untitled").strip())
        meta = (r.get("meta_description") or "").strip()
        if len(meta) > 180:
            meta = meta[:177] + "…"
        meta_esc = html_module.escape(meta) if meta else ""
        kw = html_module.escape((r.get("keywords") or "").strip())
        pub = r.get("published_at") or r.get("created_at") or ""
        if isinstance(pub, str) and len(pub) > 10:
            date_esc = html_module.escape(pub[:10])
        else:
            date_esc = ""
        kw_line = f'<p class="blog-idx-card-kw">{kw}</p>' if kw else ""
        meta_line = f'<p class="blog-idx-card-meta">{meta_esc}</p>' if meta_esc else ""
        date_line = f'<time class="blog-idx-card-date" datetime="{date_esc}">{date_esc}</time>' if date_esc else ""
        cards.append(
            f"""<li class="blog-idx-card"><a class="blog-idx-card-link" href="/blog/{slug}">
  <h2 class="blog-idx-card-title">{title}</h2>
  {date_line}
  {meta_line}
  {kw_line}
</a></li>"""
        )
    if cards:
        cards_html = "\n".join(cards)
    elif q_raw.strip():
        cards_html = '<li class="blog-idx-empty">No articles match your search. <a href="/blog">Clear search</a></li>'
    else:
        cards_html = '<li class="blog-idx-empty">No published articles yet. Check back soon.</li>'
    seo_block = head_canonical_social(
        canonical_url=canonical_url,
        og_title=page_title,
        og_description=meta_desc,
        og_image=og_image,
        og_site_name=og_site_name,
        og_type="website",
    )
    title_esc = html_module.escape(page_title)
    meta_desc_esc = html_module.escape(meta_desc, quote=True)
    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title_esc}</title>
  <meta name="description" content="{meta_desc_esc}" />
  {seo_block}  <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
  <link rel="stylesheet" href="/static/styles.css" />
  <style>
  body {{ margin:0; font-family:Inter,system-ui,sans-serif; background:#0B0F19; color:#E5E7EB; min-height:100vh; }}
  [data-theme="light"] body {{ background:#f8fafc; color:#0f172a; }}
  .visually-hidden {{ position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }}
  .blog-idx-wrap {{ max-width:800px; margin:0 auto; padding:88px 24px 80px; }}
  .blog-idx-hero h1 {{ font-size:2rem; font-weight:700; letter-spacing:-.03em; margin:0 0 8px; }}
  .blog-idx-hero p {{ color:#94a3b8; margin:0 0 28px; font-size:1rem; line-height:1.5; }}
  .blog-idx-search {{ display:flex; gap:10px; flex-wrap:wrap; margin-bottom:36px; }}
  .blog-idx-search input[type="search"] {{ flex:1; min-width:200px; padding:12px 16px; border-radius:10px; border:1px solid rgba(255,255,255,.12); background:#111827; color:#E5E7EB; font-size:.95rem; box-sizing:border-box; }}
  [data-theme="light"] .blog-idx-search input[type="search"] {{ background:#fff; border-color:rgba(15,23,42,.15); color:#0f172a; }}
  .blog-idx-search button {{ padding:12px 22px; border-radius:10px; border:none; background:#4F46E5; color:#fff; font-weight:600; cursor:pointer; font-size:.95rem; }}
  .blog-idx-search button:hover {{ filter:brightness(1.06); }}
  .blog-idx-list {{ list-style:none; padding:0; margin:0; display:flex; flex-direction:column; gap:14px; }}
  .blog-idx-card {{ border-radius:14px; border:1px solid rgba(255,255,255,.08); background:rgba(17,24,39,.85); overflow:hidden; transition:border-color .15s, box-shadow .15s; }}
  [data-theme="light"] .blog-idx-card {{ background:#fff; border-color:rgba(15,23,42,.1); }}
  .blog-idx-card:hover {{ border-color:rgba(129,140,248,.35); box-shadow:0 8px 32px rgba(0,0,0,.2); }}
  .blog-idx-card-link {{ display:block; padding:22px 24px; text-decoration:none; color:inherit; }}
  .blog-idx-card-title {{ font-size:1.2rem; font-weight:600; margin:0 0 12px; line-height:1.35; color:#F1F5F9; }}
  [data-theme="light"] .blog-idx-card-title {{ color:#0f172a; }}
  .blog-idx-card-date {{ display:block; font-size:.78rem; color:#64748b; margin-bottom:10px; }}
  .blog-idx-card-meta {{ font-size:.9rem; color:#94a3b8; line-height:1.55; margin:0 0 8px; }}
  .blog-idx-card-kw {{ font-size:.78rem; color:#64748b; margin:0; }}
  .blog-idx-empty {{ padding:48px 24px; text-align:center; color:#94a3b8; border-radius:14px; border:1px dashed rgba(255,255,255,.12); }}
  .blog-idx-empty a {{ color:#818cf8; }}
  </style>
</head>
<body>
  {public_site_nav_html()}
  <div class="blog-page-with-nav">
  <main class="blog-idx-wrap">
    <header class="blog-idx-hero">
      <h1>Blog</h1>
      <p>Guides and tips on product feeds, Google Merchant Center, and growing your catalog visibility.</p>
      <form class="blog-idx-search" method="get" action="/blog" role="search">
        <label for="blogq" class="visually-hidden">Search articles by keywords</label>
        <input type="search" id="blogq" name="q" value="{q_esc}" placeholder="Search by keywords (title, topic, tags…)" autocomplete="off" />
        <button type="submit">Search</button>
      </form>
    </header>
    <ul class="blog-idx-list">{cards_html}</ul>
  </main>
  </div>
  <script>
  {ADMIN_THEME_SCRIPT.strip()}
  </script>
</body>
</html>"""


@router.get("/blog", response_class=HTMLResponse)
async def blog_index_page(request: Request, q: str = Query("", max_length=500)):
    """Public blog index: all published articles, optional keyword search."""
    q_clean = (q or "").strip()
    canonical_url = canonical_url_for_request(request)
    meta_desc = (
        "Articles and guides from Cartozo — product feed optimization, Google Merchant Center, and e-commerce SEO."
    )
    if q_clean:
        meta_desc = f'Search results for "{q_clean[:120]}" — Cartozo blog (feeds, Merchant Center, SEO).'
    page_title = "Blog — Cartozo.ai"
    if q_clean:
        page_title = f"Search: {q_clean[:40]}{'…' if len(q_clean) > 40 else ''} — Cartozo.ai"
    with get_db() as db:
        s = get_settings(db)
        og_image = (s.get("seo_og_image") or "").strip()
        og_site = (s.get("seo_og_site_name") or "").strip() or "Cartozo.ai"
        rows = repo.list_blog_articles_published_search(db, search=q_clean, limit=300)
    html = _blog_index_page_html(
        rows,
        q_clean,
        canonical_url=canonical_url,
        meta_desc=meta_desc,
        page_title=page_title,
        og_image=og_image,
        og_site_name=og_site,
    )
    return HTMLResponse(content=html)


@router.get("/blog/{slug}", response_class=HTMLResponse)
async def blog_public_page(request: Request, slug: str):
    """Public SEO article. Right-hand analytics panel only for logged-in admin."""
    show_admin = is_admin(request)
    with get_db() as db:
        row = repo.get_blog_article_by_slug(db, slug)
        if not row or row.status != "published":
            raise HTTPException(404, detail="Article not found")
        sidebar_rows = repo.list_blog_articles_published(db, limit=80)
        repo.increment_blog_views(db, slug)
        article_id = row.id
        title_esc = html_module.escape(row.title or "")
        meta_esc = html_module.escape((row.meta_description or "")[:300])
        content = row.content_html or ""
        views_ct = (row.views or 0) + 1
        metrics = _only_dict(row.metrics_json or {})
        m_imp = metrics.get("estimated_impressions", "—")
        m_ctr = metrics.get("estimated_ctr")
        m_clk = metrics.get("estimated_clicks", "—")
        m_conv = metrics.get("potential_conversions", "—")
        ctr_pct = "—"
        if m_ctr is not None:
            try:
                ctr_pct = f"{float(m_ctr) * 100:.2f}%"
            except (TypeError, ValueError):
                ctr_pct = str(m_ctr)
        sessions = int(row.analytics_sessions or 0)
        avg_time_s = (row.total_time_ms or 0) / max(sessions, 1) / 1000.0
        avg_scroll = (row.total_scroll_pct or 0.0) / max(sessions, 1)
        cta_n = int(row.cta_clicks or 0)
        links_n = len(row.internal_links_json) if isinstance(row.internal_links_json, list) else 0
        title_plain = row.title or ""
        meta_plain = row.meta_description or ""
        kw_plain = row.keywords or ""
        at_plain = row.article_type or ""
        topic_plain = row.topic or ""
        display_content = _strip_trailing_writter_cta_block(content)
        s_seo = get_settings(db)
        og_image = (s_seo.get("seo_og_image") or "").strip()
        og_site = (s_seo.get("seo_og_site_name") or "").strip() or "Cartozo.ai"
        # Materialize dates while session is open (avoid DetachedInstanceError on lazy refresh).
        ts_pub = row.published_at or row.created_at
        ts_mod = getattr(row, "updated_at", None) or ts_pub

    admin_aside = ""
    if show_admin:
        q = estimate_article_quality(
            title=title_plain,
            meta_description=meta_plain,
            content_html=display_content,
            keywords=kw_plain,
            internal_links_count=links_n,
        )
        insights = None
        cached_ai = metrics.get("admin_ai_insights")
        if _admin_ai_insights_valid(cached_ai):
            insights = cached_ai
        if insights:
            q_score = int(insights["quality_score"])
            q_label = html_module.escape(insights["quality_label"])
            q_color = html_module.escape(insights["quality_color"])
            sum_p = html_module.escape(insights.get("summary") or "")
            eng_p = html_module.escape(insights.get("engagement_analysis") or "")
            proj_p = html_module.escape(insights.get("projections_analysis") or "")
            rec_html = ""
            for r in insights.get("recommendations") or []:
                if isinstance(r, str) and r.strip():
                    rec_html += f"<li>{html_module.escape(r.strip())}</li>"
            hint_ai = ""
            for h in insights.get("hints") or []:
                if isinstance(h, str) and h.strip():
                    hint_ai += f"<li>{html_module.escape(h.strip())}</li>"
            ai_note = '<p class="bar-ai-note">Stored from the last full generation or regenerate; refreshing this page does not call the model again.</p>'
            quality_block = f"""
      <div class="bar-card bar-quality" style="border-color:{q_color};">
        <div class="bar-quality-row">
          <div class="bar-ring" style="--p:{q_score}; --c:{q_color};">
            <span>{q_score}</span>
          </div>
          <div>
            <div class="bar-qlabel" style="color:{q_color};">{q_label}</div>
            <div class="bar-qhint">AI quality assessment</div>
          </div>
        </div>
        <p class="bar-narr">{sum_p}</p>
        {ai_note}
      </div>"""
            engage_block = f"""
      <div class="bar-card">
        <h3 class="bar-h3">Live engagement</h3>
        <p class="bar-narr">{eng_p}</p>
        <dl class="bar-dl">
          <div><dt>Page views</dt><dd>{views_ct}</dd></div>
          <div><dt>Recorded sessions</dt><dd>{sessions}</dd></div>
          <div><dt>Avg. time on page</dt><dd>{avg_time_s:.1f}s</dd></div>
          <div><dt>Avg. scroll depth</dt><dd>{avg_scroll:.0f}%</dd></div>
          <div><dt>CTA clicks</dt><dd>{cta_n}</dd></div>
          <div><dt>Internal links</dt><dd>{links_n}</dd></div>
        </dl>
      </div>"""
            proj_block = f"""
      <div class="bar-card">
        <h3 class="bar-h3">Projected (at publish)</h3>
        <p class="bar-narr">{proj_p}</p>
        <dl class="bar-dl">
          <div><dt>Est. impressions</dt><dd>{html_module.escape(str(m_imp))}</dd></div>
          <div><dt>Est. CTR</dt><dd>{html_module.escape(ctr_pct)}</dd></div>
          <div><dt>Est. clicks</dt><dd>{html_module.escape(str(m_clk))}</dd></div>
          <div><dt>Potential conversions</dt><dd>{html_module.escape(str(m_conv))}</dd></div>
        </dl>
      </div>"""
            rec_block = ""
            if rec_html:
                rec_block = f'<div class="bar-card"><h3 class="bar-h3">Recommendations</h3><ul class="bar-hints">{rec_html}</ul></div>'
            hint_block = ""
            if hint_ai:
                hint_block = f'<div class="bar-card"><h3 class="bar-h3">Quick tips</h3><ul class="bar-hints">{hint_ai}</ul></div>'
        else:
            q_score = int(q["score"])
            q_label = html_module.escape(q["label"])
            q_color = html_module.escape(q.get("color") or "#94a3b8")
            hints_html = ""
            for h in q.get("hints") or []:
                hints_html += f"<li>{html_module.escape(h)}</li>"
            quality_block = f"""
      <div class="bar-card bar-quality" style="border-color:{q_color};">
        <div class="bar-quality-row">
          <div class="bar-ring" style="--p:{q_score}; --c:{q_color};">
            <span>{q_score}</span>
          </div>
          <div>
            <div class="bar-qlabel" style="color:{q_color};">{q_label}</div>
            <div class="bar-qhint">Heuristic score (add OpenAI key in Settings for AI insights)</div>
          </div>
        </div>
        <ul class="bar-hints">{hints_html}</ul>
      </div>"""
            engage_block = f"""
      <div class="bar-card">
        <h3 class="bar-h3">Live engagement</h3>
        <dl class="bar-dl">
          <div><dt>Page views</dt><dd>{views_ct}</dd></div>
          <div><dt>Recorded sessions</dt><dd>{sessions}</dd></div>
          <div><dt>Avg. time on page</dt><dd>{avg_time_s:.1f}s</dd></div>
          <div><dt>Avg. scroll depth</dt><dd>{avg_scroll:.0f}%</dd></div>
          <div><dt>CTA clicks</dt><dd>{cta_n}</dd></div>
          <div><dt>Internal links</dt><dd>{links_n}</dd></div>
        </dl>
      </div>"""
            proj_block = f"""
      <div class="bar-card">
        <h3 class="bar-h3">Projected (at publish)</h3>
        <dl class="bar-dl">
          <div><dt>Est. impressions</dt><dd>{html_module.escape(str(m_imp))}</dd></div>
          <div><dt>Est. CTR</dt><dd>{html_module.escape(ctr_pct)}</dd></div>
          <div><dt>Est. clicks</dt><dd>{html_module.escape(str(m_clk))}</dd></div>
          <div><dt>Potential conversions</dt><dd>{html_module.escape(str(m_conv))}</dd></div>
        </dl>
      </div>"""
            rec_block = ""
            hint_block = ""

        admin_aside = f"""
    <aside class="blog-admin-r" aria-label="Admin analytics">
      <div class="bar-card bar-head">
        <span class="bar-badge">Admin</span>
        <h2 class="bar-title">Insights</h2>
        <p class="bar-sub">Visible only to you · not shown to readers</p>
      </div>
      {quality_block}
      {engage_block}
      {proj_block}
      {rec_block}
      {hint_block}
      <div class="bar-card">
        <h3 class="bar-h3">Article</h3>
        <p class="bar-meta">Type: {html_module.escape(ARTICLE_TYPE_LABELS.get(at_plain, at_plain))}</p>
        <p class="bar-meta">Words (approx.): {q.get("word_count", "—")} · H2: {q.get("h2_count", "—")}</p>
        <div class="bar-actions">
          <button type="button" class="bar-btn bar-btn-primary" id="barRegen">Regenerate article</button>
          <a class="bar-btn bar-btn-ghost" href="/admin/writter/article/{article_id}/review">Open in Writter</a>
        </div>
        <p class="bar-foot" id="barRegenMsg"></p>
      </div>
    </aside>"""

    nav_li = ""
    for r in sidebar_rows:
        if r.get("status") != "published":
            continue
        s_esc = html_module.escape(r.get("slug") or "")
        t = html_module.escape(r.get("title") or "Untitled")
        is_active = (r.get("slug") or "") == slug
        li_cls = ' class="wt-sb-active"' if is_active else ""
        nav_li += f"<li{li_cls}><a href=\"/blog/{s_esc}\">{t}</a></li>"

    regen_script = ""
    if show_admin:
        regen_script = f"""
    var br = document.getElementById('barRegen');
    if (br) {{
      br.onclick = function() {{
        var msg = document.getElementById('barRegenMsg');
        br.disabled = true;
        if (msg) msg.textContent = 'Regenerating…';
        fetch('/api/admin/writter/articles/{article_id}/regenerate', {{ method: 'POST', credentials: 'same-origin' }})
          .then(function(r) {{ if (!r.ok) return r.text().then(function(t) {{ throw new Error(t); }}); return r.json(); }})
          .then(function() {{ location.reload(); }})
          .catch(function(e) {{ if (msg) msg.textContent = e.message || 'Failed'; br.disabled = false; }});
      }};
    }}"""

    subtitle_block = _blog_public_subtitle_html(meta_plain, title_plain)
    _bc = (title_plain or "").strip()
    if len(_bc) > 72:
        _bc = _bc[:69] + "…"
    breadcrumb_title_esc = html_module.escape(_bc)
    blog_body = display_content if isinstance(display_content, str) else str(display_content or "")
    article_url = canonical_url_blog_article(slug)
    og_desc_for_social = ((meta_plain or "").strip()[:500]) or ((title_plain or "").strip()[:160])
    article_seo = head_canonical_social(
        canonical_url=article_url,
        og_title=(title_plain or "Article") + " — Cartozo.ai",
        og_description=og_desc_for_social,
        og_image=og_image,
        og_site_name=og_site,
        og_type="article",
    )
    ld = blog_posting_json_ld(
        headline=title_plain or "",
        url=article_url,
        description=meta_plain or "",
        date_published=str(ts_pub) if ts_pub else "",
        date_modified=str(ts_mod) if ts_mod else None,
    )
    html = (
        f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title_esc} — Cartozo.ai</title>
  <meta name="description" content="{meta_esc}" />
  {article_seo}{ld}  <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
  <link rel="stylesheet" href="/static/styles.css" />
  <style>
  body {{ margin:0; font-family:Inter,system-ui,sans-serif; background:#0B0F19; color:#E5E7EB; min-height:100vh; }}
  [data-theme="light"] body {{ background:#f8fafc; color:#0f172a; }}
  body.blog-article-body {{ color:#e2e8f0; }}
  [data-theme="light"] body.blog-article-body {{ color:#0f172a; }}
  .blog-layout {{ display:flex; min-height:100vh; width:100%; }}
  .blog-side {{ width:260px; flex-shrink:0; border-right:1px solid rgba(255,255,255,.08); padding:12px 16px 24px; position:sticky; top:72px; align-self:flex-start; max-height:calc(100vh - 72px); overflow-y:auto; }}
  [data-theme="light"] .blog-side {{ border-color:rgba(15,23,42,.1); }}
  .blog-side h2 {{ font-size:.75rem; text-transform:uppercase; letter-spacing:.08em; color:#64748b; margin:0 0 12px; }}
  .blog-side ul {{ list-style:none; padding:0; margin:0; }}
  .blog-side li {{ margin-bottom:6px; }}
  .blog-side a {{ color:#94a3b8; text-decoration:none; font-size:.88rem; line-height:1.35; display:block; padding:8px 10px; border-radius:8px; transition:color .15s, background .15s, transform .12s; }}
  .blog-side a:hover {{ color:#E5E7EB; background:rgba(255,255,255,.08); transform:translateX(2px); }}
  .blog-side li.wt-sb-active a {{ color:#a5b4fc; font-weight:600; background:rgba(79,70,229,.18); border:1px solid rgba(129,140,248,.25); }}
  [data-theme="light"] .blog-side a {{ color:#475569; }}
  [data-theme="light"] .blog-side li.wt-sb-active a {{ color:#4338ca; background:rgba(79,70,229,.1); border-color:rgba(79,70,229,.2); }}
  .blog-center {{ flex:1; min-width:0; padding:clamp(10px,2.5vw,20px) clamp(16px,4vw,40px) 80px; margin-inline:auto; }}
  .writter-cta a, .blog-main .writter-cta a {{ color:#4F46E5; font-weight:600; }}
  .blog-admin-r {{ width:320px; flex-shrink:0; padding:16px 20px 48px; border-left:1px solid rgba(255,255,255,.08); position:sticky; top:72px; align-self:flex-start; max-height:calc(100vh - 72px); overflow-y:auto; background:linear-gradient(180deg, rgba(79,70,229,.06) 0%, transparent 120px); }}
  [data-theme="light"] .blog-admin-r {{ border-color:rgba(15,23,42,.1); background:linear-gradient(180deg, rgba(79,70,229,.04) 0%, transparent 120px); }}
  .bar-card {{ background:rgba(17,24,39,.85); border:1px solid rgba(255,255,255,.08); border-radius:14px; padding:16px 18px; margin-bottom:14px; }}
  [data-theme="light"] .bar-card {{ background:#fff; border-color:rgba(15,23,42,.1); }}
  .bar-head .bar-title {{ margin:6px 0 4px; font-size:1.05rem; }}
  .bar-sub {{ margin:0; font-size:.78rem; color:#64748b; }}
  .bar-badge {{ font-size:.65rem; font-weight:700; letter-spacing:.1em; color:#a78bfa; }}
  .bar-quality {{ border-width:2px; }}
  .bar-quality-row {{ display:flex; gap:14px; align-items:center; }}
  .bar-ring {{ width:64px; height:64px; border-radius:50%; background:conic-gradient(var(--c, #6366f1) calc(var(--p, 0) * 1%), rgba(255,255,255,.08) 0); display:flex; align-items:center; justify-content:center; flex-shrink:0; }}
  .bar-ring span {{ width:48px; height:48px; border-radius:50%; background:#111827; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:1.1rem; }}
  [data-theme="light"] .bar-ring span {{ background:#fff; }}
  .bar-qlabel {{ font-weight:700; font-size:1rem; }}
  .bar-qhint {{ font-size:.75rem; color:#64748b; margin-top:4px; max-width:200px; }}
  .bar-hints {{ margin:12px 0 0; padding-left:18px; font-size:.8rem; color:#94a3b8; line-height:1.45; }}
  .bar-h3 {{ margin:0 0 10px; font-size:.72rem; text-transform:uppercase; letter-spacing:.08em; color:#64748b; }}
  .bar-narr {{ font-size:0.88rem; color:#94a3b8; line-height:1.55; margin:0 0 12px; }}
  [data-theme="light"] .bar-narr {{ color:#475569; }}
  .bar-ai-note {{ font-size:0.72rem; color:#64748b; margin:12px 0 0; padding-top:10px; border-top:1px solid rgba(255,255,255,.08); }}
  [data-theme="light"] .bar-ai-note {{ border-top-color:rgba(15,23,42,.1); }}
  .bar-dl {{ margin:0; }}
  .bar-dl > div {{ display:flex; justify-content:space-between; gap:12px; padding:6px 0; border-bottom:1px solid rgba(255,255,255,.06); font-size:.88rem; }}
  .bar-dl > div:last-child {{ border-bottom:none; }}
  .bar-dl dt {{ color:#94a3b8; font-weight:400; }}
  .bar-dl dd {{ margin:0; font-weight:600; font-variant-numeric:tabular-nums; }}
  .bar-meta {{ font-size:.82rem; color:#94a3b8; margin:0 0 6px; }}
  .bar-actions {{ display:flex; flex-direction:column; gap:8px; margin-top:12px; }}
  .bar-btn {{ display:inline-flex; align-items:center; justify-content:center; padding:10px 14px; border-radius:10px; font-size:.85rem; font-weight:600; text-decoration:none; border:none; cursor:pointer; text-align:center; }}
  .bar-btn-primary {{ background:#4F46E5; color:#fff; }}
  .bar-btn-primary:disabled {{ opacity:.55; cursor:not-allowed; }}
  .bar-btn-ghost {{ background:transparent; border:1px solid rgba(255,255,255,.15); color:#e5e7eb; }}
  [data-theme="light"] .bar-btn-ghost {{ border-color:rgba(15,23,42,.2); color:#334155; }}
  .bar-foot {{ font-size:.78rem; color:#f87171; margin:8px 0 0; min-height:1.2em; }}
  @media (max-width:1100px) {{
    .blog-layout {{ flex-wrap:wrap; }}
    .blog-side {{ width:100%; position:relative; max-height:none; border-right:none; border-bottom:1px solid rgba(255,255,255,.08); }}
    .blog-center {{ max-width:100%; }}
    .blog-admin-r {{ width:100%; border-left:none; border-top:1px solid rgba(255,255,255,.08); position:relative; max-height:none; }}
  }}
  </style>
</head>
<body class="blog-article-body">
  {public_site_nav_html()}
  <div class="blog-page-with-nav">
  <div class="blog-layout">
    <aside class="blog-side">
      <h2 style="font-size:.75rem;"><a href="/blog" style="color:inherit;text-decoration:none;">Articles</a></h2>
      <ul>{nav_li}</ul>
    </aside>
    <article class="blog-main blog-center blog-article-page">
      <div class="blog-article-page-grid">
        <div class="blog-article-head-slot">
          <nav class="blog-breadcrumbs" aria-label="Breadcrumb">
            <ol class="blog-breadcrumbs-list">
              <li class="blog-breadcrumbs-item"><a href="/blog">Blog</a></li>
              <li class="blog-breadcrumbs-sep" aria-hidden="true">/</li>
              <li class="blog-breadcrumbs-item blog-breadcrumbs-current" aria-current="page">{breadcrumb_title_esc}</li>
            </ol>
          </nav>
          <header class="blog-article-header">
            <h1 class="blog-article-title">{title_esc}</h1>
            {subtitle_block}
          </header>
        </div>
        <nav class="blog-toc" id="blogToc" aria-label="On this page">
          <p class="blog-toc-label">On this page</p>
          <ol class="blog-toc-list" id="blogTocList"></ol>
        </nav>
        <div class="blog-article-primary">
          <template id="blog-mid-cta-template">
            <section class="blog-article-mid-cta writter-cta" aria-labelledby="blog-mid-cta-title">
              <div class="blog-article-mid-cta-inner">
                <h3 id="blog-mid-cta-title" class="blog-article-mid-cta-head">Fix your product feed automatically</h3>
                <p class="blog-article-mid-cta-lead">From raw CSV to Shopping-ready listings—search intents scored and assembled, not a blind rewrite.</p>
                <ol class="blog-article-mid-cta-steps" aria-label="How it works">
                  <li>Upload your CSV</li>
                  <li>Detect feed issues</li>
                  <li>Position titles &amp; descriptions on intents</li>
                  <li>Push to Google Merchant Center</li>
                </ol>
                <a href="/upload" class="blog-article-mid-cta-btn"><span class="blog-article-mid-cta-btn-label">Upload your feed</span></a>
              </div>
            </section>
          </template>
          <div class="article-content content writter-article" id="blogArticleContent">"""
        + blog_body
        + f"""</div>
          {_blog_article_end_cta_html()}
        </div>
      </div>
    </article>
    {admin_aside}
  </div>
  </div>
  <script>
  {ADMIN_THEME_SCRIPT.strip()}
  (function(){{
    var start = Date.now();
    var maxScroll = 0;
    window.addEventListener('scroll', function() {{
      var p = window.scrollY / (document.body.scrollHeight - window.innerHeight + 1);
      maxScroll = Math.max(maxScroll, Math.min(100, Math.round(p * 100)));
    }}, {{ passive: true }});
    window.addEventListener('beforeunload', function() {{
      var t = Date.now() - start;
      navigator.sendBeacon('/api/blog/{html_module.escape(slug)}/analytics', new Blob([JSON.stringify({{ time_ms: t, scroll_pct: maxScroll, cta_click: false }})], {{ type: 'application/json' }}));
    }});
    document.addEventListener('click', function(ev) {{
      var a = ev.target && ev.target.closest && ev.target.closest('.writter-cta a[href]');
      if (!a) return;
      fetch('/api/blog/{html_module.escape(slug)}/analytics', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        credentials: 'same-origin',
        body: JSON.stringify({{ cta_click: true }})
      }});
    }}, false);
  }})();
  (function(){{
    var root = document.getElementById('blogArticleContent');
    if (!root) return;
    function slugify(t) {{
      var s = (t || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
      return s || 'section';
    }}
    var h2s = root.querySelectorAll('h2');
    var tocNav = document.getElementById('blogToc');
    var tocList = document.getElementById('blogTocList');
    if (tocList && h2s.length) {{
      h2s.forEach(function(h, i) {{
        var id = h.id || ('blog-h-' + i + '-' + slugify(h.textContent));
        if (!h.id) h.id = id;
        var li = document.createElement('li');
        var a = document.createElement('a');
        a.href = '#' + id;
        a.textContent = h.textContent.trim();
        li.appendChild(a);
        tocList.appendChild(li);
      }});
      var links = tocList.querySelectorAll('a');
      function pickActive() {{
        var y = window.scrollY + 110;
        var cur = null;
        h2s.forEach(function(h) {{
          var top = h.getBoundingClientRect().top + window.scrollY;
          if (top <= y) cur = h.id;
        }});
        if (!cur && h2s.length) cur = h2s[0].id;
        links.forEach(function(a) {{
          a.classList.toggle('blog-toc-active', (a.getAttribute('href') || '') === '#' + cur);
        }});
      }}
      window.addEventListener('scroll', pickActive, {{ passive: true }});
      pickActive();
    }} else if (tocNav) {{
      tocNav.setAttribute('hidden', '');
    }}
    var tmpl = document.getElementById('blog-mid-cta-template');
    if (tmpl && h2s.length >= 2) {{
      var ins = tmpl.content.cloneNode(true);
      h2s[1].parentNode.insertBefore(ins, h2s[1]);
    }}
  }})();
  {regen_script}
  </script>
</body>
</html>"""
    )
    return HTMLResponse(content=html)


@router.post("/api/blog/{slug}/analytics")
async def blog_analytics(request: Request, slug: str, body: AnalyticsBody):
    """Beacon-friendly: no auth required; validates slug exists."""
    with get_db() as db:
        row = repo.get_blog_article_by_slug(db, slug)
        if not row or row.status != "published":
            raise HTTPException(404, detail="Not found")
        repo.record_blog_analytics(
            db,
            slug,
            time_ms=body.time_ms,
            scroll_pct=body.scroll_pct,
            cta_click=body.cta_click,
        )
    return JSONResponse({"ok": True})


@router.get("/admin/writter/clusters", response_class=HTMLResponse)
async def writter_clusters_page(request: Request):
    redir = require_admin_redirect(request, "/admin/writter/clusters")
    if redir:
        return redir
    with get_db() as db:
        clusters = repo.list_content_clusters(db)
    rows = ""
    for c in clusters:
        cid = int(c.get("id") or 0)
        rows += f"""<tr><td>{html_module.escape(c.get("name") or "")}</td><td><code>{html_module.escape(c.get("slug") or "")}</code></td>
<td><a href="/api/admin/writter/clusters/{cid}/articles" target="_blank" rel="noopener">JSON</a></td></tr>"""
    if not rows:
        rows = '<tr><td colspan="3" class="wt-empty">No clusters yet.</td></tr>'
    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Clusters — Writter</title>
<script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
<link rel="stylesheet" href="/static/styles.css" />
<style>
body{{margin:0;font-family:Inter,system-ui,sans-serif;background:#0B0F19;color:#E5E7EB;min-height:100vh;}}
.wt-main{{max-width:720px;margin:0 auto;padding:32px 24px;}}
.wt-btn{{padding:10px 18px;border-radius:8px;background:#4F46E5;color:#fff;border:none;font-weight:600;cursor:pointer;}}
label{{display:block;font-size:.75rem;color:#9ca3af;margin:12px 0 6px;text-transform:uppercase;}}
input{{width:100%;padding:10px;border-radius:8px;border:1px solid rgba(255,255,255,.12);background:#111827;color:#e5e7eb;box-sizing:border-box;}}
table{{width:100%;border-collapse:collapse;margin-top:24px;font-size:.9rem;}}
th,td{{padding:10px;border-bottom:1px solid rgba(255,255,255,.08);text-align:left;}}
.wt-empty{{color:#64748b;padding:20px;}}
.err{{color:#f87171;margin-top:8px;}}
</style></head>
<body>
{admin_top_nav_html("writter")}
<div class="wt-main">
<h1 style="margin:0 0 8px;">Content clusters</h1>
<p style="color:#94a3b8;margin:0 0 20px;">Group pillar + supporting articles for topical authority.</p>
<form id="cf">
<label>Name</label><input name="name" id="cname" required placeholder="e.g. Product feed optimization" />
<label>Slug (optional)</label><input name="slug" id="cslug" placeholder="auto from name if empty" />
<label>Description</label><input name="description" id="cdesc" />
<button type="submit" class="wt-btn" style="margin-top:16px;">Create cluster</button>
<p class="err" id="cerr"></p>
</form>
<table><thead><tr><th>Name</th><th>Slug</th><th>Articles</th></tr></thead><tbody>{rows}</tbody></table>
<p style="margin-top:24px;"><a href="/admin/writter">← Writter</a></p>
</div>
<script>
document.getElementById('cf').onsubmit=function(e){{e.preventDefault();
fetch('/api/admin/writter/clusters',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json'}},
body:JSON.stringify({{name:document.getElementById('cname').value,slug:document.getElementById('cslug').value,description:document.getElementById('cdesc').value}})}}).then(r=>{{if(!r.ok)return r.text().then(t=>{{throw new Error(t)}});return r.json();}}).then(()=>location.reload()).catch(err=>{{document.getElementById('cerr').textContent=err.message||'Failed';}});
}};
{ADMIN_THEME_SCRIPT.strip()}
</script>
</body></html>"""
    return HTMLResponse(content=html)


@router.get("/api/admin/writter/clusters", response_class=JSONResponse)
async def api_list_clusters(request: Request):
    require_admin_http(request)
    with get_db() as db:
        return JSONResponse({"clusters": repo.list_content_clusters(db)})


@router.post("/api/admin/writter/clusters")
async def api_create_cluster(request: Request, body: ClusterCreateBody):
    require_admin_http(request)
    with get_db() as db:
        row = repo.create_content_cluster(db, slug=body.slug or body.name, name=body.name, description=body.description)
        db.flush()
        cid = row.id
    return JSONResponse({"id": cid, "slug": row.slug, "name": row.name})


@router.get("/api/admin/writter/clusters/{cluster_id}/articles")
async def api_cluster_articles(request: Request, cluster_id: int):
    require_admin_http(request)
    with get_db() as db:
        arts = repo.list_articles_in_cluster(db, cluster_id)
    return JSONResponse({"articles": arts})


@router.put("/api/admin/writter/articles/{article_id}/cluster")
async def api_set_article_cluster(request: Request, article_id: int, body: ArticleClusterBody):
    require_admin_http(request)
    with get_db() as db:
        row = repo.get_blog_article_by_id(db, article_id)
        if not row:
            raise HTTPException(404, detail="Not found")
        if body.cluster_id is not None:
            c = repo.get_content_cluster_by_id(db, body.cluster_id)
            if not c:
                raise HTTPException(400, detail="Invalid cluster_id")
        repo.update_blog_article(
            db,
            row,
            cluster_id=body.cluster_id,
            cluster_role=body.cluster_role or "supporting",
        )
        out = repo.blog_article_to_dict(row)
    return JSONResponse(out)


@router.get("/api/admin/writter/articles/{article_id}/versions")
async def api_article_versions(request: Request, article_id: int):
    require_admin_http(request)
    with get_db() as db:
        row = repo.get_blog_article_by_id(db, article_id)
        if not row:
            raise HTTPException(404, detail="Not found")
        vers = repo.list_blog_article_versions(db, article_id)
    return JSONResponse({"versions": vers})


@router.post("/api/admin/writter/articles/{article_id}/restore-version")
async def api_restore_version(request: Request, article_id: int, body: RestoreVersionBody):
    require_admin_http(request)
    user = get_current_user(request)
    email = (user.get("email") or "") if user else ""
    with get_db() as db:
        row = repo.get_blog_article_by_id(db, article_id)
        if not row:
            raise HTTPException(404, detail="Not found")
        ver = repo.get_blog_article_version_full(db, body.version_id)
        if not ver or ver.article_id != article_id:
            raise HTTPException(404, detail="Version not found")
        repo.add_blog_article_version(
            db,
            article_id=article_id,
            title=row.title or "",
            content_html=row.content_html or "",
            meta_description=row.meta_description or "",
            author_email=email,
            note="Before restore",
            change_summary=f"restore from v{body.version_id}",
        )
        repo.update_blog_article(
            db,
            row,
            title=ver.title,
            content_html=ver.content_html,
            meta_description=ver.meta_description or "",
        )
        out = repo.blog_article_to_dict(row)
    return JSONResponse(out)


@router.get("/api/admin/writter/cheap-visual")
async def api_cheap_visual(request: Request, description: str = "", topic: str = "", keywords: str = "", seed: int = 0):
    require_admin_http(request)
    out = route_cheap_visual(description, topic, keywords, seed=seed)
    return JSONResponse(out)


@router.post("/api/admin/writter/cheap-visual")
async def api_cheap_visual_post(request: Request, body: CheapVisualBody):
    require_admin_http(request)
    out = route_cheap_visual(body.description, body.topic, body.keywords, seed=body.seed)
    return JSONResponse(out)


@router.post("/api/admin/writter/articles/{article_id}/ctr-variants")
async def api_ctr_variants(request: Request, article_id: int):
    require_admin_http(request)
    api_key = _settings_openai_key()
    with get_db() as db:
        row = repo.get_blog_article_by_id(db, article_id)
        if not row:
            raise HTTPException(404, detail="Not found")
        plain = re.sub(r"<[^>]+>", " ", row.content_html or "")
        plain = re.sub(r"\s+", " ", plain).strip()[:4000]
        ctr = generate_ctr_variants(
            api_key,
            title=row.title or "",
            meta_description=row.meta_description or "",
            topic=row.topic or "",
            keywords=row.keywords or "",
            content_excerpt=plain,
        )
        if not ctr:
            raise HTTPException(503, detail="CTR variants unavailable (check OpenAI key)")
        m = row.metrics_json if isinstance(row.metrics_json, dict) else {}
        m = dict(m)
        m["ctr_variants"] = ctr
        repo.update_blog_article(db, row, metrics_json=m)
        out = repo.blog_article_to_dict(row)
    return JSONResponse({"article": out, "ctr_variants": ctr})


@router.post("/api/admin/writter/articles/{article_id}/refresh")
async def api_refresh_article(request: Request, article_id: int, body: RefreshActionBody):
    require_admin_http(request)
    api_key = _settings_openai_key()
    action = (body.action or "").strip().lower()
    with get_db() as db:
        row = repo.get_blog_article_by_id(db, article_id)
        if not row:
            raise HTTPException(404, detail="Not found")
        settings = get_settings(db)
        type_prompt = get_writter_type_prompt(settings, row.article_type or "informational")
        patches = refresh_article_partial(
            api_key,
            action=action,
            article_type=row.article_type or "",
            topic=row.topic or "",
            keywords=row.keywords or "",
            title=row.title or "",
            meta_description=row.meta_description or "",
            content_html=row.content_html or "",
            type_prompt_extra=type_prompt,
        )
        if not patches:
            raise HTTPException(503, detail="Refresh failed (OpenAI or invalid action)")
        new_title = row.title
        new_meta = row.meta_description or ""
        new_html = row.content_html or ""
        if action == "title":
            if patches.get("seo_title"):
                new_title = patches["seo_title"][:500]
            if patches.get("meta_description"):
                new_meta = patches["meta_description"][:2000]
        elif action == "intro":
            new_html = _merge_refresh_html("intro", new_html, patches)
        elif action == "clarity":
            new_html = patches.get("content_html") or new_html
        elif action in ("cta", "faq", "evidence"):
            new_html = _merge_refresh_html(action, new_html, patches)
        repo.update_blog_article(db, row, title=new_title, content_html=new_html, meta_description=new_meta)
        if row.status == "published":
            metrics = _only_dict(row.metrics_json or {})
            seo_qa = run_seo_quality_audit(
                content_html=new_html,
                title=new_title,
                meta_description=new_meta,
                slug=row.slug or "",
                keywords=row.keywords or "",
                h1=new_title,
            )
            m2 = dict(metrics)
            m2["seo_qa"] = seo_qa
            repo.update_blog_article(db, row, metrics_json=m2)
        out = repo.blog_article_to_dict(row)
    return JSONResponse({"article": out, "patches": patches})


@router.post("/api/admin/writter/articles/{article_id}/conversion-blocks")
async def api_conversion_blocks(request: Request, article_id: int):
    require_admin_http(request)
    with get_db() as db:
        row = repo.get_blog_article_by_id(db, article_id)
        if not row:
            raise HTTPException(404, detail="Not found")
        block = conversion_blocks_html()
        new_html = (row.content_html or "") + "\n" + block
        repo.update_blog_article(db, row, content_html=new_html)
        out = repo.blog_article_to_dict(row)
    return JSONResponse({"article": out})


@router.post("/api/admin/writter/articles/{article_id}/gsc")
async def api_import_gsc(request: Request, article_id: int, body: GscImportBody):
    require_admin_http(request)
    with get_db() as db:
        row = repo.get_blog_article_by_id(db, article_id)
        if not row:
            raise HTTPException(404, detail="Not found")
        gsc = {
            "impressions": body.impressions,
            "clicks": body.clicks,
            "ctr": body.ctr,
            "avg_position": body.avg_position,
            "queries": body.queries[:50],
            "imported_at": datetime.now(timezone.utc).isoformat(),
        }
        suggestions = gsc_feedback_suggestions(gsc)
        m = row.metrics_json if isinstance(row.metrics_json, dict) else {}
        m = dict(m)
        m["gsc"] = gsc
        m["gsc_suggestions"] = suggestions
        repo.update_blog_article(db, row, metrics_json=m)
        out = repo.blog_article_to_dict(row)
    return JSONResponse({"article": out, "gsc_suggestions": suggestions})


@router.put("/api/admin/writter/articles/{article_id}/refresh-status")
async def api_refresh_status(request: Request, article_id: int):
    require_admin_http(request)
    data = await request.json()
    st = (data.get("writter_refresh_status") or "").strip() or None
    with get_db() as db:
        row = repo.get_blog_article_by_id(db, article_id)
        if not row:
            raise HTTPException(404, detail="Not found")
        repo.update_blog_article(db, row, writter_refresh_status=st)
        out = repo.blog_article_to_dict(row)
    return JSONResponse(out)


@router.get("/admin/writter/article/{article_id}/edit", response_class=HTMLResponse)
async def writter_article_editor(request: Request, article_id: int):
    redir = require_admin_redirect(request, f"/admin/writter/article/{article_id}/edit")
    if redir:
        return redir
    with get_db() as db:
        row = repo.get_blog_article_by_id(db, article_id)
        if not row:
            return _writter_article_missing_html(article_id)
        art = repo.blog_article_to_dict(row)
    title_esc = html_module.escape(art.get("title") or "")
    meta_esc = html_module.escape(art.get("meta_description") or "")
    content_json = _json_literal_for_script(art.get("content_html") or "")
    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Edit — {title_esc} — Writter</title>
<script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
<link rel="stylesheet" href="/static/styles.css" />
<style>
body{{margin:0;font-family:Inter,system-ui,sans-serif;background:#0B0F19;color:#E5E7EB;min-height:100vh;}}
.wt-main{{max-width:960px;margin:0 auto;padding:32px 24px 80px;}}
label{{display:block;font-size:.75rem;color:#9ca3af;margin:12px 0 6px;}}
input,textarea{{width:100%;padding:12px;border-radius:8px;border:1px solid rgba(255,255,255,.12);background:#111827;color:#e5e7eb;box-sizing:border-box;font-family:ui-monospace,Menlo,monospace;font-size:.85rem;}}
textarea#ch{{min-height:420px;}}
.wt-btn{{padding:10px 18px;border-radius:8px;background:#4F46E5;color:#fff;border:none;font-weight:600;cursor:pointer;margin-right:8px;}}
.err{{color:#f87171;margin-top:8px;}}
</style></head>
<body>
{admin_top_nav_html("writter")}
<div class="wt-main">
<p><a href="/admin/writter/article/{article_id}/review" style="color:#94a3b8;">← Review</a></p>
<h1 style="font-size:1.35rem;">Edit article</h1>
<form id="ef">
<label>Title</label>
<input name="title" id="title" value="{title_esc}" />
<label>Meta description</label>
<input name="meta_description" id="meta" value="{meta_esc}" />
<label>HTML body</label>
<textarea name="content_html" id="ch"></textarea>
<label>Version note (optional — saves snapshot before apply)</label>
<input name="version_note" id="vnote" placeholder="e.g. Before CTA tweak" />
<button type="submit" class="wt-btn">Save</button>
<a class="wt-btn" style="background:#334155;text-decoration:none;display:inline-flex;" href="/admin/writter/article/{article_id}/review">Cancel</a>
<p class="err" id="eerr"></p>
</form>
</div>
<script>
(function(){{var raw={content_json};document.getElementById('ch').value=raw;}})();
document.getElementById('ef').onsubmit=function(e){{e.preventDefault();
fetch('/api/admin/writter/articles/{article_id}',{{method:'PUT',credentials:'same-origin',headers:{{'Content-Type':'application/json'}},
body:JSON.stringify({{title:document.getElementById('title').value,content_html:document.getElementById('ch').value,meta_description:document.getElementById('meta').value,version_note:document.getElementById('vnote').value,change_summary:'editor save'}})}}).then(r=>{{if(!r.ok)return r.text().then(t=>{{throw new Error(t)}});return r.json();}}).then(()=>location.href='/admin/writter/article/{article_id}/review').catch(err=>{{document.getElementById('eerr').textContent=err.message||'Failed';}});
}};
{ADMIN_THEME_SCRIPT.strip()}
</script>
</body></html>"""
    return HTMLResponse(content=html)


def register_writter_routes(app) -> None:
    app.include_router(router)
