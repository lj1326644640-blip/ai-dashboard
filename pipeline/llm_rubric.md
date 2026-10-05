# LLM 打分规则（Rubric）

对采集管线产出的候选内容做人工级判断打分。输入为 `data/candidates_YYYY-MM-DD.json`，
输出写到 `data/llm_scores_YYYY-MM-DD.json`（或 `data/llm_scores/` 目录下的分批文件，final 阶段自动合并）。

## 输入格式
每条候选包含字段：`id`、`platform`（hn/producthunt/reddit/twitter/tiktok/youtube）、
`title`、`text`（正文/描述前400字）、`engagement_summary`、`engagement`（互动原始数据）、
`s_engagement`/`s_velocity`（规则分已算好，供参考，不需要重复计算热度）。

## 输出格式（严格遵守）
单个 JSON 数组，每条：

```json
[
  {
    "id": "hn_39812345",
    "ai_relevance": 9,
    "value": 8,
    "why": "OpenAI 发布新模型 API 降价一半，开发者社区激烈讨论成本影响，转发引用率高"
  }
]
```

字段定义（必须全部填写）：

- **ai_relevance**（0-10，整数）：与 AI 主题的相关程度
  - 9-10：核心 AI 话题（模型发布/Agent框架/开源权重/AI基础设施/AI监管等）
  - 6-8：明显相关（AI应用案例、AI创业、大厂AI动向、教程）
  - 3-5：沾边（泛科技新闻里提到AI、用了AI但主题是别的）
  - 0-2：无关内容（关键词误命中的噪音）

- **value**（0-10，整数）：内容价值/爆款潜质（与相关性独立）
  - 高分信号：争议性强、数据惊人、教程可复刻、独家首发、情绪共鸣强（"wow moment"）
  - 低分信号：纯广告、标题党无干货、过期消息、重复刷屏

- **why**（一句话，中文，25-60字）：为什么火/值得看，写具体事实，不写空话。
  好例子："开源权重直接对标 Claude Sonnet，跑分截图引爆 HN，评论区争议跑分方法"
  坏例子："内容很有价值，值得关注"

## 打分操作要求
1. 每批建议 15-25 条，逐条打分，不要批量给同一分数
2. 互动数据（`engagement`）只作为热度参考，**不要**因为它高就放水 `ai_relevance`
3. 不确定相关性的按保守打分（宁低勿高），0-2 分的要在 why 里注明"疑似噪音"
4. 全部打完后把数组写入输出文件（UTF-8，无 BOM）
