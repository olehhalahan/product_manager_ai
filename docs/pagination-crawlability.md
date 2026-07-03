# Pagination and listing crawlability

## Current behavior (2026-07)

| Listing | Pagination | Canonical | Notes |
|---|---|---|---|
| `/blog` | None — up to 300 posts on one page | Self (`/blog`) | Search uses `?q=`; query stripped from canonical |
| `/blog/topics/{slug}` | None | Self per topic | Empty hubs: `noindex,follow` until posts assigned |
| `/guides` | None | `/guides` | Static index |
| `/examples` | None | `/examples` | Static index |

There is **no** `page=2` pagination today. Blog does not use JS-only “Load more” for primary listing.

## Guardrails for future pagination

If numeric pagination is added:

1. Each page gets a unique URL (`/blog?page=2` or `/blog/page/2`).
2. Each paginated page uses a **self-referencing canonical** — never canonicalize page 2+ to page 1.
3. Use real `<a href>` links for next/previous/page numbers (not JS-only).
4. Empty pages return 404 or `noindex`, not thin indexable content.
5. Include only page 1 (or representative pages) in sitemap unless each page has unique value.

## Topic hub empty state

Implemented in `writter_routes.py`:

- Topic with zero posts → `<meta name="robots" content="noindex,follow">`
- Topic remains out of sitemap until populated (QA verifies)

## Faceted URLs

Do not index infinite filter combinations (e.g. `/blog?q=...` with many variants). Current search canonicalizes to `/blog`.

## QA

`scripts/production_qa.py` checks:

- No unexpected `noindex` on core marketing pages
- Topic hub `noindex` documented as intentional when empty
- Warning if pagination links appear without matching self-canonical
