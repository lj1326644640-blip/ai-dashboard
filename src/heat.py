"""长期记忆与话题热度。

a. 长期记忆：把 data/日期/full.json（历史+当天原始数据）聚合成一张数据表
   data/longterm_memory.jsonl（每行=一条内容：日期/平台/标题/链接/分数/类型/话题），每次 finalize 全量重建（幂等、自愈）。
b. 热度表：data/topic_heat.json，按话题记录 每日条数/均分/最高分/首次出现日期。
c. 升温判定（对最新一天）：
   - 规则A：今日条数 或 今日均分 ≥ 过去7天均值的2倍，且今日条数≥3
   - 规则B：话题首次出现当天就有内容进入 Top10
   判定为「升温」的话题返回给报告/看板/Excel 标记。
"""
import json
import statistics
from datetime import date, datetime, timedelta

from pipeline.topics import extract_topics
from settings import log, topic_data_dir


def build_memory(cfg: dict) -> list[dict]:
    """扫描本主题全部按日归档，聚合成一张长期记忆表（全量重建，幂等）。"""
    lexicon = cfg.get("topic_lexicon", {})
    tdir = topic_data_dir(cfg)
    memory_path = tdir / "longterm_memory.jsonl"
    rows = []
    for full in sorted(tdir.glob("*/full.json")):
        day = full.parent.name
        if len(day) != 10:
            continue
        try:
            items = json.loads(full.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for it in items:
            rows.append({
                "date": day,
                "id": it.get("id"),
                "platform": it.get("platform"),
                "title": it.get("title", "")[:120],
                "url": it.get("url", ""),
                "score": it.get("final_score"),
                "ctype": it.get("ctype", ""),
                "engagement": it.get("engagement_summary", ""),
                "topics": extract_topics(it, lexicon),
            })
    tdir.mkdir(parents=True, exist_ok=True)
    with open(memory_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    log.info("长期记忆表: %d 行 ← %d 天归档", len(rows), len({r['date'] for r in rows}))
    return rows


def compute_heat(rows: list[dict], today: str, top10_topics: set[str]) -> dict:
    """由记忆表计算每个话题的每日热度与升温状态（纯函数，便于单测）。"""
    by_topic: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        for t in r.get("topics") or []:
            score = r.get("score") or 0
            by_topic.setdefault(t, {}).setdefault(r["date"], []).append(score)

    today_d = date.fromisoformat(today)
    past7 = [(today_d - timedelta(days=i)).isoformat() for i in range(1, 8)]

    heat = {}
    for topic, daily in by_topic.items():
        first_seen = min(daily)
        t_scores = daily.get(today, [])
        t_count, t_avg, t_max = len(t_scores), 0.0, 0.0
        if t_scores:
            t_avg = round(statistics.mean(t_scores), 1)
            t_max = round(max(t_scores), 1)
        c7 = [len(daily.get(d, [])) for d in past7]
        avg7_count = sum(c7) / 7
        past_day_avgs = [statistics.mean(daily[d]) for d in past7 if daily.get(d)]
        avg7_score = round(statistics.mean(past_day_avgs), 1) if past_day_avgs else None

        status, reason = "-", ""
        if first_seen == today:
            if topic in top10_topics:
                status, reason = "升温", "首次出现当天即进Top10"
            else:
                status, reason = "新话题", "今日首次出现"
        elif t_count >= 3:
            count_hit = avg7_count == 0 or t_count >= 2 * avg7_count
            score_hit = avg7_score is not None and t_avg >= 2 * avg7_score
            if count_hit or score_hit:
                status = "升温"
                parts = []
                if count_hit:
                    parts.append(f"今日{t_count}条 vs 近7天均值{avg7_count:.1f}条"
                                 f"（{t_count / avg7_count:.1f}×）" if avg7_count > 0
                                 else f"近7天0条，今日{t_count}条集中爆发")
                if score_hit:
                    parts.append(f"今日均分{t_avg} vs 基线{avg7_score}（{t_avg / avg7_score:.1f}×）")
                reason = "；".join(parts)

        heat[topic] = {
            "first_seen": first_seen,
            "today": {"count": t_count, "avg": t_avg, "max": t_max},
            "last7_avg_count": round(avg7_count, 2),
            "last7_avg_score": avg7_score,
            "daily": {d: {"count": len(s), "avg": round(statistics.mean(s), 1) if s else 0,
                          "max": round(max(s), 1) if s else 0} for d, s in sorted(daily.items())},
            "status": status,
            "reason": reason,
        }
    return heat


def update(cfg: dict, top10_items: list[dict]) -> list[dict]:
    """finalize 调用：重建记忆表 → 更新热度表 → 返回升温领域列表（给报告/看板标记）。"""
    lexicon = cfg.get("topic_lexicon", {})
    tdir = topic_data_dir(cfg)
    rows = build_memory(cfg)
    if not rows:
        return []
    today = max(r["date"] for r in rows)
    top10_topics = set()
    for r in top10_items:
        top10_topics.update(extract_topics(r, lexicon))

    heat = compute_heat(rows, today, top10_topics)
    (tdir / "topic_heat.json").write_text(
        json.dumps({"updated_at": datetime.utcnow().isoformat() + "Z",
                    "today": today, "topics": heat},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    hot = []
    for topic, h in heat.items():
        if h["status"] == "升温":
            sample = max((r for r in rows if r["date"] == today and topic in (r.get("topics") or [])),
                         key=lambda r: r.get("score") or 0, default=None)
            hot.append({
                "topic": topic,
                "today_count": h["today"]["count"],
                "today_avg": h["today"]["avg"],
                "today_max": h["today"]["max"],
                "last7_avg_count": h["last7_avg_count"],
                "reason": h["reason"],
                "sample_title": (sample or {}).get("title", ""),
                "sample_url": (sample or {}).get("url", ""),
            })
    hot.sort(key=lambda h: (-h["today_count"], -h["today_avg"]))
    hot = hot[:8]
    log.info("升温领域 %d 个: %s", len(hot), [h["topic"] for h in hot])
    return hot


def load(cfg: dict) -> dict:
    """读取本主题热度表（供 status/外部查询）。"""
    p = topic_data_dir(cfg) / "topic_heat.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
