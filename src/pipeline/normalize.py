"""硬过滤：跨天去重 → 时间窗 → AI关键词 → 跨平台同题合并 → 平台内TopK。"""
import re
from datetime import datetime, timezone

from collectors.common import hours_since, title_similarity

# AI 短词用词边界匹配，避免 "AI" 命中 "said" 之类；长词用子串
_WORD_RE = {}


def keyword_hits(text: str, keywords: list[str]) -> list[str]:
    if not text:
        return []
    low = text.lower()
    hits = []
    for kw in keywords:
        if len(kw) <= 3:
            pat = _WORD_RE.setdefault(kw.lower(), re.compile(rf"\b{re.escape(kw.lower())}\b"))
            if pat.search(low):
                hits.append(kw)
        elif kw.lower() in low:
            hits.append(kw)
    return hits


def load_history(path) -> set[str]:
    seen = set()
    if not path.exists():
        return seen
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    seen.add(json_fp(line))
                except Exception:  # noqa: BLE001
                    continue
    return seen


def json_fp(line: str) -> str:
    import json
    return json.loads(line)["fingerprint"]


def apply(records: list[dict], cfg: dict, history_fp: set[str],
          prior_fps: set[str] | None = None) -> tuple[list[dict], dict]:
    """返回 (过滤后候选, 统计)。每平台按 engagement_total 取 TopK。

    prior_fps：今日已有候选的指纹（当天重复运行 collect 时不作为重复剔除）。
    """
    prior_fps = prior_fps or set()
    stats = {"input": len(records), "dup_history": 0, "dup_run": 0, "out_window": 0,
             "no_keyword": 0, "dup_title": 0, "kept": 0}
    keywords = cfg["keywords"]
    window = cfg["window_hours"]
    k_per_platform = cfg["candidates_per_platform"]

    # 1) 跨天去重（今日已入库的除外）
    stage = []
    seen_run = set()
    for r in records:
        fp = r["fingerprint"]
        if fp in prior_fps:
            stage.append(r)
            continue
        if fp in history_fp:
            stats["dup_history"] += 1
            continue
        if fp in seen_run:
            stats["dup_run"] += 1
            continue
        seen_run.add(fp)
        stage.append(r)

    # 2) 时间窗（无发布时间的记录放行，如YouTube搜索兜底数据）
    stage2 = []
    for r in stage:
        h = hours_since(r.get("published"))
        if h is not None and h > window:
            stats["out_window"] += 1
            continue
        r["_hours"] = h
        stage2.append(r)

    # 3) AI关键词（标题+正文+平台名）
    stage3 = []
    for r in stage2:
        hits = keyword_hits(f"{r['title']} {r.get('text', '')}", keywords)
        if not hits:
            stats["no_keyword"] += 1
            continue
        r["keyword_hits"] = hits
        stage3.append(r)

    # 4) 跨平台同题合并（保留互动更高的那条，标记同题）
    stage3.sort(key=lambda r: r["engagement_total"], reverse=True)
    kept = []
    for r in stage3:
        dup = None
        for k in kept:
            if title_similarity(r["title"], k["title"]) >= 0.8:
                dup = k
                break
        if dup:
            stats["dup_title"] += 1
            dup.setdefault("same_story_platforms", [])
            if r["platform"] not in dup["same_story_platforms"] and r["platform"] != dup["platform"]:
                dup["same_story_platforms"].append(r["platform"])
            continue
        kept.append(r)

    # 5) 平台内TopK
    by_platform = {}
    for r in kept:
        by_platform.setdefault(r["platform"], []).append(r)
    final = []
    for plat, items in by_platform.items():
        items.sort(key=lambda r: r["engagement_total"], reverse=True)
        final.extend(items[:k_per_platform])
    stats["kept"] = len(final)
    return final, stats


def update_history(path, kept: list[dict], known_fps: set[str] | None = None):
    """把本轮新增指纹追加进库（已在库/今日已有的不重复写）。"""
    import json
    known_fps = known_fps or set()
    path.parent.mkdir(exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in kept:
            if r["fingerprint"] in known_fps:
                continue
            known_fps.add(r["fingerprint"])
            f.write(json.dumps({
                "fingerprint": r["fingerprint"],
                "platform": r["platform"],
                "id": r["id"],
                "title": r["title"][:120],
                "url": r["url"],
                "first_seen": datetime.now(timezone.utc).isoformat(),
            }, ensure_ascii=False) + "\n")
