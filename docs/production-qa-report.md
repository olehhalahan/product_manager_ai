# Cartozo.ai AI Visibility — Production QA Report

**Safe to merge:** Yes
**Production base URL:** `https://cartozo.ai` (via `DEPLOY_URL`)

## Summary

## URL status

| URL | Expected | Actual | Result | Notes |
|---|---|---|---|---|
| / | 200 | 200 | PASS |  |
| /presentation | 200 | 200 | PASS |  |
| /features | 301->/presentation | 301 -> /presentation | PASS |  |
| /use-cases/fix-google-merchant-center-disapprovals | 200 | 200 | PASS |  |
| /use-cases/optimize-google-shopping-product-titles | 200 | 200 | PASS |  |
| /use-cases/product-feed-optimization-for-agencies | 200 | 200 | PASS |  |
| /use-cases/large-catalog-feed-optimization | 200 | 200 | PASS |  |
| /use-cases/product-feed-quality-audit | 200 | 200 | PASS |  |
| /guides | 200 | 200 | PASS |  |
| /guides/google-merchant-center-feed-optimization | 200 | 200 | PASS |  |
| /guides/google-shopping-title-optimization | 200 | 200 | PASS |  |
| /guides/fix-missing-gtin-google-merchant-center | 200 | 200 | PASS |  |
| /guides/product-feed-quality-audit | 200 | 200 | PASS |  |
| /guides/product-feed-optimization-checklist | 200 | 200 | PASS |  |
| /guides/product-feed-optimization-for-large-catalogs | 200 | 200 | PASS |  |
| /feed-structure | 200 | 200 | PASS |  |
| /examples | 200 | 200 | PASS |  |
| /examples/google-shopping-feed-before-after | 200 | 200 | PASS |  |
| /examples/product-title-optimization-examples | 200 | 200 | PASS |  |
| /examples/product-feed-quality-audit-example | 200 | 200 | PASS |  |
| /templates/google-merchant-center-feed-template.csv | 200 | 200 | PASS |  |
| /templates/sample-product-feed-before.csv | 200 | 200 | PASS |  |
| /templates/sample-product-feed-after.csv | 200 | 200 | PASS |  |
| /blog | 200 | 200 | PASS |  |
| /blog/topics/google-merchant-center-issues | 200 | 200 | PASS | noindex (empty topic hub — intentional until posts assigned) |
| /blog/topics/product-title-and-description-optimization | 200 | 200 | PASS | noindex (empty topic hub — intentional until posts assigned) |
| /blog/topics/feed-quality-and-data-governance | 200 | 200 | PASS | noindex (empty topic hub — intentional until posts assigned) |
| /blog/topics/large-catalogs-and-agencies | 200 | 200 | PASS | noindex (empty topic hub — intentional until posts assigned) |
| /blog/topics/multichannel-and-marketplace-feeds | 200 | 200 | PASS | noindex (empty topic hub — intentional until posts assigned) |
| /faq | 200 | 200 | PASS |  |
| /about | 200 | 200 | PASS |  |
| /contact | 200 | 200 | PASS |  |
| /robots.txt | 200 | 200 | PASS |  |
| /sitemap.xml | 200 | 200 | PASS |  |
| /llms.txt | 200 | 200 | PASS |  |
| /feed.xml | 200 | 200 | PASS |  |

## SEO metadata

| URL | Title | Meta desc | Canonical | H1 | Indexable | Result |
|---|---|---|---|---|---|---|
| / | yes | yes | yes | 1 | yes | PASS |
| /presentation | yes | yes | yes | 1 | yes | PASS |
| /use-cases/fix-google-merchant-center-disapprovals | yes | yes | yes | 1 | yes | PASS |
| /use-cases/optimize-google-shopping-product-titles | yes | yes | yes | 1 | yes | PASS |
| /use-cases/product-feed-optimization-for-agencies | yes | yes | yes | 1 | yes | PASS |
| /use-cases/large-catalog-feed-optimization | yes | yes | yes | 1 | yes | PASS |
| /use-cases/product-feed-quality-audit | yes | yes | yes | 1 | yes | PASS |
| /guides | yes | yes | yes | 1 | yes | PASS |
| /guides/google-merchant-center-feed-optimization | yes | yes | yes | 1 | yes | PASS |
| /guides/google-shopping-title-optimization | yes | yes | yes | 1 | yes | PASS |
| /guides/fix-missing-gtin-google-merchant-center | yes | yes | yes | 1 | yes | PASS |
| /guides/product-feed-quality-audit | yes | yes | yes | 1 | yes | PASS |
| /guides/product-feed-optimization-checklist | yes | yes | yes | 1 | yes | PASS |
| /guides/product-feed-optimization-for-large-catalogs | yes | yes | yes | 1 | yes | PASS |
| /feed-structure | yes | yes | yes | 1 | yes | PASS |
| /examples | yes | yes | yes | 1 | yes | PASS |
| /examples/google-shopping-feed-before-after | yes | yes | yes | 1 | yes | PASS |
| /examples/product-title-optimization-examples | yes | yes | yes | 1 | yes | PASS |
| /examples/product-feed-quality-audit-example | yes | yes | yes | 1 | yes | PASS |
| /blog | yes | yes | yes | 1 | yes | PASS |
| /blog/topics/google-merchant-center-issues | yes | yes | yes | 1 | noindex | PASS |
| /blog/topics/product-title-and-description-optimization | yes | yes | yes | 1 | noindex | PASS |
| /blog/topics/feed-quality-and-data-governance | yes | yes | yes | 1 | noindex | PASS |
| /blog/topics/large-catalogs-and-agencies | yes | yes | yes | 1 | noindex | PASS |
| /blog/topics/multichannel-and-marketplace-feeds | yes | yes | yes | 1 | noindex | PASS |
| /faq | yes | yes | yes | 1 | yes | PASS |
| /about | yes | yes | yes | 1 | yes | PASS |
| /contact | yes | yes | yes | 1 | yes | PASS |

## Structured data

| URL | Schema types | Critical errors | Warnings | Result |
|---|---|---|---|---|
| / | Offer, Organization, SoftwareApplication, UnitPriceSpecification, WebSite | none |  | PASS |
| /pricing | BreadcrumbList, ListItem, Offer, Organization, SoftwareApplication, UnitPriceSpecification, WebPage, WebSite | none |  | PASS |
| /faq | Answer, BreadcrumbList, FAQPage, ListItem, Offer, Organization, Question, SoftwareApplication, UnitPriceSpecification, WebPage, WebSite | none |  | PASS |
| /about | BreadcrumbList, ListItem, Offer, Organization, SoftwareApplication, UnitPriceSpecification, WebPage, WebSite | none |  | PASS |
| /feed-structure | BreadcrumbList, ListItem, Offer, Organization, SoftwareApplication, UnitPriceSpecification, WebPage, WebSite | none |  | PASS |
| /examples | BreadcrumbList, DataDownload, Dataset, ListItem, Offer, Organization, SoftwareApplication, UnitPriceSpecification, WebPage, WebSite | none |  | PASS |
| /blog | BreadcrumbList, ListItem, Offer, Organization, SoftwareApplication, UnitPriceSpecification, WebPage, WebSite | none |  | PASS |
| /blog/topics/google-merchant-center-issues | BreadcrumbList, ListItem, Offer, Organization, SoftwareApplication, UnitPriceSpecification, WebPage, WebSite | none |  | PASS |
| /use-cases/fix-google-merchant-center-disapprovals | Answer, BreadcrumbList, FAQPage, ListItem, Offer, Organization, Question, SoftwareApplication, UnitPriceSpecification, WebPage, WebSite | none |  | PASS |
| /use-cases/optimize-google-shopping-product-titles | Answer, BreadcrumbList, FAQPage, ListItem, Offer, Organization, Question, SoftwareApplication, UnitPriceSpecification, WebPage, WebSite | none |  | PASS |
| /use-cases/product-feed-optimization-for-agencies | Answer, BreadcrumbList, FAQPage, ListItem, Offer, Organization, Question, SoftwareApplication, UnitPriceSpecification, WebPage, WebSite | none |  | PASS |
| /use-cases/large-catalog-feed-optimization | Answer, BreadcrumbList, FAQPage, ListItem, Offer, Organization, Question, SoftwareApplication, UnitPriceSpecification, WebPage, WebSite | none |  | PASS |
| /use-cases/product-feed-quality-audit | Answer, BreadcrumbList, FAQPage, ListItem, Offer, Organization, Question, SoftwareApplication, UnitPriceSpecification, WebPage, WebSite | none |  | PASS |
| /guides/google-merchant-center-feed-optimization | Answer, BreadcrumbList, FAQPage, ListItem, Offer, Organization, Question, SoftwareApplication, UnitPriceSpecification, WebPage, WebSite | none |  | PASS |
| /guides/google-shopping-title-optimization | Answer, BreadcrumbList, FAQPage, ListItem, Offer, Organization, Question, SoftwareApplication, UnitPriceSpecification, WebPage, WebSite | none |  | PASS |
| /guides/fix-missing-gtin-google-merchant-center | Answer, BreadcrumbList, FAQPage, ListItem, Offer, Organization, Question, SoftwareApplication, UnitPriceSpecification, WebPage, WebSite | none |  | PASS |
| /guides/product-feed-quality-audit | Answer, BreadcrumbList, FAQPage, ListItem, Offer, Organization, Question, SoftwareApplication, UnitPriceSpecification, WebPage, WebSite | none |  | PASS |
| /guides/product-feed-optimization-checklist | Answer, BreadcrumbList, FAQPage, ListItem, Offer, Organization, Question, SoftwareApplication, UnitPriceSpecification, WebPage, WebSite | none |  | PASS |
| /guides/product-feed-optimization-for-large-catalogs | Answer, BreadcrumbList, FAQPage, ListItem, Offer, Organization, Question, SoftwareApplication, UnitPriceSpecification, WebPage, WebSite | none |  | PASS |

## Sitemap / robots / llms

| File | HTTP | Broken URLs | Localhost/staging | Private URLs | Result |
|---|---|---|---|---|---|
| /sitemap.xml | 200 | none | none | none | PASS |
| /robots.txt | 200 | none | none | none | PASS |
| /llms.txt | 200 | none | none | none | PASS |
| /feed.xml | 200 | none | none | none | PASS |
| /qa-test-indexnow-key.txt | 200 | none | none | none | PASS |

## Post-deploy checklist

1. Confirm `DEPLOY_URL=https://cartozo.ai` in production `.env`
2. Regenerate sitemap/robots in Admin → Settings → SEO
3. Assign blog posts to content clusters in Writter admin
4. Submit sitemap in Google Search Console and Bing Webmaster Tools
5. Run `python3 scripts/submit_indexnow.py submit-indexnow-all-public` after major content updates
6. Remove `noindex` from topic hubs once posts are assigned (automatic when posts exist)
