"""规则打分：平台内百分位归一化的 热度/速度 + 关键词相关 + 时效 → 0-100。"""
from collectors.common import PLATFORM_NAMES


def _percentile_ranks(values: list[float]) -> list[float]:
    """按相对位置给 0-100 分；全部相同值时给 50（如 PH 无互动数据）。"""
    n = len(values)
    if n == 1:
        return [50.0]
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    for pos, idx in enumerate(order):
        # 同值并列取相同名次
        if pos > 0 and values[order[pos]] == values[order[pos - 1]]:
            ranks[idx] = ranks[order[pos - 1]]
        else:
            ranks[idx] = 100.0 * pos / (n - 1)
    return ranks


def score(candidates: list[dict], cfg: dict) -> list[dict]:
    w = cfg["weights"]["rule"]
    window = cfg["window_hours"]
    by_platform = {}
    for r in candidates:
        by_platform.setdefault(r["platform"], []).append(r)

    for plat, items in by_platform.items():
        eng_scores = _percentile_ranks([r["engagement_total"] for r in items])
        velocities = []
        for r in items:
            h = r.get("_hours")
            velocities.append(r["engagement_total"] / h if h and h >= 1 else
                              (r["engagement_total"] if h is not None else 0.0))
        vel_scores = _percentile_ranks(velocities)
        for r, e_score, v_score in zip(items, eng_scores, vel_scores):
            r["s_engagement"] = round(e_score, 1)
            r["s_velocity"] = round(v_score, 1)
            # 关键词相关：命中数×20 + 标题命中加成，封顶100
            title_hits = len([k for k in r.get("keyword_hits", [])
                              if k.lower() in r["title"].lower()])
            rel = min(100.0, 20.0 * len(r.get("keyword_hits", [])) + 25.0 * min(title_hits, 2))
            r["s_relevance"] = round(rel, 1)
            h = r.get("_hours")
            r["s_recency"] = round(max(0.0, 100.0 * (1 - h / window)) if h is not None else 50.0, 1)
            r["rule_score"] = round(
                w["engagement"] * e_score + w["velocity"] * v_score
                + w["relevance"] * rel + w["recency"] * r["s_recency"], 1)

    for r in candidates:
        r["platform_name"] = PLATFORM_NAMES.get(r["platform"], r["platform"])
        r["hours_display"] = f"{r['_hours']:.0f}h" if r.get("_hours") is not None else "未知"
    return sorted(candidates, key=lambda r: r["rule_score"], reverse=True)


def apply_llm_and_rank(candidates: list[dict], llm_scores: dict, cfg: dict) -> list[dict]:
    """合并LLM打分（ai_relevance 0-10 / value 0-10 / why），算最终总分并排序。"""
    w = cfg["weights"]["final"]
    for r in candidates:
        ls = llm_scores.get(r["id"])
        if ls:
            r["llm_relevance"] = ls.get("ai_relevance")
            r["llm_value"] = ls.get("value")
            r["why"] = ls.get("why", "")
            r["final_score"] = round(
                w["engagement"] * r["s_engagement"] + w["velocity"] * r["s_velocity"]
                + w["llm_relevance"] * (ls.get("ai_relevance") or 0) * 10
                + w["llm_value"] * (ls.get("value") or 0) * 10, 1)
        else:
            r["llm_relevance"] = r["llm_value"] = None
            r["why"] = ""
            r["final_score"] = r["rule_score"]
        # 兜底文案：没有LLM"为什么火"时用数据说话
        if not r.get("why"):
            plat = r["platform_name"]
            if r["platform"] == "producthunt":
                r["why"] = f"Product Hunt 近期新品，主题命中AI热词（{', '.join(r.get('keyword_hits', [])[:3])}）"
            else:
                r["why"] = (f"发布 {r['hours_display']} 内互动 {r['engagement_summary']}，"
                            f"在{plat}同批内容中热度排名前{round(100 - r['s_engagement']) + 1}%")
    return sorted(candidates, key=lambda r: r["final_score"], reverse=True)
