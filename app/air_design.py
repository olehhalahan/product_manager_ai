"""Air-inspired design tokens and shared marketing CSS (Cartozo adaptation)."""
from __future__ import annotations

# Loaded via gtm.py — Inter + Anton (compressed) + Caveat (cursive accent).
AIR_FONTS_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=Anton&family=Caveat:wght@400;500&family=Inter:wght@400;500;600&display=swap"
)

AIR_TOKENS_CSS = """
    :root, [data-theme="dark"] {
      --color-whiteout: #ffffff;
      --color-haze: #f5f5f5;
      --color-ink: #1b1b1b;
      --color-black-void: #000000;
      --color-twilight-blue: #426188;
      --color-signal-blue: #2b7fff;

      --hp-bg: #000000;
      --hp-surface: #0a0a0a;
      --hp-card: #f5f5f5;
      --hp-text: #ffffff;
      --hp-muted: rgba(255, 255, 255, 0.55);
      --hp-accent: #426188;
      --hp-link: #2b7fff;
      --hp-positive: #4ade80;
      --hp-negative: #f87171;
      --hp-border: rgba(255, 255, 255, 0.12);
      --hp-border-card: rgba(255, 255, 255, 0.18);
      --hp-font: 'Inter', ui-sans-serif, system-ui, -apple-system, sans-serif;
      --hp-font-display: 'Anton', 'Inter', sans-serif;
      --hp-font-cursive: 'Caveat', cursive;
      --hp-max-width: 1150px;
      --hp-radius-btn: 8px;
      --hp-radius-card: 12px;
      --hp-radius-input: 4px;
    }
    [data-theme="light"] {
      --hp-bg: #f5f5f5;
      --hp-surface: #ffffff;
      --hp-card: #ffffff;
      --hp-text: #1b1b1b;
      --hp-muted: rgba(27, 27, 27, 0.6);
      --hp-accent: #426188;
      --hp-link: #2b7fff;
      --hp-border: rgba(27, 27, 27, 0.1);
      --hp-border-card: rgba(27, 27, 27, 0.14);
    }
"""

AIR_COMPONENTS_CSS = """
    .air-ghost-btn {
      display: inline-flex; align-items: center; justify-content: center;
      padding: 10px 16px; border-radius: var(--hp-radius-btn, 8px);
      border: 1px solid var(--color-whiteout, #fff); background: transparent;
      color: var(--color-whiteout, #fff); font-family: var(--hp-font);
      font-size: 14px; font-weight: 500; text-decoration: none;
      transition: background 0.2s, border-color 0.2s, color 0.2s;
    }
    .air-ghost-btn:hover { background: rgba(255,255,255,0.06); }
    [data-theme="light"] .air-ghost-btn {
      border-color: var(--color-ink, #1b1b1b); color: var(--color-ink, #1b1b1b);
    }
    [data-theme="light"] .air-ghost-btn:hover { background: rgba(27,27,27,0.04); }

    .air-haze-btn {
      display: inline-flex; align-items: center; justify-content: center;
      padding: 8px 16px; border-radius: var(--hp-radius-btn, 8px);
      border: 1px solid var(--color-ink, #1b1b1b); background: var(--color-haze, #f5f5f5);
      color: var(--color-ink, #1b1b1b); font-family: var(--hp-font);
      font-size: 14px; font-weight: 500; text-decoration: none;
      transition: opacity 0.2s;
    }
    .air-haze-btn:hover { opacity: 0.88; }

    .air-link {
      color: var(--hp-link, #2b7fff); text-decoration: none;
      border-bottom: 2px solid currentColor; padding-bottom: 1px;
      font-weight: 500;
    }
    .air-link:hover { opacity: 0.85; }

    .air-haze-card {
      background: var(--color-haze, #f5f5f5); border-radius: var(--hp-radius-card, 12px);
      padding: 20px; color: var(--color-ink, #1b1b1b); border: none; box-shadow: none;
    }
    [data-theme="light"] .air-haze-card {
      background: #fff; border: 1px solid var(--hp-border-card);
    }

    .air-cursive { font-family: var(--hp-font-cursive); font-style: normal; font-weight: 400; }
    .air-display {
      font-family: var(--hp-font-display); font-weight: 400; text-transform: uppercase;
      line-height: 0.9; letter-spacing: -0.02em; color: var(--hp-text);
    }
    .air-section-kicker {
      font-size: 13px; font-weight: 500; letter-spacing: 0.08em; text-transform: uppercase;
      color: var(--color-twilight-blue, #426188); margin-bottom: 12px;
    }
    .air-section-title {
      font-size: clamp(1.75rem, 4vw, 2.25rem); font-weight: 500; line-height: 1.1;
      color: var(--hp-text); letter-spacing: -0.02em;
    }
    .air-section-title .air-cursive { font-size: 1.15em; color: var(--hp-text); }
"""


def air_public_styles_block() -> str:
    """Full Air token + component CSS for embedding in public pages."""
    return AIR_TOKENS_CSS + AIR_COMPONENTS_CSS
