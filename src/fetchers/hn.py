"""Hacker News 采集：Algolia API 为主（结构化 points/评论数），hnrss.org RSS 兜底。"""
import re
from datetime import timedelta

import feedparser

from schema import dateutil_parse, hours_since, now_utc, to_iso_utc
from http_util import http_get
from settings import log

ALGOLIA = "https://hn.algolia.com/api/v1/search"


def collect(cfg: dict) -> list[dict]:
    if not cfg.get("platforms", {}).get("hn", False):
        return []
    queries = cfg.get("queries", {}).get("hn", [])
    try:
        records = _collect_algolia(cfg, queries)
        if records:
            log.info("HN: Algolia 拿到 %d 条", len(records))
            return records
        raise RuntimeError("Algolia 返回 0 条")
    except Exception as e:  # noqa: BLE001
        log.warning("HN Algolia 失败(%s)，降级 hnrss.org", e)
        try:
            records = _collect_hnrss(cfg, queries)
            log.info("HN: hnrss 兜底拿到 %d 条", len(records))
            return records
        except Exception as e2:  # noqa: BLE001
            log.error("HN hnrss 也失败: %s", e2)
            return []


def _collect_algolia(cfg: dict, queries: list[str]) -> list[dict]:
    min_ts = int((now_utc() - timedelta(hours=cfg["window_hours"])).timestamp())
    seen: dict[str, dict] = {}

    hits = http_get(ALGOLIA, params={"tags": "front_page", "hitsPerPage": 60},
                    timeout=20).json().get("hits", [])
    for h in hits:
        seen[h["objectID"]] = h

    for q in cfg["queries"].get("hn", []):
        hits = http_get(ALGOLIA, params={
            "query": q, "tags": "story", "hitsPerPage": 50,
            "numericFilters": f"created_at_i>{min_ts},points>20",
        }, timeout=20).json().get("hits", [])
        for h in hits:
            seen[h["objectID"]] = h

    records = []
    for oid, h in seen.items():
        published = to_iso_utc(h.get("created_at"))
        if hours_since(published) is None or hours_since(published) > cfg["window_hours"]:
            continue
        records.append({
            "id": f"hn_{oid}",
            "platform": "hn",
            "title": h.get("title") or h.get("story_title") or "",
            "url": h.get("url") or f"https://news.ycombinator.com/item?id={oid}",
            "discussion": f"https://news.ycombinator.com/item?id={oid}",
            "author": h.get("author", ""),
            "published": published,
            "engagement": {"points": h.get("points") or 0,
                           "comments": h.get("num_comments") or 0},
            "text": (h.get("story_text") or "")[:400],
        })
    return records


_POINTS_RE = re.compile(r"Points:\s*(\d+)")
_COMMENTS_RE = re.compile(r"#\s*Comments:\s*(\d+)")


def _collect_hnrss(cfg: dict, queries: list[str]) -> list[dict]:
    """hnrss 慢且偶发502：长超时+多次重试；points/评论数埋在description文本里。"""
    records = []
    seen_ids = set()
    for q in queries[:4]:  # 兜底少抓几个词，控制耗时
        url = f"https://hnrss.org/newest?q={q.replace(' ', '+')}&points=20"
        try:
            feed = feedparser.parse(http_get(url, timeout=30, retries=2).text)
        except Exception as e:  # noqa: BLE001
            log.warning("hnrss '%s' 拉取失败: %s", q, e)
            continue
        for e in feed.entries:
            oid_m = re.search(r"id=(\d+)", e.get("id", ""))
            if not oid_m or oid_m.group(1) in seen_ids:
                continue
            oid = oid_m.group(1)
            seen_ids.add(oid)
            desc = e.get("description", "")
            published = None
            try:
                published = dateutil_parse(e.get("published", ""))
            except Exception:  # noqa: BLE001
                published = to_iso_utc(e.get("published_parsed") and e.published_parsed[0])
            records.append({
                "id": f"hn_{oid}",
                "platform": "hn",
                "title": e.get("title", ""),
                "url": e.get("link") or f"https://news.ycombinator.com/item?id={oid}",
                "discussion": f"https://news.ycombinator.com/item?id={oid}",
                "author": (e.get("dc_creator") or e.get("author") or ""),
                "published": published,
                "engagement": {
                    "points": int(_POINTS_RE.search(desc).group(1)) if _POINTS_RE.search(desc) else 0,
                    "comments": int(_COMMENTS_RE.search(desc).group(1)) if _COMMENTS_RE.search(desc) else 0,
                },
                "text": "",
            })
    return records
