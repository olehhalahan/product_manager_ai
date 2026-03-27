# Public site SEO and server-rendered HTML

## How public pages are rendered

The marketing site and blog are **not** a client-only SPA shell. FastAPI returns **full HTML documents** as strings (or composed templates): the response body already contains visible text, headings, and links. Browsers may run JavaScript for theme, navigation polish, and forms, but **the main content and metadata are present on the first response** without waiting for client-side data fetching.

Canonical URLs and Open Graph use the same base as sitemaps: set **`DEPLOY_URL`** in production (e.g. `https://cartozo.ai`) so `canonical`, `og:url`, and sitemap `loc` match the live domain.

## Adding a new SEO public page

1. Add a route in `app/main.py` (or a dedicated module) that returns `HTMLResponse` with a full HTML document.
2. Include in `<head>`: unique `<title>`, `<meta name="description">`, canonical (`<link rel="canonical">`), `og:url`, `og:title`, `og:description`, Twitter card tags (`app/seo.py` helpers: `head_canonical_social` or `head_canonical_og_url_type` when OG is already duplicated elsewhere).
3. Ensure the body has a single clear `<h1>` and real copy (not an empty root div).
4. Add the path to `_build_sitemap_xml_body` static list in `app/main.py` if the URL should be indexed.
5. Regenerate cached sitemap/robots from **Settings** if you use the admin snapshot feature.

Legal-style pages can reuse `build_legal_document_html` in `app/legal_document_page.py`. FAQ with structured data can follow `app/faq_page.py` (`FAQPage` JSON-LD + `extra_head`).

## Metadata helpers (`app/seo.py`)

| Helper | Use |
|--------|-----|
| `public_site_base(request)` | Site origin for canonical URLs (respects `DEPLOY_URL`). |
| `head_canonical_social(...)` | Full block: canonical, `og:url`, `og:type`, optional `og:image` / `og:site_name`, Twitter title/description/image. |
| `head_canonical_og_url_type(...)` | When the page already has `og:title` / Twitter in the template; adds canonical + `og:url` + `og:type` only. |
| `website_json_ld(...)` | `WebSite` schema on the home page. |
| `blog_posting_json_ld(...)` | `BlogPosting` on `/blog/{slug}`. |
| `faq_page_json_ld(...)` | `FAQPage` on `/faq`. |

## CSR-only / low-SEO areas (by design)

These routes are **not** optimized for organic search; they may require login or are app UI:

- `/upload`, `/batches/*`, `/settings`, `/merchant/*`, `/admin/*`, `/login`, `/auth/*`, `/logout`
- Authenticated dashboards and internal tools

They remain **disallowed** in `robots.txt` where applicable so crawl budget stays on public URLs.

## Manual checks (Google Search Console / curl)

Replace `https://YOUR_DOMAIN` with production `DEPLOY_URL` or your staging host.

| Page | URL |
|------|-----|
| Home | `https://YOUR_DOMAIN/` |
| Contact | `https://YOUR_DOMAIN/contact` |
| Features (presentation) | `https://YOUR_DOMAIN/presentation` |
| How it works | `https://YOUR_DOMAIN/how-it-works` |
| Pricing | `https://YOUR_DOMAIN/pricing` |
| Blog index | `https://YOUR_DOMAIN/blog` |
| FAQ | `https://YOUR_DOMAIN/faq` |
| Terms | `https://YOUR_DOMAIN/terms` |
| Privacy | `https://YOUR_DOMAIN/privacy` |
| Cookies | `https://YOUR_DOMAIN/cookies` |
| Refund | `https://YOUR_DOMAIN/refund-policy` |
| Blog article (examples) | `https://YOUR_DOMAIN/blog/<slug>` (use three real slugs from production) |

**Verify:** `curl -sI` returns `200` for each URL; `curl -s` HTML contains `<h1>`, unique `<title>`, `<meta name="description">`, and `<link rel="canonical">` pointing at the same host you intend to index.

## Sitemap and robots

- **`/sitemap.xml`**: static marketing URLs + published `/blog/{slug}` entries (see `_build_sitemap_xml_body`).
- **`/robots.txt`**: references `Sitemap: …/sitemap.xml`; disallows app/admin/auth areas.

After changing public routes, run **Regenerate sitemap & robots** in admin if cached snapshots are enabled.
