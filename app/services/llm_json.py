"""Best-effort JSON object extraction from LLM output (fences, trailing prose)."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional


def parse_json_object_from_text(raw: str) -> Optional[Dict[str, Any]]:
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```\s*$", "", s)
        s = s.strip()
    try:
        data = json.loads(s)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end <= start:
        return None
    chunk = s[start : end + 1]
    try:
        data = json.loads(chunk)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None
