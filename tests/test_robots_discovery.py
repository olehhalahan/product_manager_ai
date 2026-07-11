"""Regression tests for robots.txt policy, discovery endpoints, and private-route filtering."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("DEPLOY_URL", "https://cartozo.ai")
os.environ.setdefault("INDEXNOW_KEY", "test-indexnow-key-abc123")
os.environ.setdefault("INDEXNOW_ENABLED", "true")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-at-least-32-chars-long")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test.apps.googleusercontent.com")
os.environ.setdefault("SECRETS_ENCRYPTION_KEY", "dGVzdF9rZXlfMzJfYnl0ZXNfbG9uZ19lbm91Z2g=")

from fastapi.testclient import TestClient


class RobotsPolicyTests(unittest.TestCase):
    def setUp(self):
        from app.seo import build_robots_txt_body

        self.body = build_robots_txt_body("https://cartozo.ai")
        self.base = "https://cartozo.ai"

    def test_wildcard_allows_public_blocks_private(self):
        from app.robots_txt import is_path_allowed_for_agent

        for agent in ("Googlebot", "CCBot", "OAI-SearchBot", "PerplexityBot"):
            self.assertTrue(is_path_allowed_for_agent(self.body, agent, "/pricing"), agent)
            self.assertFalse(is_path_allowed_for_agent(self.body, agent, "/admin"), agent)
            self.assertFalse(is_path_allowed_for_agent(self.body, agent, "/upload"), agent)
            self.assertFalse(is_path_allowed_for_agent(self.body, agent, "/batches/abc"), agent)

    def test_training_bots_blocked_site_wide(self):
        from app.robots_txt import is_path_allowed_for_agent

        for agent in ("GPTBot", "ClaudeBot", "Google-Extended"):
            self.assertFalse(is_path_allowed_for_agent(self.body, agent, "/"))
            self.assertFalse(is_path_allowed_for_agent(self.body, agent, "/pricing"))

    def test_no_explicit_allow_only_groups(self):
        from app.robots_txt import parse_robots_txt

        for group in parse_robots_txt(self.body):
            if "*" in group.user_agents:
                continue
            if group.allow and not group.disallow:
                self.fail(f"group {group.user_agents} has Allow without Disallow")

    def test_validate_robots_policy_passes(self):
        from app.public_urls import PRIVATE_ROUTE_PREFIXES
        from app.robots_txt import validate_robots_policy

        errors = validate_robots_policy(
            self.body,
            sitemap_url=f"{self.base}/sitemap.xml",
            private_prefixes=PRIVATE_ROUTE_PREFIXES,
        )
        self.assertEqual(errors, [], errors)

    def test_sitemap_line_present(self):
        self.assertIn("Sitemap: https://cartozo.ai/sitemap.xml", self.body)


class DiscoveryHeadTests(unittest.TestCase):
    def setUp(self):
        from app.main import app

        self.client = TestClient(app, raise_server_exceptions=True)

    def test_head_discovery_endpoints(self):
        endpoints = [
            ("/", "text/html"),
            ("/robots.txt", "text/plain"),
            ("/sitemap.xml", "xml"),
            ("/llms.txt", "text/plain"),
            ("/feed.xml", "rss"),
            ("/examples", "text/html"),
        ]
        for path, kind in endpoints:
            get_r = self.client.get(path)
            head_r = self.client.head(path)
            self.assertEqual(get_r.status_code, 200, path)
            self.assertEqual(head_r.status_code, 200, path)
            ctype = (head_r.headers.get("content-type") or "").lower()
            if kind == "text/plain":
                self.assertIn("text/plain", ctype, path)
            elif kind == "xml":
                self.assertTrue("xml" in ctype, path)
            elif kind == "rss":
                self.assertTrue("xml" in ctype, path)
            elif kind == "text/html":
                self.assertIn("text/html", ctype, path)

    def test_get_head_content_length_matches(self):
        for path in ("/robots.txt", "/sitemap.xml", "/llms.txt", "/feed.xml"):
            get_r = self.client.get(path)
            head_r = self.client.head(path)
            self.assertEqual(head_r.headers.get("content-length"), str(len(get_r.content)), path)


class PrivateRouteFilteringTests(unittest.TestCase):
    def test_shared_private_prefixes_used_everywhere(self):
        from app.public_urls import PRIVATE_ROUTE_PREFIXES, is_private_path
        from app.security import _x_robots_tag_for_path

        for path in ("/admin/seo", "/upload", "/batches/1/export", "/api/settings"):
            self.assertTrue(is_private_path(path), path)
            self.assertEqual(_x_robots_tag_for_path(path), "noindex, nofollow", path)

        self.assertFalse(is_private_path("/pricing"))
        self.assertIsNone(_x_robots_tag_for_path("/examples"))

        self.assertIn("/admin", PRIVATE_ROUTE_PREFIXES)
        self.assertIn("/batches", PRIVATE_ROUTE_PREFIXES)

    def test_indexnow_rejects_private_urls(self):
        from app.public_urls import filter_production_public_urls

        accepted, rejected = filter_production_public_urls(
            [
                "https://cartozo.ai/examples",
                "https://cartozo.ai/batches/1/export",
                "https://cartozo.ai/login",
            ]
        )
        self.assertIn("https://cartozo.ai/examples", accepted)
        self.assertEqual(len(rejected), 2)

    def test_sitemap_static_paths_exclude_private(self):
        from app.public_urls import is_private_path
        from app.seo import PUBLIC_SITEMAP_STATIC

        for path, _, _ in PUBLIC_SITEMAP_STATIC:
            self.assertFalse(is_private_path(path), path)
        self.assertNotIn("/features", [p for p, _, _ in PUBLIC_SITEMAP_STATIC])


class IndexNowRouteOrderTests(unittest.TestCase):
    def test_discovery_paths_not_shadowed_by_indexnow_key(self):
        from app.main import app

        paths = {getattr(r, "path", None) for r in app.routes}
        for required in ("/robots.txt", "/sitemap.xml", "/llms.txt", "/feed.xml"):
            self.assertIn(required, paths, f"missing route {required}")

        key = os.environ.get("INDEXNOW_KEY", "").strip()
        if key:
            self.assertIn(f"/{key}.txt", paths)
            self.assertNotEqual(key, "robots")
            self.assertNotEqual(key, "sitemap")
            self.assertNotEqual(key, "llms")
            self.assertNotEqual(key, "feed")


if __name__ == "__main__":
    unittest.main()
