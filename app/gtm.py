"""Google Tag Manager snippets with path-based inclusion (exclude private / app surfaces from GA)."""

from __future__ import annotations

import os
from typing import Optional

_GTM_ID = os.getenv("GTM_CONTAINER_ID", "GTM-W25B668S")

_GOOGLE_SITE_VERIFICATION = os.getenv(
    "GOOGLE_SITE_VERIFICATION",
    "PBIv7Juyd9qX3pFJ-8NbZXkVKhMy0jdQZd3YvG1WiB8",
).strip()

_GSC_META_LINE = (
    f'    <meta name="google-site-verification" content="{_GOOGLE_SITE_VERIFICATION}" />\n'
    if _GOOGLE_SITE_VERIFICATION
    else ""
)

# No GTM on these first path segments (admin, authenticated app, APIs).
_GTM_EXCLUDED_FIRST_SEGMENTS = frozenset(
    {
        "admin",
        "api",
        "auth",
        "batches",
        "docs",
        "merchant",
        "settings",
        "upload",
    }
)

_GTM_EXCLUDED_PATH_NORMALIZED = frozenset({"login", "logout"})


def should_include_gtm(path: Optional[str]) -> bool:
    if path is None:
        return True
    raw = path.split("?", 1)[0].strip() or "/"
    if not raw.startswith("/"):
        raw = "/" + raw
    seg0 = raw.strip("/").split("/")[0].lower() if raw.strip("/") else ""
    if seg0 in _GTM_EXCLUDED_PATH_NORMALIZED:
        return False
    if not seg0:
        return True
    return seg0 not in _GTM_EXCLUDED_FIRST_SEGMENTS


def _base_head_snippet() -> str:
    return f"""    <link rel="icon" href="/assets/favicon.png" type="image/png" />
    <link rel="shortcut icon" href="/assets/favicon.png" type="image/png" />
{_GSC_META_LINE}    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
"""


def _gtm_script_snippet() -> str:
    return f"""    <!-- Google Tag Manager -->
    <script>(function(w,d,s,l,i){{w[l]=w[l]||[];w[l].push({{'gtm.start':
new Date().getTime(),event:'gtm.js'}});var f=d.getElementsByTagName(s)[0],
j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
}})(window,document,'script','dataLayer','{_GTM_ID}');</script>
    <!-- End Google Tag Manager -->
"""


def _gtm_noscript_snippet() -> str:
    return f"""    <!-- Google Tag Manager (noscript) -->
    <noscript><iframe src="https://www.googletagmanager.com/ns.html?id={_GTM_ID}"
height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>
    <!-- End Google Tag Manager (noscript) -->
"""


def gtm_head_for_path(path: Optional[str]) -> str:
    """Favicon, fonts, optional GSC meta, and GTM script when the URL is a public/marketing surface."""
    base = _base_head_snippet()
    return base + _gtm_script_snippet() if should_include_gtm(path) else base


def gtm_body_for_path(path: Optional[str]) -> str:
    """GTM noscript fallback; empty on excluded paths."""
    return _gtm_noscript_snippet() if should_include_gtm(path) else ""


# Full public snippets (e.g. homepage, /blog, legal pages).
GTM_HEAD = _base_head_snippet() + _gtm_script_snippet()
GTM_BODY = _gtm_noscript_snippet()
