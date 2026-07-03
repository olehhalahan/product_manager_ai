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


if __name__ == "__main__":
    unittest.main()
