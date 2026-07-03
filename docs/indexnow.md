# IndexNow setup (Cartozo.ai)

IndexNow notifies Bing and other compatible search engines when public URLs change.

## Environment

Set in production `.env`:

```txt
DEPLOY_URL=https://cartozo.ai
INDEXNOW_KEY=<generated-key>
INDEXNOW_ENABLED=true
```

Generate a stable key:

```bash
python -c "import secrets; print(secrets.token_hex(16))"
```

## Verify key file

After deploy, confirm:

```bash
curl -sS "https://cartozo.ai/${INDEXNOW_KEY}.txt"
```

Expected:

- HTTP `200`
- `Content-Type: text/plain`
- Body equals the key exactly (no trailing newline required, but must match)

## Submit one URL

```bash
DEPLOY_URL=https://cartozo.ai INDEXNOW_KEY=... INDEXNOW_ENABLED=true \
  python3 scripts/submit_indexnow.py submit-indexnow-url "https://cartozo.ai/faq"
```

## Submit all public URLs

Uses the same URL source as the sitemap (static pages + published blog posts):

```bash
DEPLOY_URL=https://cartozo.ai INDEXNOW_KEY=... INDEXNOW_ENABLED=true \
  python3 scripts/submit_indexnow.py submit-indexnow-all-public
```

Also runs automatically when an admin regenerates sitemap/robots (`POST /api/admin/regenerate-sitemap-robots`) if `INDEXNOW_ENABLED=true`.

## What not to submit

Never submit:

- `localhost` / staging URLs
- `/admin`, `/upload`, `/login`, `/auth/*`, `/api/*`, `/batches/*`, `/merchant/*`
- Raw user CSV exports or generated private files
- `/templates/*.csv` (landing pages at `/examples` are preferred)

The backend filters these before calling `https://api.indexnow.org/IndexNow`.

## Bing Webmaster Tools

1. Verify site ownership in [Bing Webmaster Tools](https://www.bingwebmaster.com/).
2. Submit sitemap: `https://cartozo.ai/sitemap.xml`
3. After IndexNow submission, check URL inspection / crawl stats for recently updated paths.
4. Review IndexNow API response in server logs (`cartozo.indexnow` logger).

## Troubleshooting

| Symptom | Check |
|---|---|
| Key file 404 | `INDEXNOW_KEY` set and matches filename |
| Submission skipped | `INDEXNOW_ENABLED=true` and `DEPLOY_URL=https://cartozo.ai` |
| All URLs rejected | `DEPLOY_URL` must be https production, not localhost |
| Batch failures | Server logs list failed URLs; retry with single-URL command |
