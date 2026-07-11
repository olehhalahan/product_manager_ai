"""Robots.txt parsing and policy validation for tests and QA."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

# Crawlers that must reach public pages via the wildcard (*) group.
DISCOVERY_CRAWLER_AGENTS: tuple[str, ...] = (
    "Googlebot",
    "bingbot",
    "OAI-SearchBot",
    "ChatGPT-User",
    "Claude-SearchBot",
    "Claude-User",
    "PerplexityBot",
    "Perplexity-User",
    "CCBot",
)

# Model-training crawlers fully blocked site-wide.
TRAINING_CRAWLER_AGENTS: tuple[str, ...] = (
    "GPTBot",
    "ClaudeBot",
    "Google-Extended",
)


@dataclass
class RobotsGroup:
    user_agents: list[str] = field(default_factory=list)
    allow: list[str] = field(default_factory=list)
    disallow: list[str] = field(default_factory=list)


def parse_robots_txt(text: str) -> list[RobotsGroup]:
    """Parse robots.txt into agent groups (comments and blanks ignored)."""
    groups: list[RobotsGroup] = []
    current: RobotsGroup | None = None

    for raw_line in (text or "").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if current is None or current.user_agents:
                current = RobotsGroup()
                groups.append(current)
            current.user_agents.append(value)
        elif key == "allow" and current is not None:
            current.allow.append(value)
        elif key == "disallow" and current is not None:
            current.disallow.append(value)
        elif key == "sitemap":
            continue
    return [g for g in groups if g.user_agents]


def _agent_matches(group_agent: str, request_agent: str) -> bool:
    ga = group_agent.lower()
    ua = request_agent.lower()
    if ga == "*":
        return True
    return ga in ua


def _matching_groups(groups: list[RobotsGroup], user_agent: str) -> list[RobotsGroup]:
    matched = [g for g in groups if any(_agent_matches(ua, user_agent) for ua in g.user_agents)]
    if not matched:
        return []
    specific = [g for g in matched if not any(ua.strip() == "*" for ua in g.user_agents)]
    return specific if specific else matched


def _rule_specificity(path: str, rule: str) -> int:
    if not rule:
        return 0
    if rule == "/":
        return 1
    prefix = rule if rule.startswith("/") else f"/{rule}"
    if path.startswith(prefix):
        return len(prefix)
    return -1


def is_path_allowed_for_agent(text: str, user_agent: str, path: str) -> bool:
    """
    Return True when path is allowed for user_agent per robots group precedence.

    More-specific user-agent groups override the wildcard group. Within a group,
    the longest matching Allow/Disallow rule wins; Disallow wins ties.
    """
    groups = parse_robots_txt(text)
    if not groups:
        return True

    p = path if path.startswith("/") else f"/{path}"
    applicable = _matching_groups(groups, user_agent)
    if not applicable:
        return True

    best_allow = -1
    best_disallow = -1
    for group in applicable:
        for rule in group.allow:
            spec = _rule_specificity(p, rule)
            if spec >= 0:
                best_allow = max(best_allow, spec)
        for rule in group.disallow:
            spec = _rule_specificity(p, rule)
            if spec >= 0:
                best_disallow = max(best_disallow, spec)

    if best_disallow < 0 and best_allow < 0:
        return True
    if best_disallow > best_allow:
        return False
    if best_allow > best_disallow:
        return True
    return best_disallow <= 0


def validate_robots_policy(
    text: str,
    *,
    sitemap_url: str,
    private_prefixes: Iterable[str],
) -> list[str]:
    """Return human-readable policy violations (empty list means pass)."""
    errors: list[str] = []
    body = text or ""

    if f"Sitemap: {sitemap_url}" not in body:
        errors.append(f"missing Sitemap: {sitemap_url}")

    if "User-agent: *" not in body:
        errors.append("missing wildcard User-agent: * group")

    groups = parse_robots_txt(body)
    wildcard = next((g for g in groups if "*" in g.user_agents), None)
    if wildcard is None:
        errors.append("wildcard group not parsed")
    else:
        if "/" not in wildcard.allow and not any(a.strip() == "/" for a in wildcard.allow):
            errors.append("wildcard group must Allow: /")
        missing_private = [
            pref
            for pref in private_prefixes
            if not any(d.rstrip("/") == pref.rstrip("/") or d == pref for d in wildcard.disallow)
        ]
        if missing_private:
            errors.append(f"wildcard group missing Disallow rules: {missing_private}")

    for agent in TRAINING_CRAWLER_AGENTS:
        if f"User-agent: {agent}" not in body:
            errors.append(f"missing training crawler group: {agent}")
        if is_path_allowed_for_agent(body, agent, "/pricing"):
            errors.append(f"{agent} must be fully disallowed (Disallow: /)")
        if is_path_allowed_for_agent(body, agent, "/"):
            errors.append(f"{agent} must be fully disallowed (Disallow: /)")

    for agent in DISCOVERY_CRAWLER_AGENTS:
        if not is_path_allowed_for_agent(body, agent, "/pricing"):
            errors.append(f"{agent} cannot fetch public /pricing")
        if is_path_allowed_for_agent(body, agent, "/admin"):
            errors.append(f"{agent} must not bypass private /admin restriction")
        if is_path_allowed_for_agent(body, agent, "/upload"):
            errors.append(f"{agent} must not bypass private /upload restriction")

    # Explicit Allow:/-only groups must not exist without private Disallow repeats.
    for group in groups:
        if any(ua.strip() == "*" for ua in group.user_agents):
            continue
        if group.allow and not group.disallow:
            agents = ", ".join(group.user_agents)
            if any(a.strip() == "/" for a in group.allow):
                errors.append(
                    f"explicit group {agents!r} has Allow:/ without repeating private Disallow rules"
                )

    # Duplicate contradictory wildcard groups
    wildcard_groups = [g for g in groups if "*" in g.user_agents]
    if len(wildcard_groups) > 1:
        errors.append("multiple wildcard User-agent: * groups")

    return errors


def extract_sitemap_url(text: str) -> str | None:
    for raw_line in (text or "").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if line.lower().startswith("sitemap:"):
            return line.split(":", 1)[1].strip()
    return None
