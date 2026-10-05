"""Product Hunt 采集：官方 Atom feed（免key直连，无投票数，靠LLM分补偿）。"""
import re

import feedparser

from schema import dateutil_parse, hours_since, strip_html
from http_util import http_get
from settings import log

FEED = "https://www.producthunt.com/feed"
_POST_ID_RE = re.compile(r"Post/(\d+)")


def collect(cfg: dict) -> list[dict]:
    try:
        resp = http_get(FEED, timeout=25, retries=2)
    except Exception as e:  # noqa: BLE001
        log.error("Product Hunt feed 拉取失败: %s", e)
        return []
    feed = feedparser.parse(resp.text)
    records = []
    for e in feed.entries[:60]:
        pid_m = _POST_ID_RE.search(e.get("id", ""))
        content = strip_html(e.get("content", [{}])[0].get("value", "") if
                             isinstance(e.get("content"), list) and e.get("content")
                             else e.get("summary", ""))
        tagline = content[:200]
        published = None
        try:
            published = dateutil_parse(e.get("published", ""))
        except Exception:  # noqa: BLE001
            pass
        if published and (hours_since(published) is None or hours_since(published) > cfg["window_hours"]):
            continue
        records.append({
            "id": f"ph_{pid_m.group(1) if pid_m else abs(hash(e.get('id', e.title)))}",
            "platform": "producthunt",
            "title": e.get("title", "").strip(),
            "url": e.get("link", ""),
            "discussion": e.get("link", ""),
            "author": (e.get("author") or "").strip(),
            "published": published,
            "engagement": {},
            "text": tagline,
        })
    log.info("Product Hunt: feed 拿到 %d 条(窗口内)", len(records))
    return records
