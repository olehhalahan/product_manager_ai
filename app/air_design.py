"""ORYZO-inspired warm walnut design tokens (Cartozo public site)."""
from __future__ import annotations

# Inter substitutes for Halyard Display Variable (per DESIGN.md).
SITE_FONTS_URL = (
    "https://fonts.googleapis.com/css2?family=Inter:wght@400;500&display=swap"
)

ORYZO_TOKENS_CSS = """
    :root, [data-theme="dark"] {
      --color-warm-cream: #ffedd7;
      --color-walnut-shadow: #100904;
      --color-bark-brown: #382416;
      --color-cork-border: #40372e;
      --color-driftwood: #6c5f51;
      --color-ember-accent: #dc5000;
      --color-pure-black: #000000;

      --hp-bg: #100904;
      --hp-surface: #382416;
      --hp-card: #382416;
      --hp-text: #ffedd7;
      --hp-muted: #6c5f51;
      --hp-accent: #382416;
      --hp-link: #dc5000;
      --hp-positive: #4ade80;
      --hp-negative: #f87171;
      --hp-border: #40372e;
      --hp-border-card: #40372e;
      --hp-font: 'Inter', ui-sans-serif, system-ui, -apple-system, sans-serif;
      --hp-font-display: 'Inter', ui-sans-serif, system-ui, sans-serif;
      --hp-max-width: 1150px;
      --hp-radius-btn-pill: 36px;
      --hp-radius-btn-outlined: 22.5px;
      --hp-radius-card: 12px;
      --hp-radius-input: 0px;
      --text-display: clamp(2rem, 5vw, 51px);
      --text-heading: clamp(1.5rem, 3.5vw, 41px);
      --text-body: 16px;
      --text-subheading: 18px;
      --text-caption: 12px;
    }
    [data-theme="light"] {
      --hp-bg: #ffedd7;
      --hp-surface: #ffffff;
      --hp-card: #ffffff;
      --hp-text: #100904;
      --hp-muted: #6c5f51;
      --hp-accent: #382416;
      --hp-link: #dc5000;
      --hp-border: #40372e;
      --hp-border-card: #40372e;
    }
"""

ORYZO_COMPONENTS_CSS = """
    .cz-pill-btn {
      display: inline-flex; align-items: center; justify-content: center;
      padding: 14px 24px; border-radius: var(--hp-radius-btn-pill, 36px);
      border: none; background: var(--color-bark-brown, #382416);
      color: var(--color-warm-cream, #ffedd7); font-family: var(--hp-font);
      font-size: 14px; font-weight: 500; text-transform: uppercase;
      text-decoration: none; letter-spacing: 0.02em; transition: opacity 0.2s;
      box-shadow: none;
    }
    .cz-pill-btn:hover { opacity: 0.92; }

    .cz-ghost-btn {
      display: inline-flex; align-items: center; justify-content: center;
      padding: 7.5px 18px; border-radius: var(--hp-radius-btn-outlined, 22.5px);
      border: 1px solid var(--color-warm-cream, #ffedd7); background: transparent;
      color: var(--color-warm-cream, #ffedd7); font-family: var(--hp-font);
      font-size: 12px; font-weight: 500; text-transform: uppercase;
      text-decoration: none; transition: background 0.2s; box-shadow: none;
    }
    .cz-ghost-btn:hover { background: rgba(255, 237, 215, 0.06); }
    [data-theme="light"] .cz-ghost-btn {
      border-color: var(--color-bark-brown); color: var(--color-bark-brown);
    }

    .cz-link {
      color: var(--hp-link, #dc5000); text-decoration: none;
      border-bottom: 1px solid currentColor; font-weight: 500;
      text-transform: uppercase; font-size: 12px;
    }
    .cz-link:hover { opacity: 0.85; }

    .cz-card {
      background: transparent; border: 1px solid var(--color-cork-border, #40372e);
      border-radius: var(--hp-radius-card, 12px); padding: 24px;
      color: var(--hp-text); box-shadow: none;
    }
    [data-theme="light"] .cz-card {
      background: #fff; border-color: var(--color-cork-border);
    }

    .cz-divider {
      border: none; border-top: 1px dashed var(--color-cork-border, #40372e);
      margin: var(--spacing-41, 41px) 0;
    }

    .cz-display {
      font-family: var(--hp-font-display); font-weight: 500; text-transform: uppercase;
      font-size: var(--text-display); line-height: 0.9; color: var(--hp-text);
    }
    .cz-section-kicker {
      font-size: var(--text-caption, 12px); font-weight: 500;
      letter-spacing: 0.06em; text-transform: uppercase;
      color: var(--color-driftwood, #6c5f51); margin-bottom: 12px;
    }
    .cz-section-title {
      font-size: var(--text-heading); font-weight: 500; line-height: 0.9;
      text-transform: uppercase; color: var(--hp-text);
    }
    .cz-body {
      font-size: var(--text-body, 16px); font-weight: 400; line-height: 1.5;
      color: var(--hp-text); text-transform: none;
    }
    .cz-body-muted { color: var(--hp-muted); }
"""

# Shared styles for answer / guide / example pages (.ap-*)
SITE_PAGE_CSS = """
.ap-wrap{position:relative;z-index:1;max-width:920px;margin:0 auto;padding:96px 24px 48px;box-sizing:border-box}
.ap-bc{font-size:12px;font-weight:500;text-transform:uppercase;color:var(--hp-muted);margin-bottom:18px;letter-spacing:.04em}
.ap-bc a{color:var(--hp-text);text-decoration:none;border-bottom:1px dashed var(--hp-border)}
.ap-h1{font-size:var(--text-heading);font-weight:500;letter-spacing:-.01em;line-height:.95;text-transform:uppercase;margin-bottom:18px;color:var(--hp-text)}
.ap-lead{font-size:var(--text-body);line-height:1.5;font-weight:400;color:var(--hp-text);margin-bottom:24px;text-transform:none}
.ap-box{background:transparent;border:1px solid var(--hp-border-card);border-radius:12px;padding:24px;margin:24px 0;color:var(--hp-text)}
[data-theme=light] .ap-box{background:#fff}
.ap-table-wrap{overflow-x:auto;margin:24px 0;border:1px dashed var(--hp-border);border-radius:12px}
.ap-table{width:100%;border-collapse:collapse;font-size:14px;min-width:640px}
.ap-table th,.ap-table td{padding:12px 14px;border-bottom:1px solid var(--hp-border);text-align:left;vertical-align:top;color:var(--hp-text)}
.ap-table th{font-weight:500;text-transform:uppercase;font-size:12px;color:var(--hp-muted);background:transparent}
.ap-cta{margin:41px 0;padding:24px;border-radius:12px;border:1px dashed var(--hp-border);text-align:center;background:transparent}
.ap-cta a{display:inline-block;margin:8px 6px 0}
.ap-cta a.primary{display:inline-flex;padding:14px 24px;border-radius:36px;background:var(--color-bark-brown);color:var(--color-warm-cream);font-weight:500;font-size:14px;text-transform:uppercase;text-decoration:none;border:none}
.ap-cta a.secondary{display:inline-flex;padding:7.5px 18px;border-radius:22.5px;border:1px solid var(--color-warm-cream);color:var(--color-warm-cream);font-weight:500;font-size:12px;text-transform:uppercase;text-decoration:none;background:transparent}
.ap-dl-list{margin:12px 0 0 1rem}
.ap-dl-list li{margin-bottom:8px}
.ap-note{font-size:13px;color:var(--hp-muted);margin-top:12px}
.ap-toc{margin:24px 0;padding:20px;border-radius:12px;border:1px dashed var(--hp-border);background:transparent}
.ap-toc a{color:var(--hp-link);text-decoration:none;border-bottom:1px solid currentColor;font-size:12px;text-transform:uppercase;font-weight:500}
.ap-ex pre{background:var(--color-bark-brown);border-radius:12px;padding:14px;font-size:13px;overflow:auto;white-space:pre-wrap;word-break:break-word;color:var(--color-warm-cream);border:1px solid var(--hp-border)}
[data-theme=light] .ap-ex pre{background:#382416}
.ap-section{margin:41px 0;padding-top:41px;border-top:1px dashed var(--hp-border)}
.ap-section h2{font-size:24px;font-weight:500;text-transform:uppercase;line-height:1.09;margin-bottom:14px;color:var(--hp-text)}
.ap-section p,.ap-section li{font-size:16px;line-height:1.5;font-weight:400;color:var(--hp-text)}
.ap-faq dt{font-weight:500;text-transform:uppercase;font-size:14px;margin-top:18px;color:var(--hp-text)}
.ap-faq dd{font-size:16px;font-weight:400;color:var(--hp-muted);margin:8px 0 0;padding:0}
"""

# Backward-compatible aliases
AIR_TOKENS_CSS = ORYZO_TOKENS_CSS
AIR_COMPONENTS_CSS = ORYZO_COMPONENTS_CSS
AIR_FONTS_URL = SITE_FONTS_URL


def site_public_styles_block() -> str:
    """Tokens + components for embedding in public page <style> blocks."""
    return ORYZO_TOKENS_CSS + ORYZO_COMPONENTS_CSS


def site_page_shell_css() -> str:
    """Full public page CSS including .ap-* content blocks."""
    return site_public_styles_block() + SITE_PAGE_CSS


def air_public_styles_block() -> str:
    return site_public_styles_block()
