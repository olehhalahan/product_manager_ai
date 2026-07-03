"""Inbound traffic classification — bots vs humans for server-side analytics."""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

# Mirrors docs/ai-crawler-monitoring.md and robots.txt policy names.
_SEARCH_BOT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"googlebot", "Googlebot"),
    (r"googleother", "GoogleOther"),
    (r"google-inspectiontool", "Google-InspectionTool"),
    (r"bingbot", "bingbot"),
    (r"slurp", "Yahoo Slurp"),
    (r"duckduckbot", "DuckDuckBot"),
    (r"yandexbot", "YandexBot"),
    (r"baiduspider", "Baiduspider"),
    (r"applebot", "Applebot"),
    (r"petalbot", "PetalBot"),
)

_AI_BOT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"oai-searchbot", "OAI-SearchBot"),
    (r"chatgpt-user", "ChatGPT-User"),
    (r"claude-searchbot", "Claude-SearchBot"),
    (r"claude-user", "Claude-User"),
    (r"perplexitybot", "PerplexityBot"),
    (r"perplexity-user", "Perplexity-User"),
    (r"youbot", "YouBot"),
)

_TRAINING_BOT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"gptbot", "GPTBot"),
    (r"claudebot", "ClaudeBot"),
    (r"anthropic-ai", "Anthropic-AI"),
    (r"ccbot", "CCBot"),
    (r"facebookexternalhit", "FacebookExternalHit"),
    (r"meta-externalagent", "Meta-ExternalAgent"),
)

_MONITOR_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"uptimerobot", "UptimeRobot"),
    (r"pingdom", "Pingdom"),
    (r"statuscake", "StatusCake"),
    (r"headlesschrome", "HeadlessChrome"),
)

_GENERIC_BOT_RE = re.compile(
    r"bot|crawler|spider|scraper|curl/|wget/|python-requests|httpx/|go-http-client|java/|libwww",
    re.I,
)

_AI_REFERRER_DOMAINS = frozenset(
    {
        "chatgpt.com",
        "chat.openai.com",
        "perplexity.ai",
        "claude.ai",
        "copilot.microsoft.com",
        "bing.com",
        "gemini.google.com",
    }
)

VISITOR_HUMAN = "human"
VISITOR_SEARCH_BOT = "search_bot"
VISITOR_AI_BOT = "ai_bot"
VISITOR_TRAINING_BOT = "training_bot"
VISITOR_MONITOR = "monitor"
VISITOR_UNKNOWN_BOT = "unknown_bot"

HUMAN_CLASSES = frozenset({VISITOR_HUMAN})
BOT_CLASSES = frozenset(
    {
        VISITOR_SEARCH_BOT,
        VISITOR_AI_BOT,
        VISITOR_TRAINING_BOT,
        VISITOR_MONITOR,
        VISITOR_UNKNOWN_BOT,
    }
)


@dataclass(frozen=True)
class TrafficClassification:
    visitor_class: str
    bot_name: str = ""
    is_bot: bool = False


def _match_patterns(ua_lower: str, patterns: tuple[tuple[str, str], ...]) -> Optional[str]:
    for pattern, name in patterns:
        if re.search(pattern, ua_lower):
            return name
    return None


def classify_user_agent(user_agent: str) -> TrafficClassification:
    ua = (user_agent or "").strip()
    if not ua:
        return TrafficClassification(VISITOR_UNKNOWN_BOT, bot_name="Empty-UA", is_bot=True)
    low = ua.lower()
    for patterns, vclass in (
        (_SEARCH_BOT_PATTERNS, VISITOR_SEARCH_BOT),
        (_AI_BOT_PATTERNS, VISITOR_AI_BOT),
        (_TRAINING_BOT_PATTERNS, VISITOR_TRAINING_BOT),
        (_MONITOR_PATTERNS, VISITOR_MONITOR),
    ):
        name = _match_patterns(low, patterns)
        if name:
            return TrafficClassification(vclass, bot_name=name, is_bot=True)
    if _GENERIC_BOT_RE.search(low):
        return TrafficClassification(VISITOR_UNKNOWN_BOT, bot_name="Generic-Bot", is_bot=True)
    return TrafficClassification(VISITOR_HUMAN, is_bot=False)


def parse_referrer_domain(referrer: str) -> str:
    ref = (referrer or "").strip()
    if not ref:
        return ""
    try:
        host = (urlparse(ref).hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def classify_referrer(referrer: str) -> str:
    """Return a short label for AI/search referrers (empty if direct/unknown)."""
    host = parse_referrer_domain(referrer)
    if not host:
        return ""
    if host in _AI_REFERRER_DOMAINS or any(host.endswith("." + d) for d in _AI_REFERRER_DOMAINS):
        return host
    if "google." in host:
        return "google"
    if "bing." in host or host == "bing.com":
        return "bing"
    if host.endswith("cartozo.ai"):
        return "internal"
    return host


def hash_client_ip(ip: str) -> str:
    raw = (ip or "").strip()
    if not raw:
        return ""
    salt = (os.getenv("TRAFFIC_IP_SALT") or os.getenv("SESSION_SECRET") or "cartozo-traffic").encode()
    return hashlib.sha256(salt + raw.encode()).hexdigest()[:32]


def should_track_path(path: str, method: str) -> bool:
    """Log public HTML GET requests only."""
    if method.upper() != "GET":
        return False
    p = (path or "/").split("?", 1)[0]
    if not p.startswith("/"):
        p = "/" + p
    if p.startswith(("/static/", "/assets/", "/favicon")):
        return False
    seg0 = p.strip("/").split("/")[0].lower() if p.strip("/") else ""
    if seg0 in {
        "admin",
        "api",
        "auth",
        "batches",
        "docs",
        "merchant",
        "settings",
        "upload",
        "login",
        "logout",
    }:
        return False
    return True
