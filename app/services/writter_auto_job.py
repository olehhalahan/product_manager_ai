"""
Daily automatic SEO article runs: sequential generation + publish using the same Writer pipeline as manual flow.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import select

from ..db import get_db
from ..db_models import WritterAutoRun
from ..seo import site_base_url
from . import db_repository as repo
from .writter_service import (
    suggest_auto_article_brief,
    suggest_future_topics_keywords_only,
    score_article_opportunity,
    VALID_ARTICLE_TYPES,
)

_log = logging.getLogger("uvicorn.error")


def _parse_int(s: str, default: int) -> int:
    try:
        return int((str(s) or "").strip())
    except (TypeError, ValueError):
        return default


def _topic_tokens(s: str) -> Set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", (s or "").lower()) if len(w) > 2}


def _max_jaccard(candidate: str, corpus_lines: List[str]) -> float:
    tc = _topic_tokens(candidate)
    if not tc:
        return 0.0
    best = 0.0
    for line in corpus_lines:
        to = _topic_tokens(line)
        if not to:
            continue
        uni = len(tc | to)
        if not uni:
            continue
        j = len(tc & to) / uni
        if j > best:
            best = j
    return best


def infer_article_type(topic: str, keywords: str) -> str:
    blob = f"{topic} {keywords}".lower()
    if " vs " in blob or " versus " in blob or re.search(r"\bcompare\b", blob):
        return "comparison"
    if "checklist" in blob or "template" in blob:
        return "checklist_template"
    if re.search(r"\b(case study|use case|how .+ used)\b", blob):
        return "use_cases"
    if any(x in blob for x in ("how to", "fix", "error", "disapproved", "issue", "problem")):
        return "problem_solving"
    if any(x in blob for x in ("feature", "works", "dashboard", "workflow")):
        return "feature_presentation"
    return "informational"


def default_primary_goal_for_type(article_type: str) -> str:
    if article_type in ("problem_solving", "checklist_template"):
        return "qualified_traffic"
    if article_type in ("comparison", "feature_presentation"):
        return "signups_trials"
    if article_type == "use_cases":
        return "product_awareness"
    return "organic_traffic"


def _allowed_types(settings: Dict[str, str]) -> Optional[Set[str]]:
    raw = (settings.get("writter_auto_allowed_article_types") or "").strip()
    if not raw:
        return None
    parts = {x.strip() for x in raw.split(",") if x.strip()}
    return {x for x in parts if x in VALID_ARTICLE_TYPES}


def _local_date_str(tz_name: str) -> str:
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo((tz_name or "UTC").strip() or "UTC")
    except Exception:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("UTC")
    return datetime.now(tz).strftime("%Y-%m-%d")


def select_scored_brief(
    db: Any,
    *,
    min_score: int,
    session_corpus: List[str],
    session_primary_kw: Set[str],
    ideas_pool: List[Dict[str, str]],
    siblings_count: int,
    allowed: Optional[Set[str]],
) -> Optional[Dict[str, Any]]:
    candidates: List[Tuple[int, Dict[str, Any]]] = []
    for idea in ideas_pool:
        topic = (idea.get("topic") or "").strip()
        kw = (idea.get("keywords") or "").strip()
        if not topic:
            continue
        if repo.count_blog_articles_same_topic(db, topic) > 0:
            continue
        if repo.count_near_duplicate_titles(db, topic) > 0:
            continue
        parts = [x.strip().lower() for x in kw.split(",") if len(x.strip()) > 2]
        pk = parts[0] if parts else ""
        if pk and pk in session_primary_kw:
            continue
        j = _max_jaccard(topic, session_corpus)
        if j >= 0.58:
            continue
        at = infer_article_type(topic, kw)
        if allowed is not None and at not in allowed:
            continue
        pg = default_primary_goal_for_type(at)
        opp = score_article_opportunity(
            topic=topic,
            keywords=kw,
            article_type=at,
            internal_article_count=siblings_count,
            primary_goal=pg,
        )
        base = int(opp.get("estimated_value_score") or 0)
        pfit = int(opp.get("product_fit_likelihood") or 0)
        if pfit < 38:
            base -= 30
        if base < min_score:
            continue
        candidates.append(
            (
                base,
                {
                    "topic": topic[:500],
                    "keywords": kw[:2000],
                    "article_type": at,
                    "primary_goal": pg,
                    "fills_site_gap": (idea.get("fills_site_gap") or "")[:600],
                    "opportunity": opp,
                },
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1]


def run_writter_auto_daily(
    trigger: str = "cron",
    *,
    force_full_count: bool = False,
    override_count: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Run the daily auto pipeline. Commits after each article so failures do not roll back siblings.

    ``force_full_count``: when True (admin test), ignore today's published quota and process
    ``override_count`` or full daily_count in one run.
    """
    from ..writter_routes import (  # noqa: WPS23 — late import avoids circular dependency
        CreateArticleBody,
        EvidencePayload,
        MIN_QUALITY_AUTO_PUBLISH,
        RULE_PRESET_MESSAGES,
        _build_article_bundle,
        extended_creation_blocked_message,
        publish_blocked_by_quality,
    )

    log_items: List[Dict[str, Any]] = []
    run_id = uuid.uuid4().hex[:24]

    with get_db() as db:
        settings = repo.get_settings(db)
        repo.writter_auto_expire_stale_running(db, max_age_minutes=180)
        enabled = (settings.get("writter_auto_enabled") or "").strip() == "1"
        if trigger in ("cron", "scheduler") and not enabled:
            return {
                "ok": True,
                "skipped": "writter_auto_disabled",
                "run_id": run_id,
                "items": [],
            }

        tz = (settings.get("writter_auto_timezone") or "UTC").strip() or "UTC"
        local_date = _local_date_str(tz)
        daily_count = _parse_int(settings.get("writter_auto_daily_count"), 5)
        daily_count = max(1, min(15, daily_count))
        target_today = max(1, min(15, int(override_count))) if override_count is not None else daily_count

        if repo.writter_auto_has_running_job(db, max_age_minutes=120):
            return {
                "ok": False,
                "skipped": "concurrent_run",
                "run_id": run_id,
                "items": [],
            }

        already = repo.count_auto_daily_articles_on_local_date(db, tz_name=tz, local_date=local_date)
        if force_full_count:
            remaining = target_today
        else:
            remaining = max(0, target_today - already)

        if remaining <= 0:
            return {
                "ok": True,
                "skipped": "daily_quota_met",
                "run_id": run_id,
                "local_date": local_date,
                "already_today": already,
                "items": [],
            }

        api_key = (settings.get("openai_api_key") or "").strip()
        if not api_key:
            return {
                "ok": False,
                "error": "openai_api_key_missing",
                "run_id": run_id,
                "items": [],
            }

        min_topic = _parse_int(settings.get("writter_auto_min_topic_score"), 38)
        pause_s = _parse_int(settings.get("writter_auto_pause_seconds"), 18)
        pause_s = max(0, min(120, pause_s))
        max_retries = _parse_int(settings.get("writter_auto_max_retries"), 2)
        max_retries = max(0, min(5, max_retries))
        gen_mode = (settings.get("writter_auto_generation_mode") or "authority").strip().lower()
        if gen_mode not in ("fast", "standard", "authority"):
            gen_mode = "authority"
        publish_now = (settings.get("writter_auto_publish_immediately") or "1").strip() == "1"
        author_email = (settings.get("writter_auto_author_email") or "writter-auto@cartozo.ai").strip() or "writter-auto@cartozo.ai"
        allowed = _allowed_types(settings)

        run_row = repo.writter_auto_insert_run(
            db,
            run_id=run_id,
            trigger=trigger,
            timezone_str=tz,
            local_date=local_date,
            target_count=remaining,
        )
        # release lock visibility for other workers
        db.commit()

    success_n = 0
    fail_n = 0
    skip_n = 0
    site_base = site_base_url().rstrip("/")

    session_topics: List[str] = []
    session_primary_kw: Set[str] = set()
    loop_completed = False

    try:
        for slot in range(remaining):
            slot_label = slot + 1
            item_log: Dict[str, Any] = {
                "slot": slot_label,
                "status": "pending",
                "topic": "",
                "title": "",
                "error": "",
                "article_id": None,
                "url": "",
            }
            try:
                with get_db() as db:
                    ctx = repo.get_writter_site_context_for_llm(db)
                    existing = list(ctx["existing_topics"]) + session_topics
                    inv = ctx["site_inventory_lines"]
                    siblings = repo.get_published_slugs_titles_excluding(db, exclude_slug=None, limit=500)
                    icount = len(siblings)

                    ideas = suggest_future_topics_keywords_only(
                        api_key,
                        existing_topics=existing,
                        site_inventory_lines=inv,
                        count=15,
                    )
                    brief = select_scored_brief(
                        db,
                        min_score=min_topic,
                        session_corpus=existing + inv[:80],
                        session_primary_kw=session_primary_kw,
                        ideas_pool=ideas,
                        siblings_count=icount,
                        allowed=allowed,
                    )
                    if not brief:
                        fb = suggest_auto_article_brief(
                            api_key,
                            existing_topics=existing,
                            site_inventory_lines=inv,
                        )
                        at = (fb.get("article_type") or "informational").strip()
                        if allowed is not None and at not in allowed:
                            at = next(iter(allowed)) if allowed else "informational"
                        if at not in VALID_ARTICLE_TYPES:
                            at = "informational"
                        pg = (fb.get("primary_goal") or default_primary_goal_for_type(at)).strip()
                        brief = {
                            "topic": (fb.get("topic") or "").strip(),
                            "keywords": (fb.get("keywords") or "").strip(),
                            "article_type": at,
                            "primary_goal": pg,
                            "fills_site_gap": (fb.get("fills_site_gap") or "")[:600],
                        }
                        opp = score_article_opportunity(
                            topic=brief["topic"],
                            keywords=brief["keywords"],
                            article_type=brief["article_type"],
                            internal_article_count=icount,
                            primary_goal=brief["primary_goal"],
                        )
                        if int(opp.get("estimated_value_score") or 0) < min_topic:
                            item_log["status"] = "skipped"
                            item_log["error"] = "fallback_brief_below_min_topic_score"
                            skip_n += 1
                            continue

                    topic = brief["topic"]
                    keywords = brief["keywords"]
                    at = brief["article_type"]
                    pg = brief["primary_goal"]
                    item_log["topic"] = topic

                    spam = extended_creation_blocked_message(
                        same_topic_count=repo.count_blog_articles_same_topic(db, topic),
                        same_primary_keyword_count=repo.count_articles_sharing_primary_keyword(db, keywords),
                        author_24h_count=repo.count_articles_by_author_since(db, author_email, 24),
                        similar_title_pairs=repo.count_near_duplicate_titles(db, topic),
                    )
                    if spam:
                        item_log["status"] = "failed"
                        item_log["error"] = spam
                        fail_n += 1
                        _log.warning("writter_auto slot %s spam guard: %s", slot_label, spam)
                        continue

                    body = CreateArticleBody(
                        article_type=at,
                        topic=topic,
                        keywords=keywords,
                        primary_goal=pg,
                        audience="",
                        country_language="",
                        business_goal="",
                        generation_mode=gen_mode,
                        evidence=EvidencePayload(),
                        rules=[],
                        rule_presets=list(RULE_PRESET_MESSAGES.keys()),
                        visual_mode="auto",
                        visual_description="",
                        visual_index=0,
                        visual_seed=slot,
                        visual_layout="horizontal",
                        publish=False,
                        outline_sections=None,
                        article_plan_json=None,
                    )

                    extra = ""
                    last_bundle: Optional[Dict[str, Any]] = None
                    last_metrics: Optional[Dict[str, Any]] = None
                    for attempt in range(max_retries + 1):
                        bundle = _build_article_bundle(
                            db,
                            body,
                            author_email,
                            extra_user_instruction=extra,
                            visual_seed_effective=int(slot * 17 + attempt),
                        )
                        last_bundle = bundle
                        last_metrics = bundle["metrics"]
                        if publish_now:
                            blocked = publish_blocked_by_quality(last_metrics, min_overall=MIN_QUALITY_AUTO_PUBLISH)
                            ov = (last_metrics.get("seo_qa") or {}).get("scores", {}).get("overall")
                            if not blocked and isinstance(ov, int) and ov >= MIN_QUALITY_AUTO_PUBLISH:
                                break
                            extra = (
                                f"Previous SEO overall was {ov}. Improve depth, internal links, and concrete examples. "
                                f"Target at least {MIN_QUALITY_AUTO_PUBLISH} overall."
                            )
                        else:
                            break

                    assert last_bundle is not None and last_metrics is not None
                    payload = last_bundle["payload"]
                    planning = dict(last_bundle["planning_json"])
                    planning["writter_auto"] = {
                        "batch": "daily",
                        "run_id": run_id,
                        "slot": slot_label,
                        "fills_site_gap": brief.get("fills_site_gap") or "",
                        "trigger": trigger,
                    }

                    publish_ok = False
                    if publish_now:
                        blocked = publish_blocked_by_quality(last_metrics, min_overall=MIN_QUALITY_AUTO_PUBLISH)
                        ov = (last_metrics.get("seo_qa") or {}).get("scores", {}).get("overall")
                        publish_ok = (not blocked) and isinstance(ov, int) and ov >= MIN_QUALITY_AUTO_PUBLISH

                    final_title = (payload.get("seo_title") or topic)[:500]
                    item_log["title"] = final_title

                    row = repo.create_blog_article(
                        db,
                        slug=last_bundle["final_slug"],
                        title=final_title,
                        article_type=last_bundle["at"],
                        topic=topic,
                        keywords=keywords,
                        rules_json=last_bundle["rules_payload"],
                        content_html=last_bundle["full_html"],
                        meta_description=payload.get("meta_description") or "",
                        structure_json=payload.get("structure_outline"),
                        visual_html=last_bundle["v"].get("html"),
                        metrics_json=last_metrics,
                        planning_json=planning,
                        internal_links_json=last_bundle["used_links"],
                        status="published" if publish_ok else "draft",
                        author_email=author_email,
                        published_at=datetime.now(timezone.utc) if publish_ok else None,
                    )
                    db.flush()
                    aid = int(row.id)
                    try:
                        from ..services.blog_og_image import generate_blog_og_image_for_article_id

                        generate_blog_og_image_for_article_id(aid, force=False)
                    except Exception:
                        _log.exception("blog OG image after writter_auto failed article_id=%s", aid)
                    item_log["article_id"] = aid
                    slug_s = last_bundle["final_slug"]
                    item_log["url"] = f"{site_base}/blog/{slug_s}" if site_base else f"/blog/{slug_s}"

                    if publish_ok:
                        item_log["status"] = "published"
                        success_n += 1
                        session_topics.append(topic)
                        session_topics.append(final_title)
                        pkp = [x.strip().lower() for x in keywords.split(",") if len(x.strip()) > 2]
                        if pkp:
                            session_primary_kw.add(pkp[0])
                    else:
                        item_log["status"] = "draft_quality"
                        item_log["error"] = (
                            publish_blocked_by_quality(last_metrics, min_overall=MIN_QUALITY_AUTO_PUBLISH)
                            or "below_min_seo_overall"
                        )
                        fail_n += 1

            except Exception as e:
                _log.exception("writter_auto slot %s failed", slot_label)
                item_log["status"] = "failed"
                item_log["error"] = str(e)[:800]
                fail_n += 1

            log_items.append(item_log)
            if pause_s and slot + 1 < remaining:
                time.sleep(pause_s)
        loop_completed = True
    finally:
        if loop_completed:
            final_status = "completed" if fail_n == 0 else ("completed" if success_n > 0 else "failed")
        else:
            final_status = "failed"
        try:
            with get_db() as db:
                row2 = db.execute(select(WritterAutoRun).where(WritterAutoRun.run_id == run_id)).scalar_one_or_none()
                if row2:
                    repo.writter_auto_finish_run(
                        db,
                        row2,
                        status=final_status,
                        success_count=success_n,
                        failed_count=fail_n,
                        skipped_count=skip_n,
                        log_json=log_items,
                        error_message="" if loop_completed else "run interrupted before normal completion",
                    )
        except Exception:
            _log.exception("writter_auto could not finalize run row run_id=%s", run_id)

    return {
        "ok": True,
        "run_id": run_id,
        "local_date": local_date,
        "timezone": tz,
        "target_attempts": remaining,
        "success": success_n,
        "failed": fail_n,
        "skipped": skip_n,
        "status": final_status,
        "items": log_items,
    }
