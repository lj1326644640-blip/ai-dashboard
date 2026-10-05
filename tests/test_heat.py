# -*- coding: utf-8 -*-
"""升温判定规则单测（纯函数 compute_heat，不依赖真实数据）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from heat import compute_heat  # noqa: E402

TODAY = "2026-10-06"


def rows_for(topic_counts: dict):
    """topic_counts: {date: count} → 构造记忆行，分数固定70。"""
    rows = []
    for d, n in topic_counts.items():
        for i in range(n):
            rows.append({"date": d, "id": f"{d}_{i}", "platform": "hn",
                         "title": f"item {i}", "url": f"https://x/{d}{i}",
                         "score": 70, "ctype": "资讯",
                         "topics": ["测试话题"]})
    return rows


def build(days_counts: dict):
    """days_counts: {date: count}，含今天。"""
    return rows_for(days_counts)


def status_of(days_counts):
    rows = build(days_counts)
    heat = compute_heat(rows, TODAY, set())
    return heat["测试话题"]["status"], heat["测试话题"]["reason"]


def test_steady_not_heating():
    # 近7天每天3条（均值3），今天4条：4 < 6 → 不升温
    counts = {f"2026-09-2{9 - i}" if False else (f"2026-10-{i:02d}"): 3
              for i in range(1, 7)}
    counts["2026-09-29"] = 3
    counts[TODAY] = 4
    s, r = status_of(counts)
    assert s == "-", f"稳态不应升温: {s} {r}"


def test_count_spike():
    # 近7天=09-29..10-05：6天各1条+09-30空=均值0.86；今天4条（≥3 且 ≥2×）→ 升温
    counts = {"2026-09-29": 1}
    counts.update({f"2026-10-{d:02d}": 1 for d in range(1, 6)})
    counts[TODAY] = 4
    s, r = status_of(counts)
    assert s == "升温" and "4.7×" in r, f"{s} {r}"


def test_comeback_zero_baseline():
    # 近7天0条（历史上有出现），今天3条 → 升温
    counts = {"2026-09-20": 5, "2026-09-21": 2}
    counts.update({f"2026-10-{d:02d}": 0 for d in range(1, 7)})  # 无记录=0
    counts[TODAY] = 3
    s, r = status_of(counts)
    assert s == "升温" and "集中爆发" in r, f"{s} {r}"


def test_avg_score_spike():
    # 条数没涨（近7天均值2.7，今天3条 < 5.4）但均分翻倍：基线30 → 今日80 → 升温
    rows = []
    rows += [{"date": "2026-09-29", "id": "c1", "platform": "hn", "title": "t",
              "url": "w", "score": 30, "ctype": "资讯", "topics": ["测试话题"]}]
    for i in range(1, 6):  # 10-01..10-05 各3条，分数30
        d = f"2026-10-{i:02d}"
        rows += [{"date": d, "id": f"a{i}_{j}", "platform": "hn", "title": "t",
                  "url": f"u{i}{j}", "score": 30, "ctype": "资讯", "topics": ["测试话题"]}
                 for j in range(3)]
    rows += [{"date": TODAY, "id": f"b{j}", "platform": "hn", "title": "t",
              "url": f"v{j}", "score": 80, "ctype": "资讯", "topics": ["测试话题"]}
             for j in range(3)]
    rows += [{"date": "2026-09-29", "id": "c1", "platform": "hn", "title": "t",
              "url": "w", "score": 30, "ctype": "资讯", "topics": ["测试话题"]}]
    heat = compute_heat(rows, TODAY, set())
    h = heat["测试话题"]
    assert h["status"] == "升温" and "均分" in h["reason"], f"{h['status']} {h['reason']}"


def test_first_seen_top10():
    rows = build({TODAY: 5})
    heat = compute_heat(rows, TODAY, {"测试话题"})
    assert heat["测试话题"]["status"] == "升温"
    assert "Top10" in heat["测试话题"]["reason"]


def test_first_seen_not_top10():
    rows = build({TODAY: 5})
    heat = compute_heat(rows, TODAY, set())
    assert heat["测试话题"]["status"] == "新话题"


def test_low_volume_not_heating():
    # 近7天均值0.43（3天各1条），今天2条（<3条门槛）→ 不升温
    counts = {"2026-09-29": 1, "2026-10-02": 1, "2026-10-04": 1, TODAY: 2}
    s, r = status_of(counts)
    assert s == "-", f"{s} {r}"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(fns)} 项升温判定规则全部通过")
