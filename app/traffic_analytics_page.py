"""Admin traffic analytics dashboard — humans vs bots, referrers, top pages."""
from __future__ import annotations

import html as html_module

from fastapi import Request
from fastapi.responses import HTMLResponse

from .admin_nav import ADMIN_MERCHANT_SCRIPT, ADMIN_THEME_SCRIPT, admin_top_nav_html
from .auth import require_admin_redirect
from .gtm import gtm_body_for_path, gtm_head_for_path


def build_traffic_analytics_page(request: Request, *, days: int, visitor_class: str) -> HTMLResponse:
    from .db import get_db
    from .services.db_repository import get_traffic_analytics_summary, list_recent_site_visits

    redir = require_admin_redirect(request, "/admin/traffic-analytics")
    if redir:
        return redir

    days = max(1, min(int(days or 7), 90))
    with get_db() as db:
        summary = get_traffic_analytics_summary(db, days=days)
        recent = list_recent_site_visits(db, days=days, visitor_class=visitor_class, limit=80)

    def esc(s: str) -> str:
        return html_module.escape(s or "")

    def hbar_rows(items: list[dict], label_key: str, count_key: str = "count", vmax: int = 0) -> str:
        if not items:
            return '<div class="ta-empty">No data in this period yet.</div>'
        mx = vmax or max((int(x.get(count_key, 0)) for x in items), default=1)
        out = ""
        colors = ["#4F46E5", "#22D3EE", "#A78BFA", "#6366f1", "#06b6d4"]
        for i, it in enumerate(items):
            label = esc(str(it.get(label_key, "")))
            c = int(it.get(count_key, 0))
            pct = min(100, round(100 * c / mx)) if mx else 0
            col = colors[i % len(colors)]
            out += (
                f'<div class="ta-hbar-row"><span class="ta-hbar-label">{label}</span>'
                f'<div class="ta-hbar-track"><div class="ta-hbar-fill" style="width:{pct}%;background:{col}"></div></div>'
                f'<span class="ta-hbar-num">{c}</span></div>'
            )
        return out

    class_rows = ""
    labels = {
        "human": "People (browsers)",
        "search_bot": "Search crawlers",
        "ai_bot": "AI search bots",
        "training_bot": "Training / Common Crawl",
        "monitor": "Monitors",
        "unknown_bot": "Other bots",
    }
    for key, label in labels.items():
        cnt = summary["by_class"].get(key, 0)
        if cnt:
            class_rows += f"<tr><td>{esc(label)}</td><td>{cnt}</td></tr>"
    if not class_rows:
        class_rows = '<tr><td colspan="2" class="ta-empty">No visits recorded yet. Browse public pages to populate data.</td></tr>'

    recent_rows = ""
    for r in recent:
        vc = r.get("visitor_class") or ""
        badge = "ta-badge-human" if vc == "human" else "ta-badge-bot"
        who = "Human" if vc == "human" else esc(r.get("bot_name") or labels.get(vc, vc))
        recent_rows += f"""<tr>
          <td class="ta-mono">{esc(r.get('viewed_at','')[:19].replace('T',' '))}</td>
          <td class="ta-mono">{esc(r.get('path',''))}</td>
          <td><span class="ta-badge {badge}">{who}</span></td>
          <td>{esc(r.get('referrer_domain') or '—')}</td>
          <td class="ta-ua" title="{esc(r.get('user_agent',''))}">{esc(r.get('user_agent',''))}</td>
        </tr>"""
    if not recent_rows:
        recent_rows = '<tr><td colspan="5" class="ta-empty">No matching visits.</td></tr>'

    day_opts = ""
    for d in (1, 7, 30, 90):
        sel = " selected" if d == days else ""
        day_opts += f'<option value="{d}"{sel}>Last {d} day{"s" if d != 1 else ""}</option>'

    vc_opts = (
        f'<option value="all"{" selected" if visitor_class == "all" else ""}>All visitors</option>'
        f'<option value="human"{" selected" if visitor_class == "human" else ""}>Humans only</option>'
        f'<option value="search_bot"{" selected" if visitor_class == "search_bot" else ""}>Search bots</option>'
        f'<option value="ai_bot"{" selected" if visitor_class == "ai_bot" else ""}>AI bots</option>'
        f'<option value="training_bot"{" selected" if visitor_class == "training_bot" else ""}>Training bots</option>'
    )

    _h = gtm_head_for_path(str(request.url.path))
    _b = gtm_body_for_path(str(request.url.path))
    nav = admin_top_nav_html(active="traffic-analytics")

    page = f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
{_h}
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Traffic analytics — Cartozo.ai</title>
<script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
<link rel="stylesheet" href="/static/styles.css"/>
<style>
.ta-wrap {{ max-width: 1200px; margin: 0 auto; padding: 24px 24px 64px; }}
.ta-title {{ font-size: 1.5rem; font-weight: 700; margin-bottom: 6px; }}
.ta-sub {{ color: rgba(255,255,255,.55); font-size: .9rem; margin-bottom: 24px; max-width: 720px; }}
[data-theme=light] .ta-sub {{ color: rgba(15,23,42,.6); }}
.ta-cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 14px; margin-bottom: 24px; }}
.ta-card {{ background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.08); border-radius: 12px; padding: 16px; }}
[data-theme=light] .ta-card {{ background: #fff; border-color: rgba(15,23,42,.1); }}
.ta-card-n {{ font-size: 1.6rem; font-weight: 700; color: #4F46E5; }}
.ta-card-l {{ font-size: .78rem; color: rgba(255,255,255,.55); margin-top: 4px; }}
[data-theme=light] .ta-card-l {{ color: rgba(15,23,42,.55); }}
.ta-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }}
@media(max-width:900px){{ .ta-grid {{ grid-template-columns: 1fr; }} }}
.ta-panel {{ background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.08); border-radius: 12px; padding: 18px; }}
[data-theme=light] .ta-panel {{ background: #fff; }}
.ta-panel h2 {{ font-size: .95rem; margin-bottom: 14px; }}
.ta-hbar-row {{ display: grid; grid-template-columns: 140px 1fr 48px; gap: 10px; align-items: center; margin-bottom: 8px; font-size: .82rem; }}
.ta-hbar-label {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.ta-hbar-track {{ height: 8px; background: rgba(255,255,255,.08); border-radius: 4px; overflow: hidden; }}
.ta-hbar-fill {{ height: 100%; border-radius: 4px; }}
.ta-hbar-num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.ta-toolbar {{ display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 20px; align-items: center; }}
.ta-toolbar select {{ padding: 8px 12px; border-radius: 8px; border: 1px solid rgba(255,255,255,.15); background: rgba(0,0,0,.2); color: inherit; }}
.ta-table {{ width: 100%; border-collapse: collapse; font-size: .82rem; }}
.ta-table th, .ta-table td {{ padding: 10px 8px; border-bottom: 1px solid rgba(255,255,255,.06); text-align: left; vertical-align: top; }}
.ta-mono {{ font-family: ui-monospace, monospace; font-size: .78rem; }}
.ta-ua {{ max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.ta-badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: .72rem; font-weight: 600; }}
.ta-badge-human {{ background: rgba(34,197,94,.15); color: #4ade80; }}
.ta-badge-bot {{ background: rgba(251,191,36,.12); color: #fbbf24; }}
.ta-empty {{ color: rgba(255,255,255,.45); padding: 16px; text-align: center; }}
.ta-note {{ font-size: .8rem; color: rgba(255,255,255,.45); margin-top: 16px; line-height: 1.5; }}
</style>
</head>
<body>
{_b}
{nav}
<div class="ta-wrap">
  <h1 class="ta-title">Traffic analytics</h1>
  <p class="ta-sub">Server-side classification of visitors: people vs search bots vs AI crawlers. Blog “Views” include bots; “Human sessions” (JS beacon) and this dashboard’s <strong>People</strong> metric are closer to real users. GA4 (via GTM) has its own bot filtering — compare all three.</p>

  <form class="ta-toolbar" method="get" action="/admin/traffic-analytics">
    <select name="days" onchange="this.form.submit()">{day_opts}</select>
    <select name="class" onchange="this.form.submit()">{vc_opts}</select>
  </form>

  <div class="ta-cards">
    <div class="ta-card"><div class="ta-card-n">{summary['total']}</div><div class="ta-card-l">All page views</div></div>
    <div class="ta-card"><div class="ta-card-n">{summary['humans']}</div><div class="ta-card-l">People ({summary['human_pct']}%)</div></div>
    <div class="ta-card"><div class="ta-card-n">{summary['bots']}</div><div class="ta-card-l">Bots & crawlers</div></div>
    <div class="ta-card"><div class="ta-card-n">{summary['unique_humans']}</div><div class="ta-card-l">Unique visitors (hashed IP)</div></div>
    <div class="ta-card"><div class="ta-card-n">{summary['blog_human_views']}</div><div class="ta-card-l">Blog views — people</div></div>
    <div class="ta-card"><div class="ta-card-n">{summary['blog_bot_views']}</div><div class="ta-card-l">Blog views — bots</div></div>
  </div>

  <div class="ta-grid">
    <div class="ta-panel"><h2>Top pages (people only)</h2>{hbar_rows(summary['top_paths'], 'path')}</div>
    <div class="ta-panel"><h2>Top referrers (people)</h2>{hbar_rows(summary['top_referrers'], 'domain')}</div>
    <div class="ta-panel"><h2>Top bots & crawlers</h2>{hbar_rows(summary['top_bots'], 'name')}</div>
    <div class="ta-panel"><h2>AI / search referrers</h2>{hbar_rows(summary['ai_referrers'], 'domain') or '<div class="ta-empty">No AI referrer traffic yet.</div>'}</div>
  </div>

  <div class="ta-panel" style="margin-bottom:20px">
    <h2>Breakdown by visitor type</h2>
    <table class="ta-table"><thead><tr><th>Type</th><th>Views</th></tr></thead><tbody>{class_rows}</tbody></table>
  </div>

  <div class="ta-panel">
    <h2>Recent visits</h2>
    <table class="ta-table"><thead><tr><th>Time (UTC)</th><th>Path</th><th>Visitor</th><th>Referrer</th><th>User-Agent</th></tr></thead><tbody>{recent_rows}</tbody></table>
  </div>

  <p class="ta-note">Classification uses User-Agent patterns (Googlebot, OAI-SearchBot, GPTBot, etc.). UAs can be spoofed — treat bot names as hints. IPs are stored as salted hashes only. For nginx-level logs see <code>docs/ai-crawler-monitoring.md</code>.</p>
</div>
<script>{ADMIN_THEME_SCRIPT.strip()}</script>
<script>{ADMIN_MERCHANT_SCRIPT.strip()}</script>
</body>
</html>"""
    return HTMLResponse(content=page)
