"""Marketing site header — same markup and styles as the homepage `.hp-nav`."""
from __future__ import annotations

import html as html_module

from .air_design import AIR_COMPONENTS_CSS, AIR_TOKENS_CSS

# Shared footer (logo + key links); use with `HP_NAV_CSS` tokens (`--hp-*`).
HP_FOOTER_CSS = """
    .hp-footer {
      max-width: var(--hp-max-width, 1150px); margin: 0 auto;
      padding: 48px 40px 32px; border-top: 1px solid var(--hp-border-card);
      box-sizing: border-box; position: relative; z-index: 2;
      background: var(--hp-bg);
    }
    .hp-footer-main { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 24px 32px; margin-bottom: 20px; }
    .hp-footer-logo { display: flex; align-items: center; flex-shrink: 0; text-decoration: none; }
    .hp-footer-logo img { height: 28px; width: auto; }
    .hp-footer-logo .logo-dark { display: none; filter: brightness(0) invert(1); }
    .hp-footer-logo .logo-light { display: block; filter: brightness(0) invert(1); }
    [data-theme="light"] .hp-footer-logo .logo-light { display: none; }
    [data-theme="light"] .hp-footer-logo .logo-dark { display: block; filter: none; }
    .hp-footer-nav { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 10px 20px; flex: 1; min-width: 0; }
    .hp-footer-link { font-size: 13px; font-weight: 500; color: var(--hp-muted); text-decoration: none; transition: color 0.2s; }
    .hp-footer-link:hover { color: var(--hp-text); }
    .hp-footer-meta { font-size: 13px; color: var(--hp-muted); text-align: center; padding-top: 4px; line-height: 1.55; }
    .hp-footer-meta a { color: var(--hp-muted); text-decoration: none; border-bottom: 1px solid transparent; }
    .hp-footer-meta a:hover { color: var(--hp-text); border-bottom-color: var(--hp-text); }
    @media (max-width: 768px) {
        .hp-footer { padding: 32px 24px 24px; }
        .hp-footer-main { flex-direction: column; align-items: stretch; text-align: center; }
        .hp-footer-logo { justify-content: center; }
        .hp-footer-nav { justify-content: center; }
    }
"""

# Tokens + nav bar — Air-inspired dark canvas, ghost CTA, thin borders.
HP_NAV_CSS = (
    AIR_TOKENS_CSS
    + AIR_COMPONENTS_CSS
    + """
    .hp-nav {
      position: fixed; top: 0; left: 0; right: 0; z-index: 1000; height: 72px;
      display: flex; align-items: center;
      background: rgba(0, 0, 0, 0.72); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
      border-bottom: 1px solid var(--hp-border-card);
    }
    [data-theme="light"] .hp-nav { background: rgba(245, 245, 245, 0.92); }
    .hp-nav-inner {
      max-width: var(--hp-max-width, 1150px); width: 100%; margin: 0 auto; padding: 0 40px;
      box-sizing: border-box; display: flex; align-items: center; justify-content: space-between; gap: 24px;
    }
    .hp-nav-logo { flex-shrink: 0; position: relative; text-decoration: none; }
    .hp-nav-logo img { height: 28px; }
    .hp-nav-logo .logo-dark { display: none; filter: brightness(0) invert(1); }
    .hp-nav-logo .logo-light { display: block; filter: brightness(0) invert(1); }
    [data-theme="light"] .hp-nav-logo .logo-light { display: none; }
    [data-theme="light"] .hp-nav-logo .logo-dark { display: block; filter: none; }
    .hp-nav-links { display: flex; align-items: center; justify-content: center; gap: 24px; flex: 1; }
    .hp-nav-right { display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
    .hp-nav-link {
      color: var(--hp-muted); font-size: 14px; text-decoration: none; transition: color 0.2s; font-weight: 500;
    }
    .hp-nav-link:hover { color: var(--hp-text); }
    .hp-theme-btn {
      display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px;
      border-radius: var(--hp-radius-btn, 8px); border: 1px solid var(--hp-border-card);
      background: transparent; color: var(--hp-muted); cursor: pointer; font-size: 1rem; transition: all 0.2s;
    }
    .hp-theme-btn:hover { color: var(--hp-text); border-color: var(--hp-text); }
    .hp-nav-cta {
      display: inline-flex; align-items: center; padding: 10px 16px;
      border-radius: var(--hp-radius-btn, 8px); border: 1px solid var(--color-whiteout, #fff);
      background: transparent; color: var(--color-whiteout, #fff);
      font-size: 14px; font-weight: 500; text-decoration: none; transition: background 0.2s;
    }
    .hp-nav-cta:hover { background: rgba(255,255,255,0.06); }
    [data-theme="light"] .hp-nav-cta {
      border-color: var(--color-ink, #1b1b1b); color: var(--color-ink, #1b1b1b);
    }
    [data-theme="light"] .hp-nav-cta:hover { background: rgba(27,27,27,0.04); }

    @media (max-width: 1024px) {
        .hp-nav-links { display: none; }
        .hp-nav-right { gap: 10px; }
    }
    @media (max-width: 768px) {
        .hp-nav-inner { padding: 0 24px; }
    }
"""
)


def public_site_styles_block() -> str:
    """Shared nav + footer CSS — embed once in each public page <style> block."""
    return HP_NAV_CSS + HP_FOOTER_CSS


def public_site_nav_html(*, feed_structure_href: str = "/feed-structure") -> str:
    """Full fixed header bar."""
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
            <a href="/login" class="hp-nav-cta">Upload your feed</a>
        </div>
        </div>
    </nav>"""


def public_site_footer_html(*, feed_structure_href: str = "/feed-structure") -> str:
    """Site footer: logo + key links."""
    href = html_module.escape(feed_structure_href, quote=True)
    return f"""<footer class="hp-footer" aria-label="Site">
        <div class="hp-footer-main">
            <a href="/" class="hp-footer-logo"><img class="logo-light" src="/assets/logo-light.png" alt="Cartozo.ai" /><img class="logo-dark" src="/assets/logo-dark.png" alt="Cartozo.ai" /></a>
            <nav class="hp-footer-nav" aria-label="Footer">
                <a href="/presentation" class="hp-footer-link">Features</a>
                <a href="/guides" class="hp-footer-link">Guides</a>
                <a href="/use-cases/fix-google-merchant-center-disapprovals" class="hp-footer-link">Fix disapprovals</a>
                <a href="/use-cases/optimize-google-shopping-product-titles" class="hp-footer-link">Title optimization</a>
                <a href="/use-cases/product-feed-optimization-for-agencies" class="hp-footer-link">For agencies</a>
                <a href="/blog" class="hp-footer-link">Blog</a>
                <a href="{href}" class="hp-footer-link">Feed structure</a>
                <a href="/how-it-works" class="hp-footer-link">How it works</a>
                <a href="/pricing" class="hp-footer-link">Pricing</a>
                <a href="/contact" class="hp-footer-link">Contact</a>
            </nav>
        </div>
        <div class="hp-footer-meta">
            &copy; 2026 Cartozo.ai &middot; <a href="mailto:support@cartozo.ai">support@cartozo.ai</a> &middot; <a href="/faq">FAQ</a> &middot; <a href="/about">About us</a> &middot; <a href="/terms">Terms</a> &middot; <a href="/privacy">Privacy</a> &middot; <a href="/cookies">Cookies</a> &middot; <a href="/refund-policy">Refunds</a> &middot; Powered by <a href="https://zanzarra.com/" target="_blank" rel="noopener noreferrer">Zanzarra</a>
        </div>
    </footer>"""


def public_site_theme_toggle_script() -> str:
    """Sync sun/moon glyph with `hp-theme` (same behavior as homepage)."""
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
