"""
/pricing — SaaS pricing page. Content is data-driven from `pricing_plans.json`.
Payment hooks: `data-plan-id`, `data-paddle-price-id`, `data-paypro-plan-code` on CTAs;
override `window.cartozoPricing.onSelectPlan` before click to integrate Paddle / PayPro.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .public_nav import HP_FOOTER_CSS, HP_NAV_CSS, public_site_footer_html, public_site_nav_html

_CONFIG_PATH = Path(__file__).resolve().parent / "pricing_plans.json"


def load_pricing_config() -> dict[str, Any]:
    with _CONFIG_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def _esc_attr(s: str) -> str:
    return html.escape(s or "", quote=True)


def _render_plan_card(plan: dict[str, Any]) -> str:
    pid = _esc_attr(plan["id"])
    highlighted = bool(plan.get("highlighted"))
    badge = plan.get("badge")
    name = _esc(plan["name"])
    pd = _esc(plan["price_display"])
    pp = _esc(plan.get("price_period") or "")
    cta = _esc(plan["cta_label"])
    href = _esc_attr(plan["cta_href"])
    paddle = _esc_attr(str(plan.get("paddle_price_id") or ""))
    paypro = _esc_attr(str(plan.get("paypro_plan_code") or ""))

    cls = "pp-card"
    if highlighted:
        cls += " pp-card--highlight"

    feat_items = "".join(f"<li>{_esc(x)}</li>" for x in plan.get("features") or [])
    lim = plan.get("limitations") or []
    lim_block = ""
    if lim:
        lim_items = "".join(f"<li>{_esc(x)}</li>" for x in lim)
        lim_block = f'<p class="pp-subhead">Limitations</p><ul class="pp-list pp-list--muted">{lim_items}</ul>'

    badge_html = ""
    if badge:
        badge_html = f'<span class="pp-badge">{_esc(badge)}</span>'

    period_html = f'<span class="pp-price-period">{pp}</span>' if pp else ""
    cta_cls = "pp-cta--primary" if highlighted else "pp-cta--secondary"

    return f"""
      <article class="{cls}" data-plan-id="{pid}">
        {badge_html}
        <h3 class="pp-name" id="plan-{pid}">{name}</h3>
        <p class="pp-price-line" aria-labelledby="plan-{pid}">
          <span class="pp-price">{pd}</span>{period_html}
        </p>
        <ul class="pp-list pp-list--features">{feat_items}</ul>
        {lim_block}
        <a class="pp-cta {cta_cls}"
           href="{href}"
           data-plan-id="{pid}"
           data-paddle-price-id="{paddle}"
           data-paypro-plan-code="{paypro}">{cta}</a>
      </article>
    """


def _render_addons(addons: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for a in addons:
        aid = _esc_attr(a["id"])
        title = _esc(a["title"])
        price = _esc(a["price"])
        note = _esc(a.get("note") or "")
        paddle = _esc_attr(str(a.get("paddle_price_id") or ""))
        note_html = f' <span class="pp-addon-note">{note}</span>' if note else ""
        parts.append(f"""
        <div class="pp-addon" data-addon-id="{aid}">
          <div class="pp-addon-copy">
            <h4 class="pp-addon-title">{title}</h4>
            <p class="pp-addon-meta"><span class="pp-addon-price">{price}</span>{note_html}</p>
          </div>
          <button type="button" class="pp-addon-btn"
            data-addon-id="{aid}"
            data-paddle-price-id="{paddle}">Add at checkout</button>
        </div>
        """)
    return "\n".join(parts)


def _render_comparison(cfg: dict[str, Any]) -> str:
    comp = cfg["comparison"]
    col_ids = comp["column_plan_ids"]
    plans = {p["id"]: p for p in cfg["plans"]}
    headers = "".join(
        f'<th scope="col"><span class="pp-th-name">{_esc(plans[cid]["name"])}</span><span class="pp-th-price">{_esc(plans[cid]["price_display"])}{_esc(plans[cid].get("price_period") or "")}</span></th>'
        for cid in col_ids
    )
    body_rows: list[str] = []
    for row in comp["rows"]:
        label = _esc(row["label"])
        cells = "".join(f"<td>{_esc(c)}</td>" for c in row["cells"])
        body_rows.append(f"<tr><th scope=\"row\">{label}</th>{cells}</tr>")
    return f"""
    <div class="pp-table-scroll">
      <table class="pp-table">
        <thead>
          <tr>
            <th scope="col" class="pp-tcorner">Compare</th>
            {headers}
          </tr>
        </thead>
        <tbody>
          {"".join(body_rows)}
        </tbody>
      </table>
    </div>
    """


def build_pricing_html(
    *,
    meta_title: str,
    meta_description: str,
    og_title: str,
    og_description: str,
    gtm_head: str,
    gtm_body: str,
) -> str:
    cfg = load_pricing_config()
    mt = _esc(meta_title)
    md = _esc(meta_description)
    ot = _esc(og_title)
    od = _esc(og_description)

    header = cfg["header"]
    pain = cfg["pain"]
    trust = cfg["trust"]

    h_title = _esc(header["title"])
    h_sub = _esc(header["subtitle"])
    pain_title = _esc(pain["title"])
    pain_bullets = "".join(f"<li>{_esc(b)}</li>" for b in pain["bullets"])
    pain_sol = _esc(pain["solution"])
    trust_lines = "".join(f'<p class="pp-trust-line">{_esc(t)}</p>' for t in trust["lines"])

    cards = "".join(_render_plan_card(p) for p in cfg["plans"])
    addons = _render_addons(cfg["addons"])
    table = _render_comparison(cfg)

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
<meta name="twitter:card" content="summary_large_image"/>
<script>try{{document.documentElement.setAttribute('data-theme',localStorage.getItem('hp-theme')||'dark')}}catch(e){{}}</script>
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

.pp-wrap{{position:relative;z-index:1;max-width:1200px;margin:0 auto;padding:72px 24px 96px;box-sizing:border-box}}

@@HP_NAV_STYLES@@

.pp-hero{{padding:clamp(40px,8vh,72px) 0 52px;text-align:center;max-width:720px;margin:0 auto}}
.pp-hero h1{{
  font-size:clamp(1.85rem,4vw,2.65rem);font-weight:800;letter-spacing:-.04em;
  line-height:1.12;margin-bottom:16px;
}}
.pp-hero p{{color:var(--pp-muted);font-size:1.05rem;line-height:1.6;max-width:52ch;margin:0 auto}}

.pp-section{{margin-top:clamp(48px,7vw,72px)}}
.pp-section-head{{text-align:center;max-width:560px;margin:0 auto 28px}}
.pp-section-head h2{{font-size:clamp(1.35rem,2.5vw,1.75rem);font-weight:700;letter-spacing:-.03em;margin-bottom:10px}}
.pp-section-head p{{color:var(--pp-muted);font-size:.98rem}}

.pp-pain{{
  border-radius:16px;border:1px solid var(--pp-line);
  background:var(--pp-card);padding:clamp(22px,3vw,32px) clamp(20px,3vw,36px);
  max-width:640px;margin:0 auto;
}}
.pp-pain h2{{font-size:1.25rem;font-weight:700;margin-bottom:14px}}
.pp-pain ul{{list-style:none;margin:0 0 18px;padding:0}}
[data-theme=light] .pp-pain ul{{color:#334155}}
.pp-pain li{{padding:8px 0 8px 26px;position:relative;color:var(--pp-muted)}}
.pp-pain li::before{{content:"—";position:absolute;left:0;color:#f87171;font-weight:700}}
.pp-pain .pp-pain-sol{{font-size:.98rem;color:var(--pp-muted);line-height:1.6}}
[data-theme=light] .pp-pain{{box-shadow:0 12px 40px -24px rgba(15,23,42,.15)}}

.pp-grid{{
  display:grid;gap:18px;
  grid-template-columns:repeat(auto-fill,minmax(220px,1fr));
  align-items:stretch;
}}
@media(min-width:1100px){{
  .pp-grid{{grid-template-columns:repeat(5,1fr);gap:14px}}
}}

.pp-card{{
  position:relative;border-radius:14px;border:1px solid var(--pp-line);
  background:var(--pp-card);padding:22px 18px 20px;
  display:flex;flex-direction:column;min-height:100%;
}}
[data-theme=light] .pp-card{{box-shadow:0 8px 30px -18px rgba(15,23,42,.12)}}
.pp-card--highlight{{
  border-color:rgba(94,106,210,.55);
  box-shadow:0 0 0 1px rgba(94,106,210,.15),0 20px 50px -20px rgba(79,70,229,.35);
  transform:translateY(-4px);
  z-index:2;
}}
.pp-badge{{
  position:absolute;top:-10px;left:50%;transform:translateX(-50%);
  font-size:.65rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
  padding:5px 12px;border-radius:99px;
  background:linear-gradient(135deg,#5e6ad2,#7c3aed);color:#fff;
}}
.pp-name{{font-size:1.1rem;font-weight:700;margin-bottom:6px}}
.pp-price-line{{margin-bottom:16px}}
.pp-price{{font-size:1.85rem;font-weight:800;letter-spacing:-.03em}}
.pp-price-period{{font-size:1rem;font-weight:500;color:var(--pp-muted);margin-left:2px}}
.pp-subhead{{font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--pp-muted);margin:14px 0 8px}}
.pp-list{{list-style:none;padding:0;margin:0 0 16px;flex:1}}
.pp-list li{{font-size:.84rem;padding:7px 0;color:#e5e7eb;border-bottom:1px solid rgba(255,255,255,.06)}}
[data-theme=light] .pp-list li{{color:#334155;border-bottom-color:var(--pp-line)}}
.pp-list--muted li{{color:var(--pp-muted);font-size:.8rem;border-bottom-style:dashed;opacity:.9}}
.pp-list--features li:last-child{{border-bottom:none}}

.pp-cta{{
  display:block;text-align:center;margin-top:auto;
  padding:11px 14px;border-radius:10px;font-size:.86rem;font-weight:600;
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

.pp-addons-grid{{
  display:grid;gap:14px;
  grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
}}
.pp-addon{{
  display:flex;align-items:center;justify-content:space-between;gap:14px;
  padding:18px 20px;border-radius:12px;border:1px solid var(--pp-line);
  background:var(--pp-card);
}}
[data-theme=light] .pp-addon{{box-shadow:0 6px 24px -16px rgba(15,23,42,.1)}}
.pp-addon-title{{font-size:.95rem;font-weight:600}}
.pp-addon-meta{{font-size:.86rem;color:var(--pp-muted);margin-top:4px}}
.pp-addon-price{{font-weight:700;color:#e5e7eb}}
[data-theme=light] .pp-addon-price{{color:#0f172a}}
.pp-addon-note{{font-weight:500}}
.pp-addon-btn{{
  flex-shrink:0;padding:8px 14px;border-radius:8px;border:1px solid var(--pp-line);
  background:transparent;color:var(--pp-muted);font-size:.78rem;font-weight:600;cursor:pointer;
}}
.pp-addon-btn:hover{{color:#e5e7eb;border-color:rgba(94,106,210,.5)}}
[data-theme=light] .pp-addon-btn:hover{{color:#0f172a}}

.pp-table-scroll{{overflow-x:auto;margin-top:8px;-webkit-overflow-scrolling:touch;border-radius:12px;border:1px solid var(--pp-line)}}
.pp-table{{width:100%;min-width:640px;border-collapse:collapse;font-size:.84rem}}
.pp-table th,.pp-table td{{padding:12px 14px;text-align:left;border-bottom:1px solid var(--pp-line);vertical-align:top}}
.pp-table thead th{{background:rgba(255,255,255,.04);font-weight:600}}
[data-theme=light] .pp-table thead th{{background:#f1f5f9}}
.pp-tcorner{{width:160px;color:var(--pp-muted);font-weight:600}}
.pp-th-name{{display:block;font-size:.9rem}}
.pp-th-price{{display:block;font-size:.75rem;color:var(--pp-muted);font-weight:500;margin-top:2px}}
.pp-table tbody th{{font-weight:500;color:var(--pp-muted);max-width:200px}}

.pp-trust{{text-align:center;padding:40px 20px 0}}
.pp-trust-line{{font-size:.92rem;color:var(--pp-muted);margin:8px 0}}


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
    <h1>{h_title}</h1>
    <p>{h_sub}</p>
  </header>

  <section class="pp-section" aria-labelledby="pain-title">
    <div class="pp-pain">
      <h2 id="pain-title">{pain_title}</h2>
      <ul>{pain_bullets}</ul>
      <p class="pp-pain-sol">{pain_sol}</p>
    </div>
  </section>

  <section class="pp-section" aria-labelledby="plans-title">
    <div class="pp-section-head">
      <h2 id="plans-title">Plans</h2>
      <p>Choose a tier. Upgrade or add capacity as your catalog grows.</p>
    </div>
    <div class="pp-grid">
{cards}
    </div>
  </section>

  <section class="pp-section" aria-labelledby="addons-title">
    <div class="pp-section-head">
      <h2 id="addons-title">Add-ons</h2>
      <p>Optional packs at checkout (placeholder — wire to Paddle / PayPro).</p>
    </div>
    <div class="pp-addons-grid">
{addons}
    </div>
  </section>

  <section class="pp-section" aria-labelledby="compare-title">
    <div class="pp-section-head">
      <h2 id="compare-title">Compare plans</h2>
      <p>Free through Pro. Enterprise includes everything custom.</p>
    </div>
{table}
  </section>

  <section class="pp-trust" aria-label="Trust">
{trust_lines}
  </section>

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
      if (console && console.debug) console.debug('[cartozo-pricing] plan CTA — integrate Paddle/PayPro here', payload);
    }};
  }}
  if (typeof window.cartozoPricing.onSelectAddon !== 'function') {{
    window.cartozoPricing.onSelectAddon = function (payload) {{
      if (console && console.debug) console.debug('[cartozo-pricing] add-on — integrate checkout here', payload);
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
    document.querySelectorAll('.pp-addon-btn').forEach(function (b) {{
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
