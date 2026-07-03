# AI crawler monitoring (nginx access logs)

Cartozo.ai exposes public marketing pages, `/robots.txt`, `/sitemap.xml`, and `/llms.txt` for search and answer-engine crawlers. Use server logs to observe crawl activity—not as a ranking guarantee, but to catch accidental blocks after deploys, WAF changes, or cache misconfiguration.

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
zgrep -hE 'OAI-SearchBot|GPTBot|ChatGPT-User|ClaudeBot|Claude-SearchBot|Claude-User|PerplexityBot|Perplexity-User|bingbot|Googlebot|GoogleOther|Google-InspectionTool' /var/log/nginx/access.log*
```

### Count hits by user agent

```bash
zgrep -hE 'OAI-SearchBot|GPTBot|ChatGPT-User|ClaudeBot|Claude-SearchBot|Claude-User|PerplexityBot|Perplexity-User|bingbot|Googlebot|GoogleOther|Google-InspectionTool' /var/log/nginx/access.log* \
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
zgrep -hE 'OAI-SearchBot|Claude-SearchBot|PerplexityBot|bingbot|Googlebot' /var/log/nginx/access.log* \
| awk '$9 ~ /4[0-9][0-9]|5[0-9][0-9]/ {print $9, $7, $12}' | head -100
```

### Quick sanity: public SEO endpoints return 200

```bash
curl -sI https://cartozo.ai/robots.txt | head -1
curl -sI https://cartozo.ai/sitemap.xml | head -1
curl -sI https://cartozo.ai/llms.txt | head -1
```

## After Cartozo deploys

- Regenerate cached sitemap/robots from **Settings → SEO** if your environment serves cached copies.
- Confirm new landing pages (`/use-cases/*`, `/guides/*`) appear in `/sitemap.xml`.
- Re-run bot error checks within 24–48 hours of robots or middleware changes.
