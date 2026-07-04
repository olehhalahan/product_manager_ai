"""Tests for traffic classification."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("SESSION_SECRET", "test-session-secret-at-least-32-chars-long")


class TrafficClassificationTests(unittest.TestCase):
    def test_googlebot_is_search_bot(self):
        from app.traffic import VISITOR_SEARCH_BOT, classify_user_agent

        c = classify_user_agent("Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)")
        self.assertEqual(c.visitor_class, VISITOR_SEARCH_BOT)
        self.assertTrue(c.is_bot)
        self.assertEqual(c.bot_name, "Googlebot")

    def test_gptbot_is_training_bot(self):
        from app.traffic import VISITOR_TRAINING_BOT, classify_user_agent

        c = classify_user_agent("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.0; +https://openai.com/gptbot)")
        self.assertEqual(c.visitor_class, VISITOR_TRAINING_BOT)

    def test_chrome_is_human(self):
        from app.traffic import VISITOR_HUMAN, classify_user_agent

        c = classify_user_agent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        self.assertEqual(c.visitor_class, VISITOR_HUMAN)
        self.assertFalse(c.is_bot)

    def test_should_not_track_api(self):
        from app.traffic import should_track_path

        self.assertFalse(should_track_path("/api/contact", "GET"))
        self.assertTrue(should_track_path("/faq", "GET"))

    def test_ensure_traffic_analytics_schema_creates_site_visit_events(self):
        import os
        import tempfile
        from sqlalchemy import create_engine, inspect, text

        from app.db import ensure_traffic_analytics_schema

        path = tempfile.mktemp(suffix=".db")
        engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE blog_article_view_events (id INTEGER PRIMARY KEY, article_id INTEGER, viewed_at DATETIME)"
                )
            )
        old_engine = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = f"sqlite:///{path}"
        try:
            import app.db as db_mod

            db_mod.engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
            ensure_traffic_analytics_schema()
            insp = inspect(db_mod.engine)
            self.assertIn("site_visit_events", insp.get_table_names())
            cols = {c["name"] for c in insp.get_columns("blog_article_view_events")}
            self.assertIn("visitor_class", cols)
        finally:
            if old_engine is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old_engine


if __name__ == "__main__":
    unittest.main()
