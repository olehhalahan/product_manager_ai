# SEO file indexing policy

Cartozo.ai separates **public marketing assets** from **private/generated user files**.

## Private / generated / user files

Routes that serve customer data or app exports:

| Route pattern | Protection |
|---|---|
| `/upload`, `/login`, `/settings`, `/admin/*` | Auth + `X-Robots-Tag: noindex, nofollow` |
| `/api/*` | Auth or API-only; `noindex` header |
| `/batches/*/export*` | Login required + `X-Robots-Tag: noindex, nofollow` on CSV responses |
| `/merchant/*` | Auth + `noindex` header |
| User-uploaded feeds | Never public; not in sitemap, llms.txt, RSS, or schema |

These URLs must **never** appear in:

- `/sitemap.xml`
- `/llms.txt`
- `/feed.xml`
- JSON-LD `Dataset` / `DataDownload`
- IndexNow submissions

## Public sample files (intentional)

| Asset | Policy |
|---|---|
| `/examples/*` HTML pages | Indexable; in sitemap and llms.txt |
| `/templates/*.csv` | Public download for templates; `X-Robots-Tag: noindex` on raw CSV; landing page `/examples` is indexed |
| Blog/guide images under `/static/` | Served as static assets; linked from public pages |

All sample CSV data is **fictional** (example.com URLs, demo SKUs). No real customer catalogs.

## Discovery files

| File | Purpose |
|---|---|
| `/sitemap.xml` | Canonical HTML pages only |
| `/llms.txt` | Curated high-intent pages for LLM agents |
| `/feed.xml` | RSS for blog + guides + evergreen pages |
| `/{INDEXNOW_KEY}.txt` | IndexNow verification |

## Middleware

`SecurityHeadersMiddleware` sets `X-Robots-Tag: noindex, nofollow` for private path prefixes (see `app/security.py`).

CSV export handlers also set the header explicitly on `StreamingResponse`.

## Operational checklist

1. Before adding a new download route, decide public vs private.
2. If private: require auth and/or `noindex`.
3. If public sample: use fictional data and link from an indexable landing page.
4. Run `python3 scripts/production_qa.py` before deploy.
