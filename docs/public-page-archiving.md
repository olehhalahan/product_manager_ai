# Public page archiving (manual)

Cartozo.ai does **not** automate submissions to Internet Archive or third-party archival services.

## Why archive manually

Stable snapshots of marketing pages can help research, citation audits, and change tracking. Archiving is **not** a search-indexing substitute.

## Safe URLs to archive

Submit manually via [Save Page Now](https://web.archive.org/save) or similar:

- `https://cartozo.ai/`
- `https://cartozo.ai/pricing`
- `https://cartozo.ai/faq`
- `https://cartozo.ai/guides`
- Use-case pages under `/use-cases/`
- Example pages under `/examples/`
- `https://cartozo.ai/feed-structure`
- Key guides under `/guides/`

## Never archive

- `/login`, `/upload`, `/admin`, `/dashboard`, `/app`
- `/batches/*`, `/merchant/*`, `/api/*`
- Any URL requiring authentication
- User-uploaded feeds or exports
- Customer-specific data

## Process

1. Confirm URL is public (200, no login).
2. Use Save Page Now once per major release.
3. Record archive URL in your internal change log (optional).
4. Do not commit archive URLs or credentials to the repo.

## Automation

No automated external archival calls are implemented. Add automation only after legal/privacy review.
