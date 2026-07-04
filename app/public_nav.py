"""Marketing site header — ORYZO warm walnut design."""
from __future__ import annotations

import html as html_module

from .air_design import ORYZO_COMPONENTS_CSS, ORYZO_TOKENS_CSS

HP_FOOTER_CSS = """
    .hp-footer {
      max-width: var(--hp-max-width, 1150px); margin: 0 auto;
      padding: 68px 40px 41px; border-top: 1px dashed var(--hp-border-card);
      box-sizing: border-box; position: relative; z-index: 2; background: var(--hp-bg);
    }
    .hp-footer-main { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 24px 32px; margin-bottom: 24px; }
    .hp-footer-logo { display: flex; align-items: center; flex-shrink: 0; text-decoration: none; }
    .hp-footer-logo img { height: 28px; width: auto; }
    .hp-footer-logo .logo-dark { display: none; filter: brightness(0) invert(1); opacity: 0.95; }
    .hp-footer-logo .logo-light { display: block; filter: brightness(0) invert(1); opacity: 0.95; }
    [data-theme="light"] .hp-footer-logo .logo-light { display: none; }
    [data-theme="light"] .hp-footer-logo .logo-dark { display: block; filter: none; opacity: 1; }
    .hp-footer-nav { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 10px 18px; flex: 1; min-width: 0; }
    .hp-footer-link {
      font-size: 12px; font-weight: 500; color: var(--hp-text); text-decoration: none;
      text-transform: uppercase; letter-spacing: 0.04em; transition: color 0.2s;
      border-bottom: 1px solid transparent;
    }
    .hp-footer-link:hover { color: var(--hp-link); border-bottom-color: var(--hp-link); }
    .hp-footer-meta { font-size: 11px; color: var(--hp-muted); text-align: center; padding-top: 8px; line-height: 1.55; font-family: Arial, sans-serif; text-transform: uppercase; }
    .hp-footer-meta a { color: var(--hp-muted); text-decoration: none; }
    .hp-footer-meta a:hover { color: var(--hp-link); }
    @media (max-width: 768px) {
        .hp-footer { padding: 41px 24px 24px; }
        .hp-footer-main { flex-direction: column; align-items: stretch; text-align: center; }
        .hp-footer-logo { justify-content: center; }
        .hp-footer-nav { justify-content: center; }
    }
"""

HP_NAV_CSS = (
    ORYZO_TOKENS_CSS
    + ORYZO_COMPONENTS_CSS
    + """
    .hp-nav {
      position: fixed; top: 0; left: 0; right: 0; z-index: 1000; height: 72px;
      display: flex; align-items: center;
      background: rgba(16, 9, 4, 0.82); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
      border-bottom: 1px dashed var(--hp-border-card);
    }
    [data-theme="light"] .hp-nav { background: rgba(255, 237, 215, 0.92); }
    .hp-nav-inner {
      max-width: var(--hp-max-width, 1150px); width: 100%; margin: 0 auto; padding: 0 40px;
      box-sizing: border-box; display: flex; align-items: center; justify-content: space-between; gap: 24px;
    }
    .hp-nav-logo { flex-shrink: 0; text-decoration: none; }
    .hp-nav-logo img { height: 28px; }
    .hp-nav-logo .logo-dark { display: none; filter: brightness(0) invert(1); opacity: 0.95; }
    .hp-nav-logo .logo-light { display: block; filter: brightness(0) invert(1); opacity: 0.95; }
    [data-theme="light"] .hp-nav-logo .logo-light { display: none; }
    [data-theme="light"] .hp-nav-logo .logo-dark { display: block; filter: none; }
    .hp-nav-links { display: flex; align-items: center; justify-content: center; gap: 20px; flex: 1; }
    .hp-nav-right { display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
    .hp-nav-link {
      color: var(--hp-text); font-size: 12px; text-decoration: none; transition: color 0.2s;
      font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em;
      border-bottom: 1px solid transparent; padding-bottom: 2px;
    }
    .hp-nav-link:hover { color: var(--hp-link); border-bottom-color: var(--hp-link); }
    .hp-theme-btn {
      display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px;
      border-radius: var(--hp-radius-btn-outlined, 22.5px); border: 1px solid var(--hp-border-card);
      background: transparent; color: var(--hp-text); cursor: pointer; font-size: 1rem; transition: all 0.2s;
    }
    .hp-theme-btn:hover { border-color: var(--hp-text); }
    .hp-nav-cta {
      display: inline-flex; align-items: center; padding: 10px 20px;
      border-radius: var(--hp-radius-btn-pill, 36px); border: none;
      background: var(--color-bark-brown, #382416); color: var(--color-warm-cream, #ffedd7);
      font-size: 12px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em;
      text-decoration: none; transition: opacity 0.2s;
    }
    .hp-nav-cta:hover { opacity: 0.92; }

    @media (max-width: 1024px) { .hp-nav-links { display: none; } }
    @media (max-width: 768px) { .hp-nav-inner { padding: 0 24px; } }
"""
)


def public_site_styles_block() -> str:
    return HP_NAV_CSS + HP_FOOTER_CSS


def public_site_nav_html(*, feed_structure_href: str = "/feed-structure") -> str:
    href = html_module.escape(feed_structure_href, quote=True)
    return f"""<nav class="hp-nav" aria-label="Main">
        <div class="hp-nav-inner">
        <a href="/" class="hp-nav-logo"><img class="logo-light" src="/assets/logo-light.png" alt="Cartozo.ai" /><img class="logo-dark" src="/assets/logo-dark.png" alt="Cartozo.ai" /></a>
        <div class="hp-nav-links">
            <a href="/presentation" class="hp-nav-link">Features</a>
            <a href="/guides" class="hp-nav-link">Guides</a>
            <a href="/blog" class="hp-nav-link">Blog</a>
            <a href="{href}" class="hp-nav-link">Feed Structure</a>
            <a href="/how-it-works" class="hp-nav-link">How it works</a>
            <a href="/pricing" class="hp-nav-link">Pricing</a>
            <a href="/faq" class="hp-nav-link">FAQ</a>
            <a href="/contact" class="hp-nav-link">Contact</a>
        </div>
        <div class="hp-nav-right">
            <button type="button" class="hp-theme-btn" id="themeToggle" title="Toggle light/dark theme" aria-label="Toggle theme">&#9728;</button>
            <a href="/login" class="hp-nav-cta">Upload feed</a>
        </div>
        </div>
    </nav>"""


def public_site_footer_html(*, feed_structure_href: str = "/feed-structure") -> str:
    href = html_module.escape(feed_structure_href, quote=True)
    return f"""<footer class="hp-footer" aria-label="Site">
        <div class="hp-footer-main">
            <a href="/" class="hp-footer-logo"><img class="logo-light" src="/assets/logo-light.png" alt="Cartozo.ai" /><img class="logo-dark" src="/assets/logo-dark.png" alt="Cartozo.ai" /></a>
            <nav class="hp-footer-nav" aria-label="Footer">
                <a href="/presentation" class="hp-footer-link">Features</a>
                <a href="/guides" class="hp-footer-link">Guides</a>
                <a href="/use-cases/fix-google-merchant-center-disapprovals" class="hp-footer-link">Fix disapprovals</a>
                <a href="/use-cases/optimize-google-shopping-product-titles" class="hp-footer-link">Titles</a>
                <a href="/blog" class="hp-footer-link">Blog</a>
                <a href="{href}" class="hp-footer-link">Feed structure</a>
                <a href="/how-it-works" class="hp-footer-link">How it works</a>
                <a href="/pricing" class="hp-footer-link">Pricing</a>
                <a href="/contact" class="hp-footer-link">Contact</a>
            </nav>
        </div>
        <div class="hp-footer-meta">
            &copy; 2026 Cartozo.ai &middot; <a href="mailto:support@cartozo.ai">support@cartozo.ai</a> &middot; <a href="/faq">FAQ</a> &middot; <a href="/terms">Terms</a> &middot; <a href="/privacy">Privacy</a> &middot; Powered by <a href="https://zanzarra.com/" target="_blank" rel="noopener noreferrer">Zanzarra</a>
        </div>
    </footer>"""


def public_site_theme_toggle_script() -> str:
    return """
    (function(){
        const t=document.getElementById("themeToggle");
        if(!t)return;
        const k="hp-theme";
        function g(){return localStorage.getItem(k)||"dark";}
        function s(v){document.documentElement.setAttribute("data-theme",v);localStorage.setItem(k,v);t.textContent=v==="dark"?"\\u2600":"\\u263E";}
        t.addEventListener("click",function(){s(g()==="dark"?"light":"dark");});
        s(g());
    })();"""
