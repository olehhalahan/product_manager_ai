"""Tests for IndexNow URL filtering and payload generation."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("DEPLOY_URL", "https://cartozo.ai")
os.environ.setdefault("INDEXNOW_KEY", "test-indexnow-key-abc123")
os.environ.setdefault("INDEXNOW_ENABLED", "true")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-at-least-32-chars-long")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test.apps.googleusercontent.com")
os.environ.setdefault("SECRETS_ENCRYPTION_KEY", "dGVzdF9rZXlfMzJfYnl0ZXNfbG9uZ19lbm91Z2g=")


class IndexNowTests(unittest.TestCase):
    def test_payload_shape(self):
        from app.indexnow import build_indexnow_payload

        payload = build_indexnow_payload(["https://cartozo.ai/faq"])
        self.assertEqual(payload["host"], "cartozo.ai")
        self.assertEqual(payload["key"], "test-indexnow-key-abc123")
        self.assertTrue(payload["keyLocation"].endswith("/test-indexnow-key-abc123.txt"))
        self.assertEqual(payload["urlList"], ["https://cartozo.ai/faq"])

    def test_rejects_private_urls(self):
        from app.indexnow import submit_indexnow_urls

        result = submit_indexnow_urls(
            [
                "https://cartozo.ai/upload",
                "https://cartozo.ai/admin/settings",
                "http://localhost:8000/faq",
            ]
        )
        self.assertEqual(result.get("submitted"), 0)
        self.assertGreaterEqual(result.get("rejected", 0), 1)

    def test_accepts_public_urls(self):
        from app.public_urls import filter_production_public_urls

        accepted, rejected = filter_production_public_urls(
            [
                "https://cartozo.ai/examples",
                "https://cartozo.ai/templates/sample.csv",
                "https://cartozo.ai/login",
            ]
        )
        self.assertIn("https://cartozo.ai/examples", accepted)
        self.assertEqual(len(rejected), 2)


class SeoDiscoveryTests(unittest.TestCase):
    def test_robots_policy_safe_precedence(self):
        from app.public_urls import PRIVATE_ROUTE_PREFIXES
        from app.robots_txt import is_path_allowed_for_agent, validate_robots_policy
        from app.seo import build_robots_txt_body

        body = build_robots_txt_body("https://cartozo.ai")
        self.assertIn("User-agent: *", body)
        self.assertIn("Sitemap: https://cartozo.ai/sitemap.xml", body)
        self.assertNotIn("User-agent: CCBot", body)
        self.assertTrue(is_path_allowed_for_agent(body, "CCBot", "/pricing"))
        self.assertFalse(is_path_allowed_for_agent(body, "CCBot", "/admin"))
        errors = validate_robots_policy(
            body,
            sitemap_url="https://cartozo.ai/sitemap.xml",
            private_prefixes=PRIVATE_ROUTE_PREFIXES,
        )
        self.assertEqual(errors, [])

    def test_rss_feed_xml_valid(self):
        from app.seo import build_rss_feed_xml

        xml = build_rss_feed_xml(
            items=[
                {
                    "title": "Test",
                    "link": "https://cartozo.ai/faq",
                    "description": "FAQ page",
                    "pubDate": "Fri, 03 Jul 2026 12:00:00 GMT",
                    "guid": "https://cartozo.ai/faq",
                    "category": "Evergreen",
                }
            ]
        )
        self.assertIn("<rss version=\"2.0\"", xml)
        self.assertIn("https://cartozo.ai/faq", xml)

    def test_x_robots_private_paths(self):
        from app.security import _x_robots_tag_for_path

        self.assertEqual(_x_robots_tag_for_path("/upload"), "noindex, nofollow")
        self.assertEqual(_x_robots_tag_for_path("/batches/abc/export"), "noindex, nofollow")
        self.assertIsNone(_x_robots_tag_for_path("/examples"))

    def test_sitemap_includes_examples(self):
        from app.seo import PUBLIC_SITEMAP_STATIC

        paths = [p for p, _, _ in PUBLIC_SITEMAP_STATIC]
        self.assertIn("/examples", paths)
        self.assertIn("/examples/google-shopping-feed-before-after", paths)


if __name__ == "__main__":
    unittest.main()
