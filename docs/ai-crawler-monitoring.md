# AI crawler monitoring (nginx access logs)

Cartozo.ai exposes public marketing pages, `/robots.txt`, `/sitemap.xml`, `/llms.txt`, and `/feed.xml` for search and answer-engine crawlers. Use server logs to observe crawl activity—not as a ranking guarantee, but to catch accidental blocks after deploys, WAF changes, or cache misconfiguration.

## Important limitations

- **User-Agent strings can be spoofed.** Treat log matches as hints, not proof of identity.
- Verify suspicious traffic with official crawler documentation and IP ranges where available:
  - [OpenAI GPTBot / OAI-SearchBot](https://platform.openai.com/docs/gptbot)
  - [Anthropic crawlers](https://support.anthropic.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web)
  - [Google crawlers](https://developers.google.com/search/docs/crawling-indexing/overview-google-crawlers)
  - [Bing / Microsoft](https://www.bing.com/webmasters/help/which-crawlers-does-bing-use-8c184ec0)
  - [Perplexity](https://docs.perplexity.ai/guides/bots)

## Weekly checks

1. Bot visits (volume and new user agents)
2. Top crawled URLs (especially new use-case and guide pages)
3. `403`, `429`, and `5xx` responses for important bots
4. Changes after robots.txt, CDN, or WAF updates

## Commands (nginx)

Replace log paths for your host. These examples assume rotated logs under `/var/log/nginx/`.

### Match AI / search crawlers in access logs

```bash
zgrep -hE 'OAI-SearchBot|GPTBot|ChatGPT-User|ClaudeBot|Claude-SearchBot|Claude-User|PerplexityBot|Perplexity-User|bingbot|Googlebot|GoogleOther|Google-InspectionTool|CCBot' /var/log/nginx/access.log*
```

### Count hits by user agent

```bash
zgrep -hE 'OAI-SearchBot|GPTBot|ChatGPT-User|ClaudeBot|Claude-SearchBot|Claude-User|PerplexityBot|Perplexity-User|bingbot|Googlebot|GoogleOther|Google-InspectionTool|CCBot' /var/log/nginx/access.log* \
| awk -F\" '{print $6}' \
| sort | uniq -c | sort -nr
```

### Top requested URLs by OpenAI Search bot

```bash
zgrep -h 'OAI-SearchBot' /var/log/nginx/access.log* \
| awk '{print $7}' | sort | uniq -c | sort -nr | head -50
```

### 4xx / 5xx for important bots

```bash
zgrep -hE 'OAI-SearchBot|Claude-SearchBot|PerplexityBot|bingbot|Googlebot|CCBot' /var/log/nginx/access.log* \
| awk '$9 ~ /4[0-9][0-9]|5[0-9][0-9]/ {print $9, $7, $12}' | head -100
```

### Quick sanity: public SEO endpoints return 200

```bash
curl -sI https://cartozo.ai/robots.txt | head -1
curl -sI https://cartozo.ai/sitemap.xml | head -1
curl -sI https://cartozo.ai/llms.txt | head -1
curl -sI https://cartozo.ai/feed.xml | head -1
```

## Common Crawl (CCBot) policy

Cartozo.ai is a public SaaS marketing site. **`CCBot` is allowed** on public pages in `/robots.txt` so Common Crawl may snapshot marketing content.

**Tradeoff:** marketing copy may appear in Common Crawl datasets. **User/customer data is never exposed** — `/upload`, `/batches`, `/admin`, and auth routes are disallowed or require login. CCBot does not execute JavaScript; important pages are server-rendered HTML.

Private routes remain blocked for all bots via global `Disallow` rules (`/admin`, `/api/`, `/upload`, `/login`, `/auth/`, `/merchant/`, `/batches/`, etc.).

## Bots to monitor

| Bot | Policy | Purpose |
|---|---|---|
| OAI-SearchBot | Allow | ChatGPT Search |
| ChatGPT-User | Allow | ChatGPT browsing |
| GPTBot | Disallow | OpenAI training |
| Claude-SearchBot | Allow | Claude search |
| Claude-User | Allow | Claude browsing |
| ClaudeBot | Disallow | Anthropic training |
| PerplexityBot | Allow | Perplexity search |
| Perplexity-User | Allow | Perplexity browsing |
| Googlebot | Allow | Google Search |
| GoogleOther | (via Googlebot rules) | Google auxiliary fetches |
| bingbot | Allow | Bing / Copilot |
| CCBot | Allow | Common Crawl snapshots |

## AI referral tracking (GA4 / logs)

Watch referrers and UTM sources in analytics:

- `utm_source=chatgpt.com`
- Referrers: `chatgpt.com`, `perplexity.ai`, `claude.ai`, `copilot.microsoft.com`, `bing.com`, `google.com`

In GA4: **Reports → Acquisition → Traffic acquisition** — filter by session source/medium or add exploration for referral path.

In nginx logs:

```bash
zgrep -hE 'chatgpt\.com|perplexity\.ai|claude\.ai|copilot\.microsoft\.com' /var/log/nginx/access.log* | head -50
```

## Weekly report template

| Date | Bot / UA | Hits | Top URLs | 4xx | 5xx | Suspicious blocks | AI referrals | Pages cited (manual) | Next action |
|------|----------|------|----------|-----|-----|-------------------|--------------|----------------------|-------------|
| YYYY-MM-DD | bingbot | | | | | | | | |
| YYYY-MM-DD | OAI-SearchBot | | | | | | | | |

## Private path alerts

Alert if bots repeatedly hit (should be 401/403/302, not 200 with content):

```bash
zgrep -hE '/upload|/admin|/batches/|/api/' /var/log/nginx/access.log* \
| grep -E 'OAI-SearchBot|bingbot|Googlebot|CCBot' | awk '$9 == 200' | head -20
```

## After Cartozo deploys

- Regenerate cached sitemap/robots from **Settings → SEO** if your environment serves cached copies.
- Confirm new landing pages (`/use-cases/*`, `/guides/*`, `/examples/*`) appear in `/sitemap.xml`.
- Submit IndexNow batch if enabled: `python3 scripts/submit_indexnow.py submit-indexnow-all-public` (see `docs/indexnow.md`).
- Re-run bot error checks within 24–48 hours of robots or middleware changes.
