# -*- coding: utf-8 -*-
"""验收测试：字段完整性 / 数据准确性 / 看板HTML质量（测试4定时任务单独查）。"""
import json
import re

import openpyxl

print("====== 测试1复检: 统一字段 ======")
REQUIRED = ["id", "platform", "platform_name", "title", "url", "author", "published",
            "engagement", "engagement_total", "engagement_summary", "fingerprint",
            "keyword_hits", "s_engagement", "s_velocity", "s_relevance", "s_recency",
            "rule_score", "hours_display", "final_score", "why", "llm_relevance", "llm_value"]
cand = json.loads(open("data/candidates_2026-10-05.json", encoding="utf-8").read())
missing = {r["id"]: [k for k in REQUIRED if k not in r or r[k] is None] for r in cand}
missing = {k: v for k, v in missing.items() if v}
print(f"候选 {len(cand)} 条 × {len(REQUIRED)} 个统一字段 | 缺失记录: {len(missing)}",
      "✅" if not missing else list(missing.items())[:3])

print()
print("====== 测试3a: 数据准确性抽查(源头→候选→看板三层一致) ======")
meta = json.loads(open("reports/2026-10-05/meta.json", encoding="utf-8").read())
top1 = meta["items"][0]
src = next(r for r in cand if r["id"] == top1["id"])
print(f"Top1: {top1['title'][:45]}")
print(f"  候选 engagement : {src['engagement_summary']}")
print(f"  看板 engagement : {top1['engagement_summary']}")
print(f"  一致: {'✅' if src['engagement_summary'] == top1['engagement_summary'] else '❌'}")
print(f"  分数: 候选 final_score={src['final_score']} meta={top1['final_score']}",
      "✅" if src["final_score"] == top1["final_score"] else "❌")

html = open("reports/dashboard.html", encoding="utf-8").read()
print()
print("====== 测试3b: 看板HTML质量扫描 ======")
bad = [w for w in ["None", "nan", "undefined", "null"]
       if re.search(r">(\s*)" + w + r"(\s*)<", html)]
print(f"占位符/未定义值残留: {len(bad)}", "✅" if not bad else bad)
cards = len(re.findall(r"<article class=\"item\">", html))
links = html.count('target="_blank"')
why_n = len(re.findall(r"class=\"why\"", html))
tabs = len(re.findall('name="day"', html))
print(f"卡片数: {cards} (应=20) | 外链: {links} (应≥20) | why文案: {why_n} (应=20)")
print(f"Top1标题在页面: {'✅' if 'Run Qwen 3.8 Flash Next' in html else '❌'}")
print(f"why文案示例在页面: {'✅' if '自称RTX 4090跑Qwen' in html else '❌'}")
print(f"日期切换tab数: {tabs} (历史天数)")

print()
print("====== 测试3c: 线上页面与本地一致性 ======")
import urllib.request
req = urllib.request.Request(
    "https://lj1326644640-blip.github.io/ai-dashboard/",
    headers={"User-Agent": "Mozilla/5.0"})
live = urllib.request.urlopen(req, timeout=20).read().decode("utf-8")
checks = ["AI 爆款看板", "Run Qwen 3.8 Flash Next", "class=\"why\"", "2026-10-05"]
for c in checks:
    print(f"  线上含 '{c}':", "✅" if c in live else "❌")
same = ("Run Qwen 3.8 Flash Next" in live) and ('class="why"' in live)
print(f"线上=本地数据版本: {'✅' if same else '❌ (需重新publish)'}")
