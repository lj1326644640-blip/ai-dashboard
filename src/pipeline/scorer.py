"""规则打分：绝对基准分（对数曲线，跨天稳定可比）+ 关键词相关 + 时效，并打内容类型标签。"""
import math

from schema import PLATFORM_NAMES
from .classify import classify


def _logscore(value: float, ref: float) -> float:
    """对数基准分：value 达到 ref 即 100 分；低互动平滑衰减，不依赖当日样本。"""
    if value <= 0 or ref <= 0:
        return 0.0
    return min(100.0, 100.0 * math.log1p(value) / math.log1p(ref))


def score(candidates: list[dict], cfg: dict) -> list[dict]:
    w = cfg["weights"]["rule"]
    window = cfg["window_hours"]
    refs = cfg.get("scoring_refs", {})
    neutral = float(cfg.get("no_engagement_score", 25))
    no_data_platforms = {"producthunt"}  # feed 无互动数据，给固定中性分

    for r in candidates:
        plat = r["platform"]
        e = r["engagement_total"]
        h = r.get("_hours")
        if plat in no_data_platforms:
            s_eng = s_vel = neutral
        else:
            ref = refs.get(plat, {"engagement": 1000, "velocity": 60})
            s_eng = _logscore(e, ref["engagement"])
            s_vel = _logscore(e / h, ref["velocity"]) if h and h >= 1 else 30.0
        r["s_engagement"] = round(s_eng, 1)
        r["s_velocity"] = round(s_vel, 1)

        # 关键词相关：命中数×20 + 标题命中加成，封顶100
        title_hits = len([k for k in r.get("keyword_hits", [])
                          if k.lower() in r["title"].lower()])
        rel = min(100.0, 20.0 * len(r.get("keyword_hits", [])) + 25.0 * min(title_hits, 2))
        r["s_relevance"] = round(rel, 1)
        r["s_recency"] = round(max(0.0, 100.0 * (1 - h / window)) if h is not None else 50.0, 1)
        r["rule_score"] = round(
            w["engagement"] * s_eng + w["velocity"] * s_vel
            + w["relevance"] * rel + w["recency"] * r["s_recency"], 1)
        r["ctype"] = classify(r)

    for r in candidates:
        r["platform_name"] = PLATFORM_NAMES.get(r["platform"], r["platform"])
        r["hours_display"] = f"{r['_hours']:.0f}h" if r.get("_hours") is not None else "未知"
    return sorted(candidates, key=lambda r: r["rule_score"], reverse=True)


def apply_llm_and_rank(candidates: list[dict], llm_scores: dict, cfg: dict) -> list[dict]:
    """合并LLM打分（ai_relevance 0-10 / value 0-10 / why），算最终总分并排序。"""
    w = cfg["weights"]["final"]
    for r in candidates:
        if not r.get("ctype"):
            r["ctype"] = classify(r)  # collect阶段已打标的跳过；单独跑finalize时补打
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
                            f"达到{plat}基准线的{r['s_engagement']:.0f}%")
    return sorted(candidates, key=lambda r: r["final_score"], reverse=True)
