"""
/pricing — High-conversion SaaS pricing page. Content from `pricing_plans.json`.
Payment hooks: `data-plan-id`, `data-paddle-price-id`, `data-paypro-plan-code` on plan CTAs;
override `window.cartozoPricing.onSelectPlan` before click to integrate Paddle / PayPro.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .public_nav import HP_FOOTER_CSS, HP_NAV_CSS, public_site_footer_html, public_site_nav_html
from .seo import head_canonical_social

_CONFIG_PATH = Path(__file__).resolve().parent / "pricing_plans.json"


def load_pricing_config() -> dict[str, Any]:
    with _CONFIG_PATH.open(encoding="utf-8") as f:
        cfg: dict[str, Any] = json.load(f)
    # Legacy key: older code or tools expected cfg["header"] with title/subtitle (same as hero).
    if "header" not in cfg:
        hero = cfg.get("hero")
        if isinstance(hero, dict):
            cfg["header"] = {
                "title": hero.get("h1") or "",
                "subtitle": hero.get("subheadline") or "",
            }
        else:
            cfg["header"] = {"title": "", "subtitle": ""}
    return cfg


def _esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def _esc_attr(s: str) -> str:
    return html.escape(s or "", quote=True)


def _render_plan_card(plan: dict[str, Any]) -> str:
    pid = _esc_attr(plan["id"])
    highlighted = bool(plan.get("highlighted"))
    badge = plan.get("badge")
    emoji = (plan.get("tier_emoji") or "").strip()
    name = _esc(plan.get("name") or "Plan")
    title_vis = f"{emoji} {name}".strip() if emoji else name
    pd = _esc(plan["price_display"])
    pp = _esc(plan.get("price_period") or "")
    cta = _esc(plan["cta_label"])
    href = _esc_attr(plan["cta_href"])
    paddle = _esc_attr(str(plan.get("paddle_price_id") or ""))
    paypro = _esc_attr(str(plan.get("paypro_plan_code") or ""))
    tagline = (plan.get("tagline") or "").strip()
    hook = (plan.get("hook_line") or "").strip()

    cls = "pp-card"
    if highlighted:
        cls += " pp-card--highlight"
    tier = pid if pid in ("free", "starter", "growth", "pro") else ""
    if tier:
        cls += f" pp-card--tier-{tier}"

    feat_items = "".join(f"<li>{_esc(x)}</li>" for x in plan.get("features") or [])
    lim = plan.get("limitations") or []
    lim_block = ""
    if lim:
        lim_items = "".join(
            f'<li><span class="pp-li-x" aria-hidden="true">❌</span> {_esc(x)}</li>' for x in lim
        )
        lim_block = f'<ul class="pp-list pp-list--limits">{lim_items}</ul>'

    badge_html = ""
    if badge:
        badge_html = f'<span class="pp-badge">{_esc(badge)}</span>'

    period_html = f'<span class="pp-price-period">{pp}</span>' if pp else ""
    cta_cls = "pp-cta--primary" if highlighted else "pp-cta--secondary"

    tagline_html = ""
    if tagline:
        tagline_html = f'<p class="pp-tagline">{_esc(tagline)}</p>'

    hook_html = ""
    if hook:
        hook_html = f'<p class="pp-hook">👉 {_esc(hook)}</p>'

    return f"""
      <article class="{cls}" data-plan-id="{pid}">
        {badge_html}
        <h3 class="pp-name" id="plan-{pid}">{_esc(title_vis)}</h3>
        <p class="pp-price-line" aria-labelledby="plan-{pid}">
          <span class="pp-price">{pd}</span>{period_html}
        </p>
        {tagline_html}
        <ul class="pp-list pp-list--features">{feat_items}</ul>
        {lim_block}
        {hook_html}
        <a class="pp-cta {cta_cls}"
           href="{href}"
           data-plan-id="{pid}"
           data-paddle-price-id="{paddle}"
           data-paypro-plan-code="{paypro}">{cta}</a>
      </article>
    """


def _cell_inner(raw: str) -> str:
    s = (raw or "").strip()
    if s == "✓":
        return (
            '<span class="pp-cmp-yes" title="Included">'
            '<span class="pp-cmp-check" aria-hidden="true">✓</span></span>'
        )
    if s == "—" or s == "-":
        return '<span class="pp-cmp-no">—</span>'
    return f'<span class="pp-cmp-txt">{_esc(s)}</span>'


def _render_comparison(cfg: dict[str, Any]) -> str:
    comp = cfg.get("comparison") or {}
    col_ids = comp.get("column_plan_ids") or []
    plans = {p["id"]: p for p in cfg.get("plans") or []}
    rows = comp.get("rows") or []

    head_parts: list[str] = []
    for cid in col_ids:
        p = plans.get(cid)
        if not p:
            continue
        head_parts.append(
            f'<div class="pp-cmp-colhead"><span class="pp-cmp-plan">{_esc(p.get("name") or cid)}</span>'
            f'<span class="pp-cmp-sub">{_esc(p.get("price_display") or "")}{_esc(p.get("price_period") or "")}</span></div>'
        )
    head_cells = "".join(head_parts)
    body_rows: list[str] = []
    for row in rows:
        label = _esc(row["label"])
        cells_raw = row.get("cells") or []
        cells = "".join(f'<div class="pp-cmp-cell">{_cell_inner(c)}</div>' for c in cells_raw)
        body_rows.append(
            f'<div class="pp-cmp-row"><div class="pp-cmp-label">{label}</div>{cells}</div>'
        )
    return f"""
    <div class="pp-cmp-scroll">
    <div class="pp-cmp" role="region" aria-label="Plan comparison">
      <div class="pp-cmp-head">
        <div class="pp-cmp-corner" aria-hidden="true"></div>
        {head_cells}
      </div>
      <div class="pp-cmp-body">
        {"".join(body_rows)}
      </div>
    </div>
    </div>
    """


def _render_addons_compact(addons: list[dict[str, Any]], addons_section: dict[str, Any]) -> str:
    parts: list[str] = []
    for a in addons:
        aid = _esc_attr(a["id"])
        title = _esc(a["title"])
        price = _esc(a["price"])
        note = (a.get("note") or "").strip()
        paddle = _esc_attr(str(a.get("paddle_price_id") or ""))
        note_html = f' <span class="pp-add-line-note">{_esc(note)}</span>' if note else ""
        parts.append(f"""
        <div class="pp-add-line" data-addon-id="{aid}">
          <span class="pp-add-line-txt">{title}</span>
          <span class="pp-add-line-meta"><span class="pp-add-line-price">{price}</span>{note_html}</span>
          <button type="button" class="pp-add-line-btn"
            data-addon-id="{aid}"
            data-paddle-price-id="{paddle}">Add</button>
        </div>
        """)
    return "\n".join(parts)


def build_pricing_html(
    *,
    meta_title: str,
    meta_description: str,
    og_title: str,
    og_description: str,
    canonical_url: str,
    og_image: str = "",
    og_site_name: str = "",
    gtm_head: str,
    gtm_body: str,
) -> str:
    cfg = load_pricing_config()
    seo_block = head_canonical_social(
        canonical_url=canonical_url,
        og_title=og_title,
        og_description=og_description,
        og_image=og_image,
        og_site_name=og_site_name,
        og_type="website",
    )
    mt = _esc(meta_title)
    md = _esc(meta_description)

    hero = cfg.get("hero") or {}
    pain = cfg.get("pain_solution") or cfg.get("pain") or {}
    hiw = cfg.get("how_it_works") or {}
    pricing_head = cfg.get("pricing_section") or {}
    social = cfg.get("social_proof") or {}
    roi = cfg.get("roi") or {}
    comp_meta = cfg.get("comparison") or {}
    addons_sec = cfg.get("addons_section") or {}
    trust_c = cfg.get("trust_commitments") or {}
    final = cfg.get("final_cta") or {}
    seo_f = cfg.get("seo_footer") or {}

    h1 = _esc(hero.get("h1") or (cfg.get("header") or {}).get("title") or "Pricing")
    sub = _esc(hero.get("subheadline") or (cfg.get("header") or {}).get("subtitle") or "")
    cta1 = _esc(hero.get("cta_primary_label") or "Get started")
    cta1_h = _esc_attr(hero.get("cta_primary_href") or "/login")
    cta2 = _esc(hero.get("cta_secondary_label") or "")
    cta2_h = _esc_attr(hero.get("cta_secondary_href") or "/how-it-works")
    hero_trust = _esc(hero.get("trust_line") or "")

    pain_title = _esc(pain.get("title") or "")
    pain_items = pain.get("items") or []
    if not pain_items and pain.get("bullets"):
        pain_items = [{"label": "", "text": b} for b in pain["bullets"]]
    pain_parts: list[str] = []
    for it in pain_items:
        label = (it.get("label") or "").strip()
        text = _esc((it.get("text") or "").strip())
        if label:
            pain_parts.append(f'<div class="pp-pain-item"><strong>{_esc(label)}</strong> {text}</div>')
        else:
            pain_parts.append(f'<div class="pp-pain-item">{text}</div>')
    pain_cards = "".join(pain_parts)
    pain_sol = _esc(pain.get("solution") or "")

    steps = hiw.get("steps") or []
    steps_html = "".join(
        f'<li class="pp-step"><span class="pp-step-n">{i + 1}</span><span class="pp-step-txt">{_esc(s)}</span></li>'
        for i, s in enumerate(steps)
    )

    ps_title = _esc(pricing_head.get("title") or "Plans")
    ps_sub = _esc(pricing_head.get("subtitle") or "")

    cards = "".join(_render_plan_card(p) for p in cfg.get("plans") or [])

    stat_prefixes = social.get("stat_prefixes") or ["up"] * len(social.get("stats") or [])
    stats_html = ""
    for i, line in enumerate(social.get("stats") or []):
        pref = stat_prefixes[i] if i < len(stat_prefixes) else "up"
        arrow = "↓" if pref == "down" else "↑"
        cls = "pp-stat--down" if pref == "down" else "pp-stat--up"
        stats_html += f'<p class="pp-stat {cls}"><span class="pp-stat-arrow" aria-hidden="true">{arrow}</span> {_esc(line)}</p>'
    quote = _esc(social.get("quote") or "")
    proof_title = _esc(social.get("title") or "")

    roi_text = _esc(roi.get("text") or "")

    comp_title = _esc(comp_meta.get("title") or "Compare")
    comp_sub = _esc(comp_meta.get("subtitle") or "")
    table = _render_comparison(cfg)

    add_title = _esc(addons_sec.get("title") or "Add-ons")
    add_sub = _esc(addons_sec.get("subtitle") or "")
    addons = _render_addons_compact(cfg.get("addons") or [], addons_sec)

    trust_lines = "".join(
        f'<p class="pp-trust-line"><span class="pp-trust-ico" aria-hidden="true">✔</span> {_esc(t)}</p>'
        for t in trust_c.get("lines") or []
    )

    fin_title = _esc(final.get("title") or "")
    fin_cta = _esc(final.get("cta_label") or "Get started")
    fin_href = _esc_attr(final.get("cta_href") or "/login")

    seo_para = _esc(seo_f.get("text") or "")

    cta2_block = ""
    if cta2:
        cta2_block = f'<a class="pp-hero-btn pp-hero-btn--ghost" href="{cta2_h}">{cta2}</a>'

    hiw_title = _esc(hiw.get("title") or "How it works")

    return (
        f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
{gtm_head}
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{mt}</title>
<meta name="description" content="{md}"/>
{seo_block}<script>try{{document.documentElement.setAttribute('data-theme',localStorage.getItem('hp-theme')||'dark')}}catch(e){{}}</script>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet"/>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{
  font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;
  background:#060711;color:#e5e7eb;
  -webkit-font-smoothing:antialiased;line-height:1.5;
}}
[data-theme=light] body{{background:#fafbfc;color:#0f172a}}
a{{color:inherit;text-decoration:none}}

:root{{
  --pp-line:rgba(255,255,255,.1);
  --pp-muted:rgba(229,231,235,.55);
  --pp-card:rgba(255,255,255,.03);
  --pp-accent:#5e6ad2;
  --pp-accent2:#7c3aed;
  --pp-green:#22c55e;
  --pp-red:#f87171;
}}
[data-theme=light]{{
  --pp-line:rgba(15,23,42,.1);
  --pp-muted:rgba(15,23,42,.55);
  --pp-card:#fff;
}}

.pp-bg{{position:fixed;inset:0;z-index:0;pointer-events:none;
  background:radial-gradient(ellipse 80% 50% at 50% -20%,rgba(94,106,210,.2),transparent),
    radial-gradient(ellipse 60% 40% at 100% 0%,rgba(124,58,237,.08),transparent);
}}
[data-theme=light] .pp-bg{{background:radial-gradient(ellipse 70% 45% at 50% -10%,rgba(94,106,210,.12),transparent)}}

.pp-wrap{{position:relative;z-index:1;max-width:1120px;margin:0 auto;padding:56px 20px 88px;box-sizing:border-box}}

@@HP_NAV_STYLES@@

.pp-hero{{padding:clamp(28px,5vh,48px) 0 36px;text-align:center;max-width:720px;margin:0 auto}}
.pp-hero h1{{
  font-size:clamp(1.75rem,3.8vw,2.45rem);font-weight:800;letter-spacing:-.04em;
  line-height:1.12;margin-bottom:16px;
}}
.pp-hero-sub{{color:var(--pp-muted);font-size:1.05rem;line-height:1.65;max-width:52ch;margin:0 auto 22px}}
.pp-hero-ctas{{display:flex;flex-wrap:wrap;gap:12px;justify-content:center;align-items:center;margin-bottom:18px}}
.pp-hero-btn{{
  display:inline-flex;align-items:center;justify-content:center;
  padding:12px 22px;border-radius:10px;font-size:.92rem;font-weight:600;
  transition:transform .15s,filter .15s,box-shadow .15s;
}}
.pp-hero-btn:hover{{transform:translateY(-1px);filter:brightness(1.05)}}
.pp-hero-btn--primary{{
  background:linear-gradient(135deg,#5e6ad2,#7c3aed);color:#fff;
  box-shadow:0 8px 28px -12px rgba(94,106,210,.6);
}}
.pp-hero-btn--ghost{{
  background:rgba(255,255,255,.06);border:1px solid var(--pp-line);color:#e5e7eb;
}}
[data-theme=light] .pp-hero-btn--ghost{{background:#fff;color:#0f172a}}
.pp-hero-trust{{font-size:.88rem;color:var(--pp-muted);letter-spacing:.02em}}

.pp-section{{margin-top:clamp(36px,5vw,56px)}}
.pp-section--tight{{margin-top:clamp(24px,3vw,36px)}}
.pp-section-head{{text-align:center;max-width:580px;margin:0 auto 22px}}
.pp-section-head h2{{font-size:clamp(1.25rem,2.2vw,1.6rem);font-weight:700;letter-spacing:-.03em;margin-bottom:8px}}
.pp-section-head p{{color:var(--pp-muted);font-size:.95rem;line-height:1.55}}

.pp-pain{{
  border-radius:16px;border:1px solid var(--pp-line);
  background:var(--pp-card);padding:clamp(20px,3vw,28px) clamp(16px,2.5vw,24px);
}}
[data-theme=light] .pp-pain{{box-shadow:0 12px 40px -24px rgba(15,23,42,.12)}}
.pp-pain h2{{font-size:1.12rem;font-weight:700;margin-bottom:16px;text-align:center;letter-spacing:-.02em}}
.pp-pain-grid{{display:grid;gap:14px;grid-template-columns:1fr}}
@media(min-width:720px){{
  .pp-pain-grid{{grid-template-columns:repeat(3,1fr);gap:16px}}
}}
.pp-pain-item{{
  border-radius:12px;border:1px solid var(--pp-line);
  background:rgba(255,255,255,.02);padding:14px 16px;
  font-size:.88rem;line-height:1.45;color:var(--pp-muted);
}}
[data-theme=light] .pp-pain-item{{background:#f8fafc}}
.pp-pain-item strong{{display:block;font-size:.78rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#e5e7eb;margin-bottom:6px}}
[data-theme=light] .pp-pain-item strong{{color:#0f172a}}
.pp-pain-sol{{font-size:.95rem;color:var(--pp-muted);line-height:1.6;margin-top:18px;text-align:center;font-weight:600;color:#cbd5e1}}
[data-theme=light] .pp-pain-sol{{color:#475569}}

.pp-hiw{{
  border-radius:16px;border:1px solid var(--pp-line);
  background:linear-gradient(180deg,rgba(94,106,210,.06),transparent);
  padding:clamp(22px,3vw,32px) clamp(18px,3vw,28px);
}}
.pp-hiw h2{{text-align:center;font-size:1.15rem;font-weight:700;margin-bottom:20px}}
.pp-steps{{list-style:none;max-width:720px;margin:0 auto;padding:0;display:flex;flex-direction:column;gap:14px}}
.pp-step{{display:flex;gap:14px;align-items:flex-start;text-align:left}}
.pp-step-n{{
  flex-shrink:0;width:28px;height:28px;border-radius:8px;
  background:rgba(94,106,210,.25);border:1px solid rgba(94,106,210,.35);
  font-size:.8rem;font-weight:700;display:flex;align-items:center;justify-content:center;color:#c4b5fd;
}}
.pp-step-txt{{font-size:.92rem;color:#e5e7eb;line-height:1.5;padding-top:2px}}
[data-theme=light] .pp-step-txt{{color:#334155}}

.pp-grid{{
  display:grid;gap:16px;grid-template-columns:1fr;
  align-items:stretch;max-width:1080px;margin:0 auto;
}}
@media(min-width:640px){{
  .pp-grid{{grid-template-columns:repeat(2,1fr)}}
}}
@media(min-width:1024px){{
  .pp-grid{{grid-template-columns:repeat(4,1fr);gap:14px}}
}}

.pp-card{{
  position:relative;border-radius:14px;border:1px solid var(--pp-line);
  background:var(--pp-card);padding:20px 16px 18px;
  display:flex;flex-direction:column;min-height:100%;
}}
[data-theme=light] .pp-card{{box-shadow:0 8px 30px -18px rgba(15,23,42,.12)}}
.pp-card--highlight{{
  border-color:rgba(124,58,237,.45);
  box-shadow:0 0 0 1px rgba(124,58,237,.2),0 18px 44px -18px rgba(124,58,237,.35);
  transform:translateY(-3px);
  z-index:2;
}}
.pp-card--tier-free{{border-top:3px solid #22c55e}}
.pp-card--tier-starter{{border-top:3px solid #3b82f6}}
.pp-card--tier-growth{{border-top:3px solid #a855f7}}
.pp-card--tier-pro{{border-top:3px solid #64748b}}
[data-theme=light] .pp-card--tier-pro{{border-top-color:#334155}}
.pp-badge{{
  position:absolute;top:-9px;left:50%;transform:translateX(-50%);
  font-size:.62rem;font-weight:700;letter-spacing:.05em;
  padding:5px 11px;border-radius:99px;
  background:linear-gradient(135deg,#7c3aed,#5e6ad2);color:#fff;white-space:nowrap;
}}
.pp-name{{font-size:.95rem;font-weight:800;letter-spacing:.04em;margin-bottom:4px}}
.pp-price-line{{margin-bottom:6px}}
.pp-price{{font-size:1.65rem;font-weight:800;letter-spacing:-.03em}}
.pp-price-period{{font-size:.88rem;font-weight:500;color:var(--pp-muted);margin-left:2px}}
.pp-tagline{{font-size:.78rem;color:var(--pp-muted);margin-bottom:12px;line-height:1.4}}
.pp-list{{list-style:none;padding:0;margin:0 0 12px;flex:1}}
.pp-list li{{font-size:.8rem;padding:6px 0;color:#e5e7eb;border-bottom:1px solid rgba(255,255,255,.06)}}
[data-theme=light] .pp-list li{{color:#334155;border-bottom-color:var(--pp-line)}}
.pp-list--features li:last-child{{border-bottom:none}}
.pp-list--limits{{margin-top:4px}}
.pp-list--limits li{{color:var(--pp-muted);font-size:.78rem;border-bottom-style:dashed;border-color:rgba(255,255,255,.08)}}
.pp-li-x{{margin-right:4px;opacity:.9}}
.pp-hook{{font-size:.8rem;color:#c4b5fd;line-height:1.45;margin:10px 0 14px;padding:8px 10px;border-radius:8px;background:rgba(124,58,237,.12);border:1px solid rgba(124,58,237,.2)}}
[data-theme=light] .pp-hook{{color:#5b21b6;background:#f5f3ff}}
.pp-cta{{
  display:block;text-align:center;margin-top:auto;
  padding:10px 12px;border-radius:10px;font-size:.82rem;font-weight:600;
  transition:transform .15s,filter .15s;
}}
.pp-cta:hover{{transform:translateY(-1px);filter:brightness(1.06)}}
.pp-cta--primary{{
  background:linear-gradient(135deg,#5e6ad2,#7c3aed);color:#fff;
}}
.pp-cta--secondary{{
  background:rgba(255,255,255,.06);border:1px solid var(--pp-line);color:#e5e7eb;
}}
[data-theme=light] .pp-cta--secondary{{background:#f8fafc;color:#0f172a}}

.pp-proof{{
  border-radius:16px;border:1px solid var(--pp-line);
  background:var(--pp-card);padding:clamp(22px,3vw,32px);text-align:center;
}}
.pp-proof h2{{font-size:1.15rem;font-weight:700;margin-bottom:16px}}
.pp-proof-stats{{max-width:520px;margin:0 auto 20px}}
.pp-stat{{font-size:.92rem;margin:10px 0;display:flex;align-items:center;justify-content:center;gap:8px;flex-wrap:wrap}}
.pp-stat-arrow{{font-weight:800;font-size:1rem}}
.pp-stat--down .pp-stat-arrow{{color:#f87171}}
.pp-stat--up .pp-stat-arrow{{color:#22c55e}}
.pp-quote{{font-size:1rem;font-style:italic;color:#cbd5e1;line-height:1.55;max-width:540px;margin:0 auto;padding:0 8px}}
[data-theme=light] .pp-quote{{color:#475569}}
.pp-quote::before{{content:"\\201C"}}
.pp-quote::after{{content:"\\201D"}}

.pp-roi{{
  text-align:center;padding:20px 18px;border-radius:14px;
  border:1px dashed var(--pp-line);background:rgba(94,106,210,.05);
}}
.pp-roi p{{font-size:.92rem;color:var(--pp-muted);line-height:1.6;max-width:56ch;margin:0 auto}}

.pp-cmp-scroll{{overflow-x:auto;-webkit-overflow-scrolling:touch;border-radius:14px;margin:0 -4px;padding:0 4px}}
.pp-cmp{{border-radius:14px;border:1px solid var(--pp-line);overflow:hidden;background:var(--pp-card);min-width:min(100%,680px)}}
.pp-cmp-head{{
  display:grid;
  grid-template-columns:minmax(100px,1fr) repeat(4,minmax(0,1fr));
  gap:0;border-bottom:1px solid var(--pp-line);
  background:rgba(255,255,255,.03);
}}
[data-theme=light] .pp-cmp-head{{background:#f1f5f9}}
.pp-cmp-corner{{min-height:48px}}
.pp-cmp-colhead{{padding:14px 10px;text-align:center;border-left:1px solid var(--pp-line)}}
.pp-cmp-plan{{display:block;font-size:.78rem;font-weight:800;letter-spacing:.06em}}
.pp-cmp-sub{{display:block;font-size:.68rem;color:var(--pp-muted);margin-top:4px}}
.pp-cmp-body{{display:flex;flex-direction:column}}
.pp-cmp-row{{
  display:grid;
  grid-template-columns:minmax(100px,1fr) repeat(4,minmax(0,1fr));
  align-items:stretch;
  border-bottom:1px solid var(--pp-line);
}}
.pp-cmp-row:last-child{{border-bottom:none}}
.pp-cmp-label{{
  padding:12px 14px;font-size:.78rem;color:var(--pp-muted);font-weight:600;
  display:flex;align-items:center;border-right:1px solid var(--pp-line);
}}
.pp-cmp-cell{{
  padding:12px 8px;text-align:center;font-size:.78rem;
  display:flex;align-items:center;justify-content:center;
  border-left:1px solid var(--pp-line);
}}
.pp-cmp-yes{{color:#22c55e}}
.pp-cmp-check{{font-weight:800;font-size:.95rem}}
.pp-cmp-no{{color:var(--pp-muted);opacity:.7}}
.pp-cmp-txt{{color:#e5e7eb}}
[data-theme=light] .pp-cmp-txt{{color:#334155}}

.pp-add-compact{{border-radius:14px;border:1px solid var(--pp-line);background:var(--pp-card);padding:8px 0;overflow:hidden}}
.pp-add-line{{
  display:flex;flex-wrap:wrap;align-items:center;gap:10px;justify-content:space-between;
  padding:14px 18px;border-bottom:1px solid var(--pp-line);
}}
.pp-add-line:last-child{{border-bottom:none}}
.pp-add-line-txt{{font-size:.9rem;font-weight:600}}
.pp-add-line-meta{{font-size:.88rem;color:var(--pp-muted);margin-left:auto}}
.pp-add-line-price{{font-weight:700;color:#e5e7eb}}
[data-theme=light] .pp-add-line-price{{color:#0f172a}}
.pp-add-line-note{{font-weight:500}}
.pp-add-line-btn{{
  padding:6px 12px;border-radius:8px;border:1px solid var(--pp-line);
  background:transparent;color:var(--pp-muted);font-size:.75rem;font-weight:600;cursor:pointer;
}}
.pp-add-line-btn:hover{{color:#e5e7eb;border-color:rgba(94,106,210,.45)}}

.pp-trust-commit{{text-align:center;padding:8px 12px 0}}
.pp-trust-line{{font-size:.88rem;color:var(--pp-muted);margin:8px 0;display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:center}}
.pp-trust-ico{{color:#22c55e;font-size:.85rem}}

.pp-final{{
  margin-top:clamp(40px,6vw,56px);
  text-align:center;padding:clamp(28px,4vw,40px) 24px;
  border-radius:16px;border:1px solid var(--pp-line);
  background:linear-gradient(135deg,rgba(94,106,210,.12),rgba(124,58,237,.08));
}}
.pp-final h2{{font-size:clamp(1.2rem,2.2vw,1.5rem);font-weight:700;margin-bottom:16px}}
.pp-final .pp-hero-btn--primary{{padding:14px 28px}}

.pp-seo{{
  margin-top:40px;padding-top:28px;border-top:1px solid var(--pp-line);
  max-width:720px;margin-left:auto;margin-right:auto;
}}
.pp-seo p{{font-size:.82rem;color:var(--pp-muted);line-height:1.65}}

.pp-trust-foot{{text-align:center;padding:28px 16px 0}}
@media(max-width:768px){{
  .pp-card--highlight{{transform:none}}
}}
</style>
</head>
<body>
{gtm_body}
<div class="pp-bg" aria-hidden="true"></div>

@@PUBLIC_NAV@@

<div class="pp-wrap">
  <header class="pp-hero">
    <h1>{h1}</h1>
    <p class="pp-hero-sub">{sub}</p>
    <div class="pp-hero-ctas">
      <a class="pp-hero-btn pp-hero-btn--primary" href="{cta1_h}">{cta1}</a>
      {cta2_block}
    </div>
    <p class="pp-hero-trust">{hero_trust}</p>
  </header>

  <section class="pp-section pp-section--tight" aria-labelledby="pain-title">
    <div class="pp-pain">
      <h2 id="pain-title">{pain_title}</h2>
      <div class="pp-pain-grid">
{pain_cards}
      </div>
      <p class="pp-pain-sol">{pain_sol}</p>
    </div>
  </section>

  <section class="pp-section" aria-labelledby="hiw-title">
    <div class="pp-hiw">
      <h2 id="hiw-title">{hiw_title}</h2>
      <ul class="pp-steps" role="list">
{steps_html}
      </ul>
    </div>
  </section>

  <section class="pp-section" aria-labelledby="plans-title">
    <div class="pp-section-head">
      <h2 id="plans-title">{ps_title}</h2>
      <p>{ps_sub}</p>
    </div>
    <div class="pp-grid">
{cards}
    </div>
  </section>

  <section class="pp-section" aria-labelledby="proof-title">
    <div class="pp-proof">
      <h2 id="proof-title">{proof_title}</h2>
      <div class="pp-proof-stats">
{stats_html}
      </div>
      <p class="pp-quote">{quote}</p>
    </div>
  </section>

  <section class="pp-section" aria-labelledby="roi-title">
    <div class="pp-roi">
      <p id="roi-title">{roi_text}</p>
    </div>
  </section>

  <section class="pp-section" aria-labelledby="compare-title">
    <div class="pp-section-head">
      <h2 id="compare-title">{comp_title}</h2>
      <p>{comp_sub}</p>
    </div>
{table}
  </section>

  <section class="pp-section" aria-labelledby="addons-title">
    <div class="pp-section-head">
      <h2 id="addons-title">{add_title}</h2>
      <p>{add_sub}</p>
    </div>
    <div class="pp-add-compact">
{addons}
    </div>
  </section>

  <section class="pp-trust-commit" aria-label="Trust">
{trust_lines}
  </section>

  <section class="pp-final" aria-labelledby="final-title">
    <h2 id="final-title">{fin_title}</h2>
    <a class="pp-hero-btn pp-hero-btn--primary" href="{fin_href}">{fin_cta}</a>
  </section>

  <footer class="pp-seo">
    <p>{seo_para}</p>
  </footer>

  @@PUBLIC_SITE_FOOTER@@
</div>

<script>
(function(){{
  var btn=document.getElementById('themeToggle'),K='hp-theme';
  function getT(){{return localStorage.getItem(K)||'dark'}}
  function setT(v){{document.documentElement.setAttribute('data-theme',v);localStorage.setItem(K,v);if(btn)btn.textContent=v==='dark'?'\\u2600':'\\u263E'}}
  if(btn){{btn.addEventListener('click',function(){{setT(getT()==='dark'?'light':'dark')}});setT(getT())}}

  window.cartozoPricing = window.cartozoPricing || {{}};
  if (typeof window.cartozoPricing.onSelectPlan !== 'function') {{
    window.cartozoPricing.onSelectPlan = function (payload) {{
      if (console && console.debug) console.debug('[cartozo-pricing] plan CTA', payload);
    }};
  }}
  if (typeof window.cartozoPricing.onSelectAddon !== 'function') {{
    window.cartozoPricing.onSelectAddon = function (payload) {{
      if (console && console.debug) console.debug('[cartozo-pricing] add-on', payload);
    }};
  }}

  function attachPlanHooks() {{
    document.querySelectorAll('a[data-plan-id]').forEach(function (a) {{
      a.addEventListener('click', function () {{
        window.cartozoPricing.onSelectPlan({{
          planId: a.getAttribute('data-plan-id'),
          paddlePriceId: a.getAttribute('data-paddle-price-id') || null,
          payproPlanCode: a.getAttribute('data-paypro-plan-code') || null,
          href: a.getAttribute('href'),
        }});
      }});
    }});
    document.querySelectorAll('.pp-add-line-btn').forEach(function (b) {{
      b.addEventListener('click', function () {{
        window.cartozoPricing.onSelectAddon({{
          addonId: b.getAttribute('data-addon-id'),
          paddlePriceId: b.getAttribute('data-paddle-price-id') || null,
        }});
      }});
    }});
  }}
  attachPlanHooks();
}})();
</script>
</body>
</html>
"""
    ).replace("@@HP_NAV_STYLES@@", HP_NAV_CSS + HP_FOOTER_CSS).replace(
        "@@PUBLIC_NAV@@", public_site_nav_html(feed_structure_href="/#feed-structure"),
    ).replace("@@PUBLIC_SITE_FOOTER@@", public_site_footer_html(feed_structure_href="/#feed-structure"))

