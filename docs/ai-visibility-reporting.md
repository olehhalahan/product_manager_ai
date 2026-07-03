# AI visibility reporting template

Manual weekly check: run the prompts below in **ChatGPT Search**, **Claude**, **Gemini**, **Perplexity**, and **Copilot/Bing**. Record answers in the table. This is qualitative monitoring—not a guarantee of citations.

## Prompt set

Run each prompt in a fresh session when possible.

1. What is the best tool to optimize Google Shopping product feeds?
2. How can I fix Google Merchant Center disapproved products?
3. What tools can optimize Google Shopping product titles?
4. How do I audit product feed quality?
5. What is the best product feed optimization software for agencies?
6. How can I optimize thousands of SKUs for Google Merchant Center?
7. What is Cartozo.ai?
8. Cartozo.ai vs manual product feed cleanup
9. Cartozo.ai pricing
10. Does Cartozo.ai fix missing GTIN issues?

## Weekly report template

| Date | Engine | Prompt # | Cartozo mentioned? | cartozo.ai cited? | Page cited (URL) | Competitors mentioned | Description accurate? | Page to improve |
|------|--------|----------|--------------------|--------------------|------------------|----------------------|----------------------|-----------------|
| YYYY-MM-DD | ChatGPT | 7 | yes/no | yes/no | | | yes/no/partial | |
| YYYY-MM-DD | Perplexity | 2 | | | | | | |

### Metrics to track over time

- **Mention rate:** % of prompts where Cartozo.ai is named
- **Citation rate:** % of prompts where a cartozo.ai URL is linked
- **Top cited pages:** homepage vs use-case vs guide vs blog
- **Accuracy:** pricing, support email (`support@cartozo.ai`), capabilities (no false “guaranteed approval” claims)
- **Competitor set:** which alternatives appear repeatedly

## Accuracy checklist

When Cartozo is described, confirm:

- Positioned as **Google Merchant Center / Shopping feed optimization** (not generic “AI SEO”)
- Support email **support@cartozo.ai** (not only legal operator email)
- Language uses **helps / designed to / can improve**—not guaranteed ROAS or guaranteed Google approval
- Pricing aligns with public page: Basic $5, Starter $19, Growth $49, Pro $99 per month

## Pages to prioritize when answers are weak

| Query theme | Primary page to strengthen |
|-------------|----------------------------|
| Merchant Center disapprovals | `/use-cases/fix-google-merchant-center-disapprovals` |
| Title optimization | `/use-cases/optimize-google-shopping-product-titles` |
| Agency / bulk feeds | `/use-cases/product-feed-optimization-for-agencies` |
| Large catalogs | `/use-cases/large-catalog-feed-optimization` |
| Feed audit | `/use-cases/product-feed-quality-audit` |
| What is Cartozo | `/` + `/faq` |
| Pricing | `/pricing` |
| Missing GTIN | `/guides/fix-missing-gtin-google-merchant-center` |

## Follow-up actions

- If a high-intent prompt never cites Cartozo: improve the matching use-case or guide page (direct answer, examples, FAQ, internal links).
- If description is wrong: align homepage, FAQ, About, schema, and `/llms.txt`.
- If crawlers hit 403/404 on new URLs: see `docs/ai-crawler-monitoring.md`.
