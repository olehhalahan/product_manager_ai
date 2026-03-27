"""Marketing site header — same markup and styles as the homepage `.hp-nav`."""
from __future__ import annotations

import html as html_module

# Shared footer (logo + key links); use with `HP_NAV_CSS` tokens (`--hp-*`).
HP_FOOTER_CSS = """
    .hp-footer { max-width: 1200px; margin: 0 auto; padding: 32px 40px 28px; border-top: 1px solid var(--hp-border-card); box-sizing: border-box; position: relative; z-index: 2; }
    .hp-footer-main { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 24px 32px; margin-bottom: 20px; }
    .hp-footer-logo { display: flex; align-items: center; flex-shrink: 0; text-decoration: none; }
    .hp-footer-logo img { height: 28px; width: auto; }
    .hp-footer-logo .logo-dark { display: none; filter: brightness(0) invert(1); }
    .hp-footer-logo .logo-light { display: block; filter: brightness(0) invert(1); }
    [data-theme="light"] .hp-footer-logo .logo-light { display: none; }
    [data-theme="light"] .hp-footer-logo .logo-dark { display: block; filter: none; }
    .hp-footer-nav { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 10px 20px; flex: 1; min-width: 0; }
    .hp-footer-link { font-size: 0.85rem; font-weight: 500; color: var(--hp-muted); text-decoration: none; transition: color 0.2s; }
    .hp-footer-link:hover { color: var(--hp-text); }
    .hp-footer-meta { font-size: 0.78rem; color: var(--hp-muted); text-align: center; padding-top: 4px; line-height: 1.55; }
    .hp-footer-meta a { color: var(--hp-muted); text-decoration: none; }
    .hp-footer-meta a:hover { color: var(--hp-text); text-decoration: underline; }
    @media (max-width: 768px) {
        .hp-footer { padding: 28px 24px 24px; }
        .hp-footer-main { flex-direction: column; align-items: stretch; text-align: center; }
        .hp-footer-logo { justify-content: center; }
        .hp-footer-nav { justify-content: center; }
    }
"""

# Tokens + nav bar (excerpt from `main.py` HOMEPAGE_HTML); safe to embed in any page `<style>`.
HP_NAV_CSS = """
    :root, [data-theme="dark"] {
      --hp-bg: #0b0f14;
      --hp-card: #1f2937;
      --hp-text: #f9fafb;
      --hp-muted: #9ca3af;
      --hp-accent: #93c5fd;
      --hp-positive: #4ade80;
      --hp-negative: #f87171;
      --hp-border: rgba(255,255,255,0.08);
      --hp-border-card: rgba(255,255,255,0.12);
      --hp-font: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      --hp-cta-gradient: linear-gradient(180deg, #2d333a 0%, #1a1d22 100%);
    }
    [data-theme="light"] {
      --hp-grad-0: #ffffff;
      --hp-grad-1: #f8fbff;
      --hp-grad-2: #e8f0fe;
      --hp-grad-3: #f0f4ff;
      --hp-bg: #f0f4ff;
      --hp-card: #ffffff;
      --hp-text: #1a1a1a;
      --hp-muted: #4b5563;
      --hp-accent: #2d333a;
      --hp-positive: #4ade80;
      --hp-negative: #f87171;
      --hp-border: rgba(26,26,26,0.08);
      --hp-border-card: #e5e7eb;
      --hp-cta-gradient: linear-gradient(180deg, #2d333a 0%, #23292f 100%);
    }

    .hp-nav { position: fixed; top: 0; left: 0; right: 0; z-index: 1000; padding: 12px 0; background: rgba(0,0,0,0.72); backdrop-filter: blur(20px) saturate(1.2); -webkit-backdrop-filter: blur(20px) saturate(1.2); border-bottom: 1px solid var(--hp-border-card); }
    [data-theme="light"] .hp-nav { background: rgba(255,255,255,0.88); border-bottom-color: var(--hp-border-card); }
    .hp-nav-inner { max-width: 1200px; width: 100%; margin: 0 auto; padding: 0 40px; box-sizing: border-box; display: flex; align-items: center; justify-content: space-between; gap: 24px; }
    .hp-nav-logo { flex-shrink: 0; position: relative; }
    .hp-nav-logo img { height: 32px; }
    .hp-nav-logo .logo-dark { display: none; filter: brightness(0) invert(1); }
    .hp-nav-logo .logo-light { display: block; filter: brightness(0) invert(1); }
    [data-theme="light"] .hp-nav-logo .logo-light { display: none; }
    [data-theme="light"] .hp-nav-logo .logo-dark { display: block; filter: none; }
    .hp-nav-links { display: flex; align-items: center; justify-content: center; gap: 28px; flex: 1; }
    .hp-nav-right { display: flex; align-items: center; gap: 14px; flex-shrink: 0; }
    .hp-nav-link { color: var(--hp-muted); font-size: 0.9rem; text-decoration: none; transition: color 0.2s; font-weight: 500; }
    .hp-nav-link:hover { color: var(--hp-text); }
    .hp-theme-btn { display: inline-flex; align-items: center; justify-content: center; width: 38px; height: 38px; border-radius: 50%; border: 1px solid var(--hp-border-card); background: rgba(255,255,255,0.04); color: var(--hp-muted); cursor: pointer; font-size: 1rem; transition: all 0.2s; }
    .hp-theme-btn:hover { color: var(--hp-text); background: rgba(255,255,255,0.08); border-color: rgba(147,197,253,0.4); }
    [data-theme="light"] .hp-theme-btn { background: rgba(255,255,255,0.75); border-color: var(--hp-border-card); }
    [data-theme="light"] .hp-theme-btn:hover { background: #ffffff; border-color: rgba(45,51,58,0.22); }
    .hp-nav-cta { background: var(--hp-cta-gradient); color: #fff; padding: 10px 22px; border-radius: 9999px; font-size: 0.85rem; font-weight: 600; text-decoration: none; transition: transform 0.2s, box-shadow 0.2s, opacity 0.2s; box-shadow: 0 0 28px rgba(17,24,39,0.35); }
    .hp-nav-cta:hover { opacity: 0.95; transform: translateY(-1px); box-shadow: 0 0 36px rgba(17,24,39,0.45); }
    [data-theme="light"] .hp-nav-cta { border-radius: 10px; box-shadow: 0 4px 16px rgba(17,24,39,0.12); }
    [data-theme="light"] .hp-nav-cta:hover { box-shadow: 0 8px 24px rgba(17,24,39,0.18); }

    @media (max-width: 1024px) {
        .hp-nav-links { display: none; }
        .hp-nav-right { gap: 12px; }
    }

    @media (max-width: 768px) {
        .hp-nav { padding: 16px 0; }
        .hp-nav-inner { padding: 0 24px; }
    }
"""


def public_site_nav_html(*, feed_structure_href: str = "/#feed-structure") -> str:
    """Full fixed header bar; `feed_structure_href` is `#feed-structure` on `/` and `/#feed-structure` elsewhere."""
    href = html_module.escape(feed_structure_href, quote=True)
    return f"""<nav class="hp-nav" aria-label="Main">
        <div class="hp-nav-inner">
        <a href="/" class="hp-nav-logo"><img class="logo-light" src="/assets/logo-light.png" alt="Cartozo.ai" /><img class="logo-dark" src="/assets/logo-dark.png" alt="Cartozo.ai" /></a>
        <div class="hp-nav-links">
            <a href="/presentation" class="hp-nav-link">Features</a>
            <a href="/blog" class="hp-nav-link">Blog</a>
            <a href="{href}" class="hp-nav-link">Feed Structure</a>
            <a href="/how-it-works" class="hp-nav-link">How it works</a>
            <a href="/pricing" class="hp-nav-link">Pricing</a>
            <a href="/contact" class="hp-nav-link">Contact us</a>
        </div>
        <div class="hp-nav-right">
            <button type="button" class="hp-theme-btn" id="themeToggle" title="Toggle light/dark theme" aria-label="Toggle theme">&#9728;</button>
            <a href="/login" class="hp-nav-cta">Get Started</a>
        </div>
        </div>
    </nav>"""


def public_site_footer_html(*, feed_structure_href: str = "/#feed-structure") -> str:
    """Site footer: logo + same key links as the header; `feed_structure_href` is `#feed-structure` on `/` and `/#feed-structure` elsewhere."""
    href = html_module.escape(feed_structure_href, quote=True)
    return f"""<footer class="hp-footer" aria-label="Site">
        <div class="hp-footer-main">
            <a href="/" class="hp-footer-logo"><img class="logo-light" src="/assets/logo-light.png" alt="Cartozo.ai" /><img class="logo-dark" src="/assets/logo-dark.png" alt="Cartozo.ai" /></a>
            <nav class="hp-footer-nav" aria-label="Footer">
                <a href="/presentation" class="hp-footer-link">Features</a>
                <a href="/blog" class="hp-footer-link">Blog</a>
                <a href="{href}" class="hp-footer-link">Feed Structure</a>
                <a href="/how-it-works" class="hp-footer-link">How it works</a>
                <a href="/pricing" class="hp-footer-link">Pricing</a>
                <a href="/contact" class="hp-footer-link">Contact us</a>
            </nav>
        </div>
        <div class="hp-footer-meta">
            &copy; 2026 Cartozo.ai &middot; <a href="/terms">Terms of Service</a> &middot; <a href="/privacy">Privacy Policy</a> &middot; <a href="/cookies">Cookie Policy</a> &middot; Powered by <a href="https://zanzarra.com/" target="_blank" rel="noopener noreferrer">Zanzarra</a>
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
