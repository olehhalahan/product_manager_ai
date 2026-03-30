"""
/how-it-works — 90+ landing page.
Design decisions:
  · Inter loaded from Google Fonts (proper typography)
  · Hero RIGHT = static batch-review product UI (always visible, no animation loop)
  · Real app components scoped under .af (app-frame): exact class names from main.py
  · Flow pipeline indicator showing Upload→Mapping→AI→Review→Export
  · Stripe aurora + rainbow gradient + shimmer button
  · Stripe stats strip (horizontal dividers)
  · Before/After centerpiece
  · Single dominant CTA throughout
"""
from __future__ import annotations
import html as html_module

from .public_nav import HP_FOOTER_CSS, HP_NAV_CSS, public_site_footer_html, public_site_nav_html, public_site_theme_toggle_script
from .seo import head_canonical_social


def build_how_it_works_html(
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
    seo_block = head_canonical_social(
        canonical_url=canonical_url,
        og_title=og_title,
        og_description=og_description,
        og_image=og_image,
        og_site_name=og_site_name,
        og_type="website",
    )
    mt = html_module.escape(meta_title)
    md = html_module.escape(meta_description)

    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
{gtm_head}
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{mt}</title>
<meta name="description" content="{md}"/>
{seo_block}<script>document.documentElement.setAttribute('data-theme',localStorage.getItem('hp-theme')||'dark')</script>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;450;500;600;700;800;900&display=swap" rel="stylesheet"/>
<link rel="stylesheet" href="/static/styles.css"/>
<style>
/* ── reset ───────────────────────────────────────── */
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{
  font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;
  background:#060711;color:#DCE0F2;
  overflow-x:hidden;-webkit-font-smoothing:antialiased;
  opacity:0;transition:opacity .48s ease;
}}
body.on{{opacity:1}}
/* light: pure white bg, concrete hex muted (5.8:1 on #FFF) */
[data-theme=light] body{{background:#FFFFFF;color:#0C0D1A}}
a{{text-decoration:none;color:inherit}}

/* ── tokens ──────────────────────────────────────── */
:root{{
  --ink:#DCE0F2; --muted:rgba(220,224,242,.5);
  --line:rgba(255,255,255,.08);
  --s1:rgba(255,255,255,.04); --s2:rgba(255,255,255,.08);
  --acc:#5E6AD2; --vi:#8B5CF6; --cy:#3DCFEF;
  --ok:#22C55E; --err:#EF4444; --warn:#F59E0B;
  --r:18px;
  --app-bg:#0B0F19; --app-fg:#E5E7EB;
  --app-line:rgba(255,255,255,.08);
}}
/* light: --muted as concrete hex → 5.8:1 contrast on #FFF ✓ WCAG AA */
[data-theme=light]{{
  --ink:#0C0D1A; --muted:#525466;
  --line:rgba(12,13,26,.12);
  --s1:#F5F6FA; --s2:#ECEEF7;
}}

/* ═══════════════════════════════════════
   STRIPE AURORA  (5 orb multicolor)
═══════════════════════════════════════ */
.aurora{{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}}
.aurora-orbs{{
  position:absolute;inset:-60% -30%;
  background:
    radial-gradient(ellipse 58% 52% at  8% 14%,rgba(94,106,210,.4),transparent 58%),
    radial-gradient(ellipse 46% 44% at 52% 40%,rgba(139,92,246,.18),transparent 56%),
    radial-gradient(ellipse 50% 44% at 88%  8%,rgba(61,207,239,.16),transparent 56%),
    radial-gradient(ellipse 44% 38% at 62% 98%,rgba(34,211,153,.09),transparent 54%),
    radial-gradient(ellipse 36% 32% at 16% 88%,rgba(251,191,36,.05),transparent 52%);
  animation:auroraShift 28s ease-in-out infinite alternate;
}}
@keyframes auroraShift{{
  0%  {{transform:translate(0%,0%) scale(1)}}
  33% {{transform:translate(-2%,1.5%) scale(1.03)}}
  66% {{transform:translate(1.5%,-1%) scale(1.02)}}
  100%{{transform:translate(-1%,2.5%) scale(1.04)}}
}}
.aurora-dots{{
  position:absolute;inset:0;
  background-image:radial-gradient(circle,rgba(255,255,255,.05) 1px,transparent 1px);
  background-size:42px 42px;
  mask-image:radial-gradient(ellipse 82% 58% at 50% 22%,#000 10%,transparent 70%);
}}
[data-theme=light] .aurora-dots{{background-image:radial-gradient(circle,rgba(12,13,26,.042) 1px,transparent 1px)}}
.aurora-vig{{
  position:absolute;inset:0;
  background:radial-gradient(ellipse 90% 72% at 50% 38%,transparent 44%,rgba(6,7,17,.72) 100%);
}}
[data-theme=light] .aurora-vig{{background:radial-gradient(ellipse 92% 76% at 50% 34%,transparent 50%,rgba(255,255,255,.92) 100%)}}
/* aurora orbs barely visible in light — page content is the focus */
[data-theme=light] .aurora-orbs{{opacity:.14}}
@@HP_NAV_STYLES@@

/* ── layout ──────────────────────────────────────── */
.w{{position:relative;z-index:1;max-width:1160px;margin:0 auto;padding:58px 28px 100px;box-sizing:border-box}}

/* ── scroll reveal ───────────────────────────────── */
.rv{{opacity:0;transform:translateY(22px);transition:opacity .7s cubic-bezier(.22,1,.36,1),transform .7s cubic-bezier(.22,1,.36,1)}}
.rv.in{{opacity:1;transform:none}}
.rv.d1{{transition-delay:.08s}}.rv.d2{{transition-delay:.16s}}
.rv.d3{{transition-delay:.24s}}.rv.d4{{transition-delay:.32s}}.rv.d5{{transition-delay:.4s}}
.rv.d6{{transition-delay:.48s}}.rv.d7{{transition-delay:.56s}}.rv.d8{{transition-delay:.64s}}
/* hero visual has its own slide-in from the right */
.rv-right{{opacity:0;transform:translateX(40px);transition:opacity .75s cubic-bezier(.22,1,.36,1),transform .75s cubic-bezier(.22,1,.36,1);transition-delay:.1s}}
.rv-right.in{{opacity:1;transform:none}}

/* ═══════════════════════════════════════
   BUTTONS — Stripe shimmer
═══════════════════════════════════════ */
.btn{{
  display:inline-flex;align-items:center;justify-content:center;gap:8px;
  padding:13px 24px;border-radius:10px;
  font-size:.9rem;font-weight:600;letter-spacing:-.015em;
  border:none;cursor:pointer;position:relative;overflow:hidden;
  transition:transform .2s,box-shadow .2s,filter .2s;
}}
.btn:hover{{transform:translateY(-2px)}}
.btn-primary{{
  color:#fff;
  background:linear-gradient(135deg,#5E6AD2,#7C3AED 55%,#4F46E5);
  box-shadow:0 14px 44px -10px rgba(94,106,210,.62),0 0 0 1px rgba(255,255,255,.08) inset;
}}
.btn-primary:hover{{
  box-shadow:0 20px 56px -10px rgba(94,106,210,.76),0 0 0 1px rgba(255,255,255,.12) inset;
  filter:brightness(1.07);
}}
/* Stripe shimmer sweep */
.btn-primary::after{{
  content:'';position:absolute;inset:0;
  background:linear-gradient(108deg,transparent 28%,rgba(255,255,255,.26),transparent 70%);
  transform:translateX(-130%);
  animation:bShimmer 3s ease-in-out infinite;
  animation-delay:1.4s;
}}
@keyframes bShimmer{{to{{transform:translateX(230%)}}}}
.btn-ghost{{
  background:var(--s1);color:var(--ink);border:1px solid var(--line);
}}
[data-theme=light] .btn-ghost{{background:#fff}}
.btn-ghost:hover{{background:var(--s2)}}

/* ═══════════════════════════════════════
   § 1  HERO
═══════════════════════════════════════ */
.hero{{
  display:grid;grid-template-columns:1fr 1.18fr;
  gap:clamp(20px,3.2vw,48px);align-items:start;
  padding:clamp(12px,2.5vh,36px) 0 clamp(16px,3.5vh,44px);
}}
@media(max-width:980px){{.hero{{grid-template-columns:1fr;gap:32px;padding:24px 0 40px}}}}
.hero-copy{{
  max-width:544px;
  display:flex;flex-direction:column;align-items:stretch;
  gap:clamp(14px,2.2vw,26px);
  isolation:isolate;
}}

.eyebrow{{
  display:inline-flex;align-items:center;gap:10px;align-self:flex-start;
  padding:7px 16px;border-radius:99px;margin:0;
  background:linear-gradient(135deg,rgba(94,106,210,.18),rgba(139,92,246,.11));
  border:1px solid rgba(139,92,246,.28);
  font-size:.69rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--cy);
}}
.eyebrow-dot{{
  width:7px;height:7px;border-radius:50%;
  background:linear-gradient(135deg,var(--acc),var(--cy));
  box-shadow:0 0 10px rgba(61,207,239,.7);
  animation:dotPulse 2.8s ease-in-out infinite;
}}
@keyframes dotPulse{{0%,100%{{transform:scale(1);opacity:1}}50%{{transform:scale(1.24);opacity:.6}}}}

.h1{{
  font-size:clamp(2.3rem,5.4vw,3.9rem);
  font-weight:820;letter-spacing:-.056em;line-height:1.04;margin:0;
}}
/* two-tone: muted first line, vivid second */
.h1 .dim{{
  display:block;color:rgba(220,224,242,.34);
  font-weight:380;letter-spacing:-.038em;
}}
/* large text — WCAG 3:1 applies; #767892 gives 3.8:1 on #FFF ✓ */
[data-theme=light] .h1 .dim{{color:#767892}}
/* animated rainbow gradient phrase — Stripe signature */
.h1 .rainbow{{
  display:block;
  background:linear-gradient(110deg,#818cf8 0%,#3DCFEF 32%,#22C55E 58%,#a78bfa 86%,#818cf8 100%);
  background-size:220% auto;
  -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;
  animation:rainbowMove 6s linear infinite;
}}
@keyframes rainbowMove{{to{{background-position:220% center}}}}

/* ── light-theme: replace #3DCFEF (2:1 on white) with accessible teal ───
   #016E8C = 5.65:1 on #FFF ✓  |  #15803D = 5.7:1 ✓  |  #DC2626 = 5.9:1 ✓
─────────────────────────────────────────────────────────────────────── */
[data-theme=light] .eyebrow{{
  color:#016E8C;
  border-color:rgba(1,110,140,.3);
  background:linear-gradient(135deg,rgba(79,70,229,.09),rgba(1,110,140,.09));
}}
[data-theme=light] .eyebrow-dot{{
  background:linear-gradient(135deg,#4F46E5,#016E8C);
  box-shadow:0 0 8px rgba(1,110,140,.5);
}}
[data-theme=light] .s-label{{color:#016E8C}}
[data-theme=light] .finale-label{{color:#016E8C}}
[data-theme=light] .pipe-node.active{{
  color:#016E8C;
  border-color:rgba(1,110,140,.4);
  background:linear-gradient(135deg,rgba(79,70,229,.1),rgba(1,110,140,.09));
}}
[data-theme=light] .ba-th.mid{{color:#016E8C}}
[data-theme=light] .ba-arrow{{color:#016E8C;background:rgba(1,110,140,.05)}}
/* dark-green for "good" tags in light (--ok #22C55E = 2.9:1, fails) */
[data-theme=light] .ba-th.good{{color:#15803D;background:rgba(21,128,61,.07)}}
[data-theme=light] .ba-fix{{background:rgba(21,128,61,.12);border-color:rgba(21,128,61,.28);color:#15803D}}
/* dark-red for error tags in light (--err #EF4444 = 3.8:1 — below 4.5) */
[data-theme=light] .ba-th.bad{{color:#DC2626;background:rgba(220,38,38,.07)}}
/* nav backdrop */
[data-theme=light] .nav{{border-bottom-color:rgba(12,13,26,.1)}}

[data-theme=light] .h1 .rainbow{{
  background:linear-gradient(110deg,#4F46E5 0%,#0891b2 32%,#059669 58%,#7C3AED 86%,#4F46E5 100%);
  background-size:220% auto;animation:rainbowMove 6s linear infinite;
  -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;
}}

/* one calm “value” card — less visual noise than stacked orange + black */
.hero-support{{
  padding:16px 20px;border-radius:14px;border:1px solid var(--line);
  background:var(--s1);max-width:100%;
  display:flex;flex-direction:column;gap:14px;
}}
[data-theme=light] .hero-support{{
  background:#f4f6fb;border-color:rgba(12,13,26,.09);
  box-shadow:0 1px 0 rgba(255,255,255,.9) inset;
}}
.hero-kicker{{
  display:block;font-size:.7rem;font-weight:700;letter-spacing:.11em;
  text-transform:uppercase;color:var(--muted);margin-bottom:2px;
}}
.hero-punch{{
  margin:0;font-size:clamp(.97rem,1.5vw,1.05rem);line-height:1.62;font-weight:500;
  color:var(--muted);letter-spacing:-.01em;
}}
.hero-punch strong{{color:var(--ink);font-weight:700}}
.hero-money{{
  margin:0;padding-top:14px;border-top:1px solid var(--line);
  font-size:clamp(1rem,1.55vw,1.08rem);line-height:1.58;font-weight:600;
  color:var(--ink);letter-spacing:-.02em;
}}
.hero-money strong{{font-weight:700;color:var(--ink)}}
.hero-actions{{display:flex;flex-direction:column;align-items:flex-start;gap:12px}}
.hero-ctas{{display:flex;flex-wrap:wrap;gap:10px 12px;align-items:center;margin:0}}
[data-theme=light] .hero .btn-primary{{
  box-shadow:0 10px 28px -10px rgba(79,70,229,.42),0 0 0 1px rgba(255,255,255,.1) inset;
}}
[data-theme=light] .hero .btn-primary:hover{{
  box-shadow:0 14px 34px -10px rgba(79,70,229,.5),0 0 0 1px rgba(255,255,255,.12) inset;
}}
.hero-friction{{
  margin:0;font-size:.78rem;font-weight:500;color:var(--muted);letter-spacing:.02em;line-height:1.45;
}}
/* proof: separated scan-friendly list */
.hero-proof{{
  padding-top:clamp(12px,1.8vw,18px);margin:0;border-top:1px solid var(--line);
}}
.hero-proof .hero-kicker{{margin-bottom:11px}}
.trust-chips{{display:flex;flex-direction:column;align-items:flex-start;gap:11px;margin:0;padding:0}}
.t-chip{{
  display:flex;align-items:flex-start;gap:10px;
  font-size:.8rem;color:var(--muted);font-weight:450;line-height:1.45;max-width:40rem;
}}
.t-chip strong{{color:var(--ink);font-weight:600}}
.t-chip-dot{{
  width:5px;height:5px;border-radius:50%;flex-shrink:0;
  background:var(--ok);box-shadow:0 0 8px rgba(34,197,94,.6);
}}

/* ── product window (hero right) ─────────────────── */
/* Shows batch-review end-state — real app look */
/* layered indigo/slate shadow — avoids “muddy” pure-black bloom */
.pw-wrap{{
  position:relative;
  filter:
    drop-shadow(0 22px 44px rgba(79,70,229,.22))
    drop-shadow(0 8px 20px rgba(30,27,75,.14));
}}
/* Right column: .ann-tl uses negative top so badge straddles card corner; offset .pw-wrap so badge still lines up with .h1 first line */
@media(min-width:981px){{
  .hero .pw-wrap{{
    margin-top:max(0px,calc(14px + 0.69rem * 1.35 + clamp(14px,2.2vw,26px) + 14px));
  }}
}}
.pw{{
  border-radius:16px;overflow:hidden;
  border:1px solid rgba(255,255,255,.1);
  background:var(--app-bg);
  box-shadow:
    0 0 0 1px rgba(255,255,255,.06) inset,
    0 28px 56px -22px rgba(79,70,229,.32),
    0 12px 28px -12px rgba(15,23,42,.38);
}}
/* product window is always dark — shows the real app UI */

/* window chrome bar (macOS style) */
.pw-chrome{{
  display:flex;align-items:center;gap:10px;
  padding:10px 16px;
  background:rgba(0,0,0,.28);border-bottom:1px solid rgba(255,255,255,.07);
}}
.pw-dots{{display:flex;gap:5px}}
.pw-dots span{{width:10px;height:10px;border-radius:50%}}
.pw-dots span:nth-child(1){{background:#ff5f56}}
.pw-dots span:nth-child(2){{background:#ffbd2e}}
.pw-dots span:nth-child(3){{background:#27c93f}}
.pw-url{{
  flex:1;text-align:center;
  font-size:.68rem;font-family:ui-monospace,monospace;
  color:rgba(220,224,242,.4);
}}
.pw-status{{
  font-size:.65rem;font-weight:700;padding:2px 9px;border-radius:5px;
  background:rgba(34,197,94,.14);border:1px solid rgba(34,197,94,.28);color:var(--ok);
}}

/* window content = scoped real app UI */
.pw-body{{padding:12px 14px 14px;max-height:min(360px,min(44vw,54vh));overflow:hidden}}
@media(min-width:981px) and (max-height:820px){{
  .pw-body{{max-height:min(300px,50vh)}}
  .hero .h1{{font-size:clamp(2.05rem,4.5vw,3.2rem)}}
  .trust-chips{{gap:8px}}
}}

/* annotation badges */
.ann{{
  position:absolute;z-index:5;
  display:flex;align-items:center;gap:10px;
  padding:10px 15px;border-radius:13px;
  background:rgba(6,7,17,.92);
  border:1px solid rgba(255,255,255,.14);
  backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);
  box-shadow:0 10px 36px rgba(0,0,0,.45);
  white-space:nowrap;
}}
[data-theme=light] .ann{{background:rgba(244,245,251,.96);border-color:rgba(12,13,26,.15);box-shadow:0 8px 28px rgba(12,13,26,.16)}}
.ann-ico{{font-size:.9rem}}
.ann-main{{font-size:.78rem;font-weight:700;color:#fff;line-height:1.2}}
[data-theme=light] .ann-main{{color:#0C0D1A}}
.ann-sub{{font-size:.64rem;color:var(--muted)}}
.ann-tl{{top:-14px;left:-12px;animation:annEnter .55s .9s cubic-bezier(.22,1,.36,1) both,annBounce 4s 1.5s ease-in-out infinite}}
.ann-br{{bottom:-14px;right:-12px;animation:annEnter .55s 1.3s cubic-bezier(.22,1,.36,1) both,annBounce 4s 1.9s ease-in-out infinite}}
@keyframes annEnter{{from{{opacity:0;transform:translateY(10px) scale(.91)}}to{{opacity:1;transform:none}}}}
@keyframes annBounce{{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(-5px)}}}}

/* ═══════════════════════════════════════
   REAL APP COMPONENTS  (scoped .af)
   ALWAYS DARK — intentionally shows the
   product's dark UI (like Linear/Vercel do).
   Class names match main.py exactly.
═══════════════════════════════════════ */
.af{{
  background:var(--app-bg);color:var(--app-fg);
  font-family:'Inter',-apple-system,sans-serif;
  font-size:13px;line-height:1.45;
  -webkit-font-smoothing:antialiased;
  border-radius:inherit;
}}
/* review summary bar */
.af .review-summary-bar{{
  display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px;
  padding:9px 13px;margin-bottom:12px;
  background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08);border-radius:9px;
  font-size:.72rem;
}}
.af .review-summary-lead{{color:rgba(255,255,255,.9);font-weight:600}}
.af .review-summary-lead strong{{color:#fff;font-weight:700}}
.af .review-summary-meta{{font-size:.62rem;color:rgba(255,255,255,.45);text-transform:uppercase;letter-spacing:.04em}}
.af .review-summary-meta strong{{font-weight:700;text-transform:none;color:rgba(255,255,255,.85);margin:0 1px}}
.af .review-summary-meta .c-review{{color:var(--warn)}}
.af .review-summary-meta .c-fail{{color:var(--err)}}
.af .m{{opacity:.4;font-weight:400;margin:0 2px}}
/* table */
.af .table-container{{
  background:rgba(255,255,255,.025);border:1px solid rgba(255,255,255,.09);
  border-radius:11px;overflow:hidden;margin-bottom:12px;
}}
.af table{{width:100%;border-collapse:collapse;font-size:.72rem}}
/* global styles.css targets thead/tbody tr without .af — must override */
.af thead{{background:rgba(255,255,255,.03)!important}}
.af th{{
  text-align:left;padding:8px 11px;
  font-size:.6rem;font-weight:600;text-transform:uppercase;letter-spacing:.05em;
  color:rgba(255,255,255,.42)!important;background:rgba(255,255,255,.03)!important;
  border-bottom:1px solid rgba(255,255,255,.08)!important;
}}
.af tbody tr,.af tbody tr:nth-child(even){{background:transparent!important}}
.af tbody tr:hover{{background:transparent!important}}
/* explicit transparent + td hover — block zebra from global table rules */
.af tr{{background:transparent!important}}
.af td{{
  padding:9px 11px;border-bottom:1px solid rgba(255,255,255,.06)!important;vertical-align:middle;
  color:rgba(255,255,255,.72)!important;background:transparent!important;
}}
.af tr:last-child td{{border-bottom:none}}
.af tr:hover td{{background:rgba(255,255,255,.04)!important}}
/* content cells */
.af .new-content{{color:var(--app-fg);font-weight:500}}
.af .cell-with-gmc{{display:flex;flex-direction:column;gap:4px}}
.af .gmc-tags{{display:flex;flex-wrap:wrap;gap:3px;margin-top:2px}}
.af .gmc-tag{{display:inline-flex;align-items:center;gap:3px;padding:2px 7px;border-radius:4px;font-size:.63rem;font-weight:600;white-space:nowrap}}
.af .gmc-tag-fixed{{background:rgba(34,197,94,.14);color:#4ade80}}
.af .gmc-tag-err{{background:rgba(239,68,68,.14);color:#f87171}}
.af .gmc-tag-warn{{background:rgba(245,158,11,.14);color:#fbbf24}}
/* scores */
.af .score-high{{display:inline-block;padding:2px 8px;border-radius:5px;font-size:.67rem;font-weight:700;background:rgba(34,197,94,.16);color:#4ade80}}
.af .score-mid{{display:inline-block;padding:2px 8px;border-radius:5px;font-size:.67rem;font-weight:700;background:rgba(251,191,36,.16);color:#fbbf24}}
.af .pill-done{{display:inline-block;padding:2px 8px;border-radius:5px;font-size:.65rem;font-weight:600;background:rgba(255,255,255,.1);color:rgba(255,255,255,.78)}}
.af .mono{{font-family:ui-monospace,monospace;font-size:.67rem;color:rgba(255,255,255,.42)}}
/* action buttons */
.af .header-actions{{display:flex;gap:8px;flex-wrap:wrap}}
.af .btn{{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border-radius:8px;font-size:.78rem;font-weight:600;cursor:default;border:none;letter-spacing:-.01em}}
.af .btn-merchant-push{{background:linear-gradient(135deg,#22D3EE,#06b6d4);color:#031c22;box-shadow:0 2px 14px rgba(6,182,212,.35);animation:gmcGlow 2.6s ease-in-out infinite}}
@keyframes gmcGlow{{0%,100%{{box-shadow:0 2px 14px rgba(6,182,212,.3)}}50%{{box-shadow:0 4px 26px rgba(6,182,212,.58)}}}}
.af .btn-primary{{background:rgba(255,255,255,.9);color:#0a0a0a}}
/* mapping */
.af .col-name{{font-weight:600;color:var(--app-fg);font-size:.73rem}}
.af .sample{{color:rgba(255,255,255,.36);font-family:ui-monospace,monospace;font-size:.65rem;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.af select{{width:100%;padding:5px 10px;font-size:.7rem;border:1px solid rgba(255,255,255,.14);border-radius:6px;background:rgba(255,255,255,.05);color:var(--app-fg);cursor:default}}
/* options box */
.af .options-box{{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:11px 13px;margin-top:10px}}
.af .options-title{{font-size:.74rem;font-weight:600;color:rgba(255,255,255,.82);margin-bottom:8px}}
.af .checkboxes{{display:flex;gap:14px;flex-wrap:wrap}}
.af .checkbox-label{{display:flex;align-items:center;gap:7px;font-size:.72rem;color:rgba(255,255,255,.7);cursor:default}}
.af .checkbox-label input{{width:13px;height:13px;accent-color:#4F46E5;cursor:default}}
/* processing loader */
.af .loader{{text-align:center;padding:22px 16px;background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.08);border-radius:14px}}
.af .spinner{{width:36px;height:36px;border:3px solid rgba(255,255,255,.1);border-top-color:#22D3EE;border-radius:50%;margin:0 auto 12px;animation:spin 1s linear infinite}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.af .thinking{{font-size:.86rem;font-weight:600;color:var(--app-fg)}}
.af .thinking-sub{{font-size:.72rem;color:rgba(255,255,255,.5);margin-top:4px}}
.af .progress{{height:4px;background:rgba(255,255,255,.08);border-radius:99px;overflow:hidden;margin-top:16px}}
.af .progress-fill{{height:100%;background:linear-gradient(90deg,#4F46E5,#22D3EE);border-radius:99px;width:68%}}
/* gmc top-issues */
.af .gmc-top-issues{{border-top:1px solid rgba(255,255,255,.06);margin-top:10px;padding-top:10px}}
.af .gmc-ti-label{{font-size:.62rem;font-weight:600;color:rgba(255,255,255,.4);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px}}
.af .gmc-ti-list{{list-style:none;padding:0;display:flex;flex-direction:column;gap:5px}}
.af .gmc-ti-item{{display:flex;align-items:center;gap:8px;padding:6px 9px;border-radius:6px;background:rgba(255,255,255,.025);font-size:.74rem}}
.af .gmc-ti-icon{{flex-shrink:0;font-size:.66rem;width:14px;text-align:center}}
.af .gmc-ti-err .gmc-ti-icon{{color:#f87171}}
.af .gmc-ti-warn .gmc-ti-icon{{color:#fbbf24}}
.af .gmc-ti-text{{flex:1;color:rgba(255,255,255,.78)}}
.af .gmc-ti-count{{flex-shrink:0;font-size:.64rem;font-weight:700;padding:1px 7px;border-radius:8px;background:rgba(255,255,255,.07)}}
.af .gmc-ti-err .gmc-ti-count{{background:rgba(239,68,68,.14);color:#f87171}}
.af .gmc-ti-warn .gmc-ti-count{{background:rgba(245,158,11,.14);color:#fbbf24}}
/* dropzone */
.af .dropzone{{border:2px dashed rgba(255,255,255,.2);border-radius:12px;padding:22px 16px;text-align:center}}
.af .dropzone.has-file{{border-color:#4F46E5;border-style:solid;background:rgba(79,70,229,.08)}}
.af .dropzone-icon{{font-size:1.5rem;margin-bottom:7px;opacity:.85}}
.af .dropzone.has-file .dropzone-icon{{color:#818cf8}}
.af .dropzone-text{{font-size:.78rem;color:rgba(255,255,255,.62)}}
.af .dropzone-text strong{{color:var(--app-fg)}}
.af .dropzone.has-file .dropzone-text{{color:#818cf8;font-weight:600}}
.af .dropzone-filename{{margin-top:6px;font-size:.75rem;font-weight:500;color:rgba(255,255,255,.82)}}
.af .dropzone-hint{{font-size:.66rem;color:rgba(255,255,255,.4);margin-top:4px}}
.af .subtitle{{font-size:.78rem;color:rgba(255,255,255,.56);margin-bottom:12px;line-height:1.5}}

/* ═══════════════════════════════════════
   STRIPE STATS STRIP
═══════════════════════════════════════ */
.stats-strip{{
  display:flex;align-items:stretch;justify-content:center;flex-wrap:wrap;
  border-top:1px solid var(--line);border-bottom:1px solid var(--line);
  position:relative;margin:clamp(52px,8vw,80px) 0;
}}
.stats-strip::before{{
  content:'';position:absolute;top:-1px;left:10%;right:10%;height:1px;
  background:linear-gradient(90deg,transparent,rgba(94,106,210,.6),rgba(61,207,239,.45),rgba(139,92,246,.4),transparent);
}}
.stat-item{{
  flex:1;min-width:160px;text-align:center;
  padding:clamp(24px,3.5vw,40px) clamp(16px,2.5vw,36px);position:relative;
}}
.stat-item+.stat-item::before{{
  content:'';position:absolute;left:0;top:18%;bottom:18%;width:1px;
  background:linear-gradient(180deg,transparent,var(--line),transparent);
}}
@media(max-width:560px){{
  .stat-item{{min-width:45%;border-bottom:1px solid var(--line)}}
  .stat-item:nth-child(odd)+.stat-item::before{{display:none}}
}}
.stat-n{{
  font-size:clamp(2rem,3.8vw,2.6rem);font-weight:800;letter-spacing:-.055em;line-height:1.08;margin-bottom:6px;
  background:linear-gradient(140deg,#fff 12%,var(--cy) 100%);
  -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;
}}
[data-theme=light] .stat-n{{background:linear-gradient(140deg,#0C0D1A,#0891b2);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}}
.stat-t{{font-size:.83rem;color:var(--muted);font-weight:440;max-width:22ch;margin:0 auto;line-height:1.42}}
/* credibility strip: short headline, not giant metrics */
.stat-n.stat-lead{{
  font-size:clamp(1.08rem,2.1vw,1.38rem);font-weight:780;letter-spacing:-.028em;line-height:1.22;margin-bottom:8px;
  background:none;-webkit-text-fill-color:var(--ink);color:var(--ink);
}}
[data-theme=light] .stat-n.stat-lead{{background:none;-webkit-text-fill-color:var(--ink);color:var(--ink)}}
.flow-summary{{
  font-size:clamp(1.02rem,1.9vw,1.14rem);font-weight:650;color:var(--ink);
  letter-spacing:-.02em;margin-bottom:22px;padding:14px 18px;border-radius:12px;
  border:1px solid var(--line);background:var(--s1);text-align:center;
}}
.why-list{{list-style:none;margin:0 0 20px;padding:0;max-width:52ch}}
.why-list li{{
  position:relative;padding:12px 0 12px 28px;border-bottom:1px solid var(--line);
  font-size:1.02rem;line-height:1.55;color:var(--muted);
}}
.why-list li:last-child{{border-bottom:none}}
.why-list li::before{{
  content:'\\2022';position:absolute;left:6px;top:.85em;color:var(--acc);font-weight:900;font-size:1.1rem;line-height:1;
}}
.why-close{{font-size:1.12rem;font-weight:650;color:var(--ink);max-width:52ch;line-height:1.5}}

/* ═══════════════════════════════════════
   § 2  BEFORE / AFTER
═══════════════════════════════════════ */
.section{{margin-bottom:clamp(64px,10vw,96px)}}
/* Stripe gradient separator line */
.section::before{{
  content:'';display:block;height:1px;margin-bottom:clamp(36px,5vw,56px);
  background:linear-gradient(90deg,transparent 4%,rgba(94,106,210,.56),rgba(61,207,239,.42),rgba(139,92,246,.32),transparent 96%);
}}
.s-label{{font-size:.7rem;font-weight:700;letter-spacing:.13em;text-transform:uppercase;color:var(--cy);margin-bottom:14px;display:block}}
.s-h{{font-size:clamp(1.9rem,3.6vw,2.6rem);font-weight:780;letter-spacing:-.052em;line-height:1.08;margin-bottom:12px;color:var(--ink)}}
.s-sub{{font-size:1.02rem;color:var(--muted);line-height:1.68;font-weight:420;max-width:52ch;margin-bottom:clamp(26px,3.5vw,42px)}}

.ba{{
  border-radius:22px;overflow:hidden;border:1px solid var(--line);
  background:linear-gradient(170deg,var(--s1),rgba(255,255,255,.01));
  box-shadow:0 40px 96px -44px rgba(0,0,0,.8),0 0 0 1px rgba(255,255,255,.04) inset;
  position:relative;
}}
[data-theme=light] .ba{{background:#fff;box-shadow:0 24px 64px -32px rgba(12,13,26,.18)}}
.ba::before{{
  content:'';position:absolute;top:0;left:0;right:0;height:1px;z-index:2;
  background:linear-gradient(90deg,transparent 4%,rgba(94,106,210,.65),rgba(61,207,239,.5),rgba(34,211,153,.35),transparent 96%);
}}
.ba-head{{display:grid;grid-template-columns:1fr 52px 1fr;border-bottom:1px solid var(--line)}}
.ba-th{{padding:13px 20px;font-size:.7rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase}}
.ba-th.bad{{color:var(--err);background:rgba(239,68,68,.07)}}
.ba-th.good{{color:var(--ok);background:rgba(34,197,94,.07)}}
.ba-th.mid{{
  display:flex;align-items:center;justify-content:center;
  border-left:1px solid var(--line);border-right:1px solid var(--line);
  font-size:.65rem;font-weight:800;letter-spacing:.05em;color:var(--cy);
}}
.ba-row{{display:grid;grid-template-columns:1fr 52px 1fr;border-bottom:1px solid var(--line)}}
.ba-row:last-child{{border-bottom:none}}
.ba-cell{{padding:16px 20px;font-size:.9rem;line-height:1.5}}
.ba-cell.bad{{background:rgba(239,68,68,.04);color:var(--muted)}}
.ba-cell.bad .v{{font-family:ui-monospace,monospace;font-size:.83rem}}
.ba-cell.good{{background:rgba(34,197,94,.05);color:var(--ink);font-weight:500}}
.ba-cell.good .v{{font-size:.86rem;line-height:1.42}}
.ba-arrow{{
  display:flex;align-items:center;justify-content:center;
  border-left:1px solid var(--line);border-right:1px solid var(--line);
  background:rgba(61,207,239,.04);color:var(--cy);font-weight:700;font-size:.95rem;
}}
.ba-fix{{
  display:inline-block;margin-top:6px;
  font-size:.62rem;font-weight:700;padding:2px 9px;border-radius:5px;
  background:rgba(34,197,94,.14);border:1px solid rgba(34,197,94,.28);color:var(--ok);
}}
@media(max-width:660px){{
  .ba-head,.ba-row{{grid-template-columns:1fr}}
  .ba-arrow,.ba-th.mid{{height:28px;border:none;border-top:1px solid var(--line);font-size:.8rem}}
  .ba-cell.bad{{border-bottom:none}}
}}

/* ═══════════════════════════════════════
   § 3  FLOW — pipeline indicator + 4 steps
═══════════════════════════════════════ */
/* horizontal pipeline (like Webflow/Vercel) */
.pipeline{{
  display:flex;align-items:center;gap:0;margin-bottom:44px;
  overflow-x:auto;padding-bottom:4px;
}}
.pipe-node{{
  display:flex;flex-direction:column;align-items:center;gap:5px;
  padding:10px 16px;border-radius:10px;
  background:var(--s1);border:1px solid var(--line);
  font-size:.74rem;font-weight:600;color:var(--ink);
  white-space:nowrap;flex-shrink:0;
  transition:border-color .22s,background .22s;
}}
.pipe-node.active{{
  background:linear-gradient(135deg,rgba(94,106,210,.18),rgba(61,207,239,.1));
  border-color:rgba(94,106,210,.4);
  color:var(--cy);
}}
.pipe-node em{{font-style:normal;font-size:.6rem;color:var(--muted);font-weight:450;font-family:ui-monospace,monospace}}
.pipe-track{{
  flex:1;min-width:24px;max-width:52px;height:2px;
  background:var(--line);flex-shrink:0;position:relative;overflow:hidden;border-radius:2px;
}}
.pipe-shine{{
  position:absolute;left:0;top:0;bottom:0;width:44%;
  background:linear-gradient(90deg,transparent,rgba(61,207,239,.35),transparent);
  animation:pipeShine 2.4s ease-in-out infinite;
}}
.pipe-track:nth-child(4) .pipe-shine{{animation-delay:.3s}}
.pipe-track:nth-child(6) .pipe-shine{{animation-delay:.6s}}
.pipe-track:nth-child(8) .pipe-shine{{animation-delay:.9s}}
@keyframes pipeShine{{0%{{transform:translateX(-100%);opacity:0}}30%{{opacity:1}}100%{{transform:translateX(280%);opacity:0}}}}

.grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
@media(max-width:700px){{.grid-2{{grid-template-columns:1fr}}}}

/* step card */
.sc{{
  border-radius:var(--r);border:1px solid var(--line);
  background:var(--s1);padding:26px 24px 22px;
  position:relative;overflow:hidden;
  box-shadow:0 20px 64px -28px rgba(0,0,0,.7);
  transition:border-color .25s,box-shadow .25s;
}}
[data-theme=light] .sc{{background:#fff;box-shadow:0 12px 36px -20px rgba(12,13,26,.14);border-color:rgba(12,13,26,.1)}}
/* step number: dark mode uses near-invisible white gradient — in light use solid muted */
[data-theme=light] .sc-num{{background:linear-gradient(135deg,rgba(12,13,26,.1),rgba(12,13,26,.06));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}}
.sc:hover{{border-color:rgba(94,106,210,.36);box-shadow:0 26px 78px -28px rgba(0,0,0,.78),0 0 0 1px rgba(94,106,210,.2) inset}}
.sc::before{{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,rgba(94,106,210,.5),rgba(61,207,239,.38),transparent);opacity:0;transition:opacity .25s}}
.sc::after{{content:'';position:absolute;inset:0;pointer-events:none;background:radial-gradient(ellipse 68% 52% at 50% 0%,rgba(94,106,210,.09),transparent 62%);opacity:0;transition:opacity .25s}}
.sc:hover::before,.sc:hover::after{{opacity:1}}
/* number lights up on hover */
.sc-num{{
  font-size:3rem;font-weight:800;letter-spacing:-.065em;line-height:1;margin-bottom:14px;
  background:linear-gradient(135deg,rgba(220,224,242,.14),rgba(220,224,242,.05));
  -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;
  user-select:none;transition:background .25s;
}}
.sc:hover .sc-num{{background:linear-gradient(135deg,var(--acc),var(--vi),var(--cy));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}}
.sc-title{{font-size:1.08rem;font-weight:700;letter-spacing:-.03em;margin-bottom:7px;color:var(--ink)}}
.sc-desc{{font-size:.9rem;color:var(--muted);line-height:1.64;margin-bottom:18px;max-width:38ch}}

/* ── mini window chrome for each step ── */
/* always dark — shows real app preview regardless of page theme */
.mw{{border-radius:11px;border:1px solid rgba(255,255,255,.1);overflow:hidden;background:#0B0F19}}
[data-theme=light] .mw{{border-color:rgba(0,0,0,.14);box-shadow:0 4px 16px rgba(0,0,0,.15)}}
.mw-bar{{display:flex;align-items:center;gap:7px;padding:8px 11px;border-bottom:1px solid rgba(255,255,255,.07);background:rgba(0,0,0,.22)}}
.mw-dots{{display:flex;gap:4px}}
.mw-dots i{{width:7px;height:7px;border-radius:50%;list-style:none}}
.mw-dots i:nth-child(1){{background:#ff5f56}}.mw-dots i:nth-child(2){{background:#ffbd2e}}.mw-dots i:nth-child(3){{background:#27c93f}}
.mw-url{{flex:1;text-align:center;font-size:.6rem;font-family:ui-monospace,monospace;color:rgba(220,224,242,.42)}}
.mw-body{{padding:12px 13px}}

/* ═══════════════════════════════════════
   § 4  FINALE
═══════════════════════════════════════ */
.finale{{
  padding:clamp(56px,10vw,96px) clamp(24px,6vw,68px);
  border-radius:24px;text-align:center;position:relative;overflow:hidden;
  border:1px solid rgba(94,106,210,.28);
  background:
    radial-gradient(ellipse 90% 118% at 50% -8%,rgba(94,106,210,.25),transparent 54%),
    radial-gradient(ellipse 60% 78% at 96% 96%,rgba(61,207,239,.12),transparent 54%),
    radial-gradient(ellipse 50% 58% at 4%  90%,rgba(139,92,246,.1),transparent 54%),
    rgba(0,0,0,.48);
  box-shadow:0 52px 104px -54px rgba(79,70,229,.54);
}}
[data-theme=light] .finale{{background:radial-gradient(ellipse 88% 112% at 50% -16%,rgba(94,106,210,.13),transparent 52%),#fff;box-shadow:0 36px 80px -48px rgba(12,13,26,.2)}}
.finale::before{{
  content:'';position:absolute;top:0;left:8%;right:8%;height:1px;
  background:linear-gradient(90deg,transparent,rgba(94,106,210,.72),rgba(139,92,246,.58),rgba(61,207,239,.52),rgba(34,211,153,.32),transparent);
}}
.finale-label{{display:block;font-size:.7rem;font-weight:700;letter-spacing:.13em;text-transform:uppercase;color:var(--cy);margin-bottom:18px}}
.finale-h{{font-size:clamp(2rem,4.5vw,3.1rem);font-weight:800;letter-spacing:-.054em;line-height:1.06;margin-bottom:14px;max-width:22ch;margin-left:auto;margin-right:auto}}
.finale-sub{{font-size:1.04rem;color:var(--muted);max-width:46ch;margin:0 auto 30px;line-height:1.62;font-weight:420}}
.finale-ctas{{display:flex;flex-wrap:wrap;gap:12px;justify-content:center;margin-bottom:18px}}
.finale-note{{font-size:.78rem;color:var(--muted);opacity:.68}}

/* ── responsive ──────────────────────────────────── */
@media(max-width:768px){{
  .nav{{flex-wrap:wrap;padding:12px 18px}}
  .nav-links{{order:3;width:100%;margin-top:12px;gap:16px;justify-content:flex-start}}
  .finale{{padding:44px 20px 40px}}
  .pw-body{{max-height:none}}
}}

/* ── reduced motion ──────────────────────────────── */
@media(prefers-reduced-motion:reduce){{
  .aurora-orbs,.eyebrow-dot,.btn-primary::after,
  .af .btn-merchant-push,.pipe-shine,.ann-tl,.ann-br,
  .af .spinner{{animation:none!important}}
  .af .spinner{{border-top-color:#22D3EE}}
  .rv,.rv-right{{opacity:1!important;transform:none!important;transition:none!important}}
  .h1 .rainbow{{animation:none!important;background:linear-gradient(110deg,#818cf8,var(--cy));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}}
  .ann-tl,.ann-br{{animation:none!important;opacity:1!important;transform:none!important}}
}}
</style>
</head>
<body>
{gtm_body}

<div class="aurora" aria-hidden="true">
  <div class="aurora-orbs"></div>
  <div class="aurora-dots"></div>
  <div class="aurora-vig"></div>
</div>

<!-- ── Nav (same as homepage) ── -->
@@PUBLIC_NAV@@

<div class="w">

  <!-- ═══ § 1  HERO ═══ -->
  <header class="hero">
    <div class="hero-copy rv">
      <div class="eyebrow rv d1"><span class="eyebrow-dot"></span>AI-powered &middot; Google Shopping feed</div>
      <h1 class="h1 rv d2">
        <span class="dim">Stop losing clicks to</span>
        <span class="rainbow">bad product data.</span>
      </h1>
      <div class="hero-support rv d3">
        <span class="hero-kicker">What goes wrong</span>
        <p class="hero-punch">Up to <strong>30%</strong> of products get disapproved over feed issues &mdash; while you still pay for ads on the rest.</p>
        <p class="hero-money">Increase Shopping performance <strong>without raising ad spend</strong>. Get <strong>more clicks and sales</strong> from the same budget.</p>
      </div>
      <div class="hero-actions rv d4">
        <div class="hero-ctas">
          <a href="/login?next=/upload" class="btn btn-primary" style="font-size:.95rem;padding:14px 26px">Fix my feed &rarr;</a>
          <a href="#flow-h" class="btn btn-ghost">See how it works &rarr;</a>
        </div>
        <p class="hero-friction">No setup &middot; No integration &middot; Works with any CSV</p>
      </div>
      <div class="hero-proof rv d5">
        <span class="hero-kicker">Why teams try Cartozo</span>
        <div class="trust-chips">
          <span class="t-chip"><span class="t-chip-dot"></span><span>Teams running <strong>Google Shopping campaigns</strong> use it to clean feeds before spend scales.</span></span>
          <span class="t-chip"><span class="t-chip-dot"></span><span><strong>Early users</strong> reported fewer Merchant disapprovals after one pass.</span></span>
          <span class="t-chip"><span class="t-chip-dot"></span><span>For stores that can&rsquo;t afford another <strong>warning or limited</strong> state on key SKUs.</span></span>
        </div>
      </div>
    </div>

    <!-- batch-review product window — always visible, real app UI -->
    <div class="pw-wrap rv-right">
      <div class="pw">
        <div class="pw-chrome">
          <div class="pw-dots"><span></span><span></span><span></span></div>
          <div class="pw-url">cartozo.ai / batches / review</div>
          <div class="pw-status">&#10003; Done &middot; 142 / 150</div>
        </div>
        <div class="pw-body af">
          <div class="review-summary-bar">
            <span class="review-summary-lead">&#9889; <strong>142</strong>/<strong>150</strong> optimized<span class="m">&middot;</span>avg <strong>87</strong>/100</span>
            <span class="review-summary-meta">
              Done <strong>142</strong><span class="m">&middot;</span>
              Review <strong class="c-review">5</strong><span class="m">&middot;</span>
              Failed <strong class="c-fail">1</strong><span class="m">&middot;</span>
              Skipped <strong>2</strong>
            </span>
          </div>
          <div class="table-container">
            <table>
              <thead>
                <tr><th>SKU</th><th>Original title</th><th>Positioned title</th><th>Score</th><th>Status</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td class="mono">SKU-91</td>
                  <td style="color:rgba(239,68,68,.9);font-size:.7rem">shoe</td>
                  <td>
                    <div class="cell-with-gmc">
                      <span class="new-content">Men&rsquo;s Trail Running Shoes &ndash; Waterproof, Lightweight &ndash; Blue | Size 42</span>
                      <div class="gmc-tags"><span class="gmc-tag gmc-tag-fixed">&#10004; Fixed: Title too short</span><span class="gmc-tag gmc-tag-fixed">&#10004; GTIN enriched</span></div>
                    </div>
                  </td>
                  <td><span class="score-high">91</span></td>
                  <td><span class="pill-done">Done</span></td>
                </tr>
                <tr>
                  <td class="mono">SKU-02</td>
                  <td style="color:rgba(245,158,11,.9);font-size:.7rem">bag blue</td>
                  <td>
                    <div class="cell-with-gmc">
                      <span class="new-content">Women&rsquo;s Leather Tote Bag &ndash; Navy Blue, 13&Prime; Laptop Sleeve</span>
                      <div class="gmc-tags"><span class="gmc-tag gmc-tag-fixed">&#10004; Full attributes added</span></div>
                    </div>
                  </td>
                  <td><span class="score-high">88</span></td>
                  <td><span class="pill-done">Done</span></td>
                </tr>
                <tr>
                  <td class="mono">SKU-44</td>
                  <td style="color:rgba(245,158,11,.9);font-size:.7rem">jacket L</td>
                  <td>
                    <div class="cell-with-gmc">
                      <span class="new-content">Men&rsquo;s Waterproof Hiking Jacket &ndash; Size L, Windproof 3-Layer Shell</span>
                      <div class="gmc-tags"><span class="gmc-tag gmc-tag-fixed">&#10004; Description generated</span></div>
                    </div>
                  </td>
                  <td><span class="score-high">86</span></td>
                  <td><span class="pill-done">Done</span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="header-actions">
            <span class="btn btn-merchant-push">&#9654;&ensp;Push to Merchant</span>
            <span class="btn btn-primary">&#8681;&ensp;Export CSV</span>
          </div>
        </div>
      </div>
      <!-- floating annotation badges -->
      <div class="ann ann-tl"><span class="ann-ico">&#9889;</span><div><div class="ann-main">142&thinsp;/&thinsp;150 optimized</div><div class="ann-sub">avg score&thinsp;87/100</div></div></div>
      <div class="ann ann-br"><span class="ann-ico">&#10004;</span><div><div class="ann-main">GMC validated</div><div class="ann-sub">0 disapprovals</div></div></div>
    </div>
  </header>

  <!-- ═══ STATS STRIP ═══ -->
  <div class="stats-strip rv">
    <div class="stat-item"><div class="stat-n stat-lead">Fix disapprovals automatically</div><div class="stat-t">Merchant errors, missing GTINs, and policy flags surfaced and corrected row-by-row &mdash; not in a spreadsheet marathon.</div></div>
    <div class="stat-item"><div class="stat-n stat-lead">Position on real search intents</div><div class="stat-t">Not a blind rewrite: intents are detected, scored, and merged into titles and descriptions so listings match how people shop.</div></div>
    <div class="stat-item"><div class="stat-n stat-lead">Push clean feeds in one click</div><div class="stat-t">Export a validated CSV or send the batch straight to Google Merchant &mdash; no copy-paste between tools.</div></div>
  </div>

  <!-- ═══ § 2  BEFORE / AFTER ═══ -->
  <section class="section rv" aria-labelledby="ba-h">
    <span class="s-label">The transformation</span>
    <h2 class="s-h" id="ba-h">Same product.<br/>Completely different&nbsp;results.</h2>
    <p class="s-sub">Bad data isn&rsquo;t a &ldquo;nice-to-fix&rdquo; problem &mdash; it costs approvals, clicks, and budget. Here&rsquo;s the same SKU with shopping-grade vs. broken listings.</p>
    <div class="ba">
      <div class="ba-head">
        <div class="ba-th bad">&#10005;&ensp;Disapproved / low CTR</div>
        <div class="ba-th mid">AI</div>
        <div class="ba-th good">&#10003;&ensp;Approved / optimized</div>
      </div>
      <div class="ba-row">
        <div class="ba-cell bad"><div class="v">&ldquo;shoe&rdquo;</div></div>
        <div class="ba-arrow">&rarr;</div>
        <div class="ba-cell good"><div class="v">Men&rsquo;s Trail Running Shoes &ndash; Waterproof, Lightweight Mesh &ndash; Model X42&thinsp;|&thinsp;Blue&thinsp;|&thinsp;Size&thinsp;42</div><span class="ba-fix">&#10004; Title &amp; GTIN fixed</span></div>
      </div>
      <div class="ba-row">
        <div class="ba-cell bad"><div class="v">&ldquo;bag blue&rdquo;</div></div>
        <div class="ba-arrow">&rarr;</div>
        <div class="ba-cell good"><div class="v">Women&rsquo;s Leather Tote Bag &ndash; Navy Blue, 13&Prime; Laptop Compartment, Zip Closure&thinsp;|&thinsp;Work Bag</div><span class="ba-fix">&#10004; Full attributes added</span></div>
      </div>
      <div class="ba-row">
        <div class="ba-cell bad"><div class="v">&ldquo;jacket L&rdquo;</div></div>
        <div class="ba-arrow">&rarr;</div>
        <div class="ba-cell good"><div class="v">Men&rsquo;s Waterproof Hiking Jacket &ndash; Size L, Windproof 3-Layer Shell&thinsp;|&thinsp;Olive&thinsp;/&thinsp;Navy</div><span class="ba-fix">&#10004; Description generated</span></div>
      </div>
    </div>
  </section>

  <!-- ═══ WHY IT MATTERS ═══ -->
  <section class="section rv" aria-labelledby="why-h">
    <span class="s-label">Why it matters</span>
    <h2 class="s-h" id="why-h">Skip this and your Shopping campaigns pay the&nbsp;price.</h2>
    <p class="s-sub" style="margin-bottom:20px">Improve performance of your Google Shopping campaigns without increasing ad spend &mdash; by fixing the feed everything else depends on.</p>
    <ul class="why-list">
      <li>Up to ~30% of offers can run into disapprovals or warnings when feed quality is weak.</li>
      <li>Thin titles and missing attributes drag down CTR &mdash; you pay more per click for worse placement.</li>
      <li>Manual clean-up in sheets takes hours or days; every day costs impressions you don&rsquo;t get back.</li>
    </ul>
    <p class="why-close">Cartozo clears the blockers in minutes &mdash; so listings can spend, not sit in &ldquo;limited&rdquo; or disapproved states.</p>
  </section>

  <!-- ═══ § 3  KEY FLOW + STEPS ═══ -->
  <section class="section rv" aria-labelledby="flow-h">
    <span class="s-label">How it works</span>
    <h2 class="s-h" id="flow-h">The complete pipeline &mdash;<br/>from CSV to Google Shopping.</h2>
    <p class="s-sub">Five automated stages. Spot-check if you want &mdash; then export or push.</p>
    <p class="flow-summary rv d1" role="note"><strong>TL;DR:</strong> Upload &rarr; Fix &rarr; Review &rarr; Push to Merchant</p>

    <!-- flow pipeline indicator -->
    <div class="pipeline rv d1" role="list" aria-label="Processing pipeline">
      <div class="pipe-node" role="listitem">
        &#128196; Upload
        <em>/upload</em>
      </div>
      <div class="pipe-track"><div class="pipe-shine"></div></div>
      <div class="pipe-node" role="listitem">
        &#9881; Mapping
        <em>/preview</em>
      </div>
      <div class="pipe-track"><div class="pipe-shine"></div></div>
      <div class="pipe-node active" role="listitem">
        &#129302; Intent pipeline
        <em>/confirm</em>
      </div>
      <div class="pipe-track"><div class="pipe-shine"></div></div>
      <div class="pipe-node" role="listitem">
        &#128202; Review
        <em>/review</em>
      </div>
      <div class="pipe-track"><div class="pipe-shine"></div></div>
      <div class="pipe-node" role="listitem">
        &#128640; Export&thinsp;/&thinsp;GMC
        <em>push or CSV</em>
      </div>
    </div>

    <div class="grid-2">

      <!-- Step 01: Upload -->
      <div class="sc rv d1">
        <div class="sc-num">01</div>
        <div class="sc-title">Upload your feed</div>
        <p class="sc-desc">Drop your CSV &mdash; UTF-8, any columns, up to 40&thinsp;MB. We detect the schema for&nbsp;you.</p>
        <div class="mw">
          <div class="mw-bar"><span class="mw-dots"><i></i><i></i><i></i></span><span class="mw-url">cartozo.ai&thinsp;/&thinsp;upload</span></div>
          <div class="mw-body af">
            <p class="subtitle">Upload a CSV. We infer shopper search intents, pick the strongest, then assemble titles and descriptions—plus validation and export.</p>
            <div class="dropzone has-file">
              <div class="dropzone-icon">&#10003;</div>
              <div class="dropzone-text"><strong>Ready to process</strong></div>
              <div class="dropzone-filename">products_2026.csv &middot; 2.4&thinsp;MB &middot; 5,000 rows</div>
              <div class="dropzone-hint">UTF-8 &middot; any columns &middot; up to 40&thinsp;MB</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Step 02: Mapping -->
      <div class="sc rv d2">
        <div class="sc-num">02</div>
        <div class="sc-title">Map columns &mdash; auto-detected</div>
        <p class="sc-desc">Mapping is pre-filled from your headers. Confirm which fields run the intent pipeline (title / description) &mdash; done.</p>
        <div class="mw">
          <div class="mw-bar"><span class="mw-dots"><i></i><i></i><i></i></span><span class="mw-url">column_mapping</span></div>
          <div class="mw-body af">
            <div class="table-container">
              <table>
                <thead><tr><th>CSV column</th><th>Sample data</th><th>Maps to</th></tr></thead>
                <tbody>
                  <tr><td class="col-name">sku</td><td class="sample">ABC-01</td><td><select disabled><option>id</option></select></td></tr>
                  <tr><td class="col-name">title</td><td class="sample">shoe model X</td><td><select disabled><option>title</option></select></td></tr>
                  <tr><td class="col-name">long_desc</td><td class="sample">comfortable…</td><td><select disabled><option>description</option></select></td></tr>
                </tbody>
              </table>
            </div>
            <div class="options-box">
              <p class="options-title">Which fields should AI optimize?</p>
              <div class="checkboxes">
                <label class="checkbox-label"><input type="checkbox" checked disabled/> Optimize titles</label>
                <label class="checkbox-label"><input type="checkbox" checked disabled/> Optimize descriptions</label>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Step 03: AI Processing -->
      <div class="sc rv d3">
        <div class="sc-num">03</div>
        <div class="sc-title">Intent layer &amp; assembly</div>
        <p class="sc-desc">Row-by-row GMC checks, then search intents scored and selected, then titles and descriptions assembled for Shopping&mdash;not generic rewrite.</p>
        <div class="mw">
          <div class="mw-bar"><span class="mw-dots"><i></i><i></i><i></i></span><span class="mw-url">processing</span></div>
          <div class="mw-body af">
            <div class="loader">
              <div class="spinner"></div>
              <div class="thinking">Boiling the water&hellip;</div>
              <div class="thinking-sub">Extracting intents, selecting winners, assembling copy</div>
              <div class="progress"><div class="progress-fill"></div></div>
            </div>
            <div class="gmc-top-issues">
              <div class="gmc-ti-label">Issues found in source data</div>
              <ul class="gmc-ti-list">
                <li class="gmc-ti-item gmc-ti-err"><span class="gmc-ti-icon">&#10006;</span><span class="gmc-ti-text">Missing or invalid GTIN</span><span class="gmc-ti-count">24</span></li>
                <li class="gmc-ti-item gmc-ti-warn"><span class="gmc-ti-icon">&#9888;</span><span class="gmc-ti-text">Title too short for Google</span><span class="gmc-ti-count">61</span></li>
                <li class="gmc-ti-item gmc-ti-err"><span class="gmc-ti-icon">&#10006;</span><span class="gmc-ti-text">Description missing</span><span class="gmc-ti-count">18</span></li>
              </ul>
            </div>
          </div>
        </div>
      </div>

      <!-- Step 04: Review & Ship -->
      <div class="sc rv d4">
        <div class="sc-num">04</div>
        <div class="sc-title">Review, export or push to GMC</div>
        <p class="sc-desc">Scan the batch, tweak inline if needed, then CSV export or one-click push to&nbsp;Merchant.</p>
        <div class="mw">
          <div class="mw-bar"><span class="mw-dots"><i></i><i></i><i></i></span><span class="mw-url">batch_review</span></div>
          <div class="mw-body af">
            <div class="review-summary-bar">
              <span class="review-summary-lead">&#9889; <strong>142</strong>/<strong>150</strong> optimized</span>
              <span class="review-summary-meta">avg <strong>87</strong>/100</span>
            </div>
            <div class="table-container">
              <table>
                <thead><tr><th>Original</th><th>Positioned title</th><th>GMC</th><th>&#9733;</th></tr></thead>
                <tbody>
                  <tr>
                    <td style="color:rgba(239,68,68,.85);font-size:.68rem">shoe</td>
                    <td><div class="cell-with-gmc"><span class="new-content">Men&rsquo;s Trail Running Shoes &ndash; Lightweight</span><div class="gmc-tags"><span class="gmc-tag gmc-tag-fixed">&#10004; Fixed</span></div></div></td>
                    <td></td>
                    <td><span class="score-high">91</span></td>
                  </tr>
                  <tr>
                    <td style="color:rgba(245,158,11,.85);font-size:.68rem">bag blue</td>
                    <td><div class="cell-with-gmc"><span class="new-content">Women&rsquo;s Leather Tote &ndash; Navy, 13&Prime;</span><div class="gmc-tags"><span class="gmc-tag gmc-tag-fixed">&#10004; Fixed</span></div></div></td>
                    <td></td>
                    <td><span class="score-high">88</span></td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="header-actions">
              <span class="btn btn-merchant-push">&#9654;&ensp;Push to Merchant</span>
              <span class="btn btn-primary">&#8681;&ensp;Export CSV</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- ═══ § 4  FINALE ═══ -->
  <section class="finale rv" aria-labelledby="finale-h">
    <span class="finale-label">Free to try &middot; revenue impact</span>
    <h2 class="finale-h" id="finale-h">Fix your product feed in 5 minutes<br/>&mdash; or see exactly what&rsquo;s broken.</h2>
    <p class="finale-sub">Upload a CSV and watch disapprovals, weak titles, and missing attributes surface with fixes applied. No credit card &mdash; no integrations to wire up first.</p>
    <div class="finale-ctas">
      <a href="/login?next=/upload" class="btn btn-primary" style="font-size:.97rem;padding:15px 32px">Fix my feed &rarr;</a>
      <a href="#flow-h" class="btn btn-ghost">See how it works &rarr;</a>
    </div>
    <p class="finale-note">No setup &middot; No integration &middot; Works with any CSV &middot; Typical large feed&thinsp;&sim;5&thinsp;min</p>
  </section>

  @@PUBLIC_SITE_FOOTER@@
</div>

<script>
(function(){{
  document.body.classList.add('on');

  /* theme (hp-nav button) */
  @@THEME_TOGGLE_INLINE@@

  /* scroll reveal */
  var mm=window.matchMedia('(prefers-reduced-motion:reduce)');
  if('IntersectionObserver' in window&&!mm.matches){{
    var io=new IntersectionObserver(function(es){{
      es.forEach(function(e){{if(e.isIntersecting){{e.target.classList.add('in');io.unobserve(e.target)}}}}
    )}},{{rootMargin:'0px 0px -7% 0px',threshold:0.06}});
    document.querySelectorAll('.rv,.rv-right').forEach(function(el){{io.observe(el)}})
  }}else{{
    document.querySelectorAll('.rv,.rv-right').forEach(function(el){{el.classList.add('in')}})
  }}

  /* 3-D tilt on step cards */
  if(!mm.matches){{
    document.querySelectorAll('.sc').forEach(function(card){{
      card.addEventListener('mousemove',function(e){{
        var r=card.getBoundingClientRect();
        var x=(e.clientX-r.left)/r.width-.5;
        var y=(e.clientY-r.top)/r.height-.5;
        card.style.transform='perspective(900px) rotateY('+(x*9)+'deg) rotateX('+(-y*6)+'deg) translateZ(6px)';
      }});
      card.addEventListener('mouseleave',function(){{
        card.style.transform='perspective(900px) rotateY(0) rotateX(0) translateZ(0)';
        setTimeout(function(){{card.style.transform=''}},280);
      }});
    }})
  }}
}})();
</script>
<script src="/static/page-transition.js"></script>
</body>
</html>"""
    return (
        html.replace("@@HP_NAV_STYLES@@", HP_NAV_CSS + HP_FOOTER_CSS)
        .replace("@@PUBLIC_NAV@@", public_site_nav_html(feed_structure_href="/#feed-structure"))
        .replace("@@PUBLIC_SITE_FOOTER@@", public_site_footer_html(feed_structure_href="/#feed-structure"))
        .replace("@@THEME_TOGGLE_INLINE@@", public_site_theme_toggle_script().strip())
    )
