"""内容类型分类器：工具 / 资讯 / 观点 / 争议。

中英文文本特征 + 来源域名特征 + 互动形状特征（回赞比/评论比）加权投票，取最高分类。
规则可解释、可扩展；每条候选在规则打分阶段打上 ctype 标签。
"""
import re

# 各类特征词（小写；命中标题权重2，正文权重1）
FEATURES = {
    "工具": [
        "show hn", "show hn:", "launch", "launched", "open-source", "open source",
        "released", "release", "beta", "v1.", "v2.", "try ", "install", "github",
        "framework", "sdk", "boilerplate", "template", "extension", "plugin",
        "self-host", "cli", "repo", "star ", "app ", "tool", "toolkit", "library",
        "如何用", "怎么用", "开源", "发布", "上线", "工具", "框架", "插件", "部署",
        "跑通", "实测", "教程", "搭建", "白嫖", "开源了", "免费使用", "一键",
    ],
    "资讯": [
        "report", "reported", "announc", "raises", "raised", "funding", "acquir",
        "according", "said", "update", "launches", "debut", "unveil", "rolls out",
        "reportedly", "sources say", "bloomberg", "reuters", "techcrunch", "the verge",
        "wired", "bbc", "nytimes", "fortune", "cnbc",
        "融资", "收购", "宣布", "据报道", "消息称", "发布会", "上线了", "推出了", "报道称",
    ],
    "观点": [
        "i think", "my take", "hot take", "essay", "opinion", "thoughts on", "why i",
        "we need", "i quit", "i'm worried", "makes me", "i feel", "reflection",
        "future of", "believe", "反思", "观点", "我认为", "怎么看", "思考", "随笔",
        "感想", "担忧", "本质", "未来", "我为什么", "论 ",
    ],
    "争议": [
        "ban", "banned", "backlash", "fired", "firing", "lawsuit", "sued", "safety",
        "warning", "quit", "resign", "controversy", "accused", "scandal", "protest",
        "criticism", "slam", "slammed", "outrage", "fight", "war ", "against",
        "封禁", "离职", "辞职", "诉讼", "起诉", "警告", "争议", "反击", "怒斥", "痛批",
        "叫停", "禁止", "引众怒", "吵翻", "开撕", "回应质疑", "陷入",
    ],
}
COMPILED = {k: [re.compile(re.escape(w.lower())) for w in v] for k, v in FEATURES.items()}

NEWS_DOMAINS = ("techcrunch.com", "theverge.com", "bbc.co", "bbc.com", "nytimes.com",
                "reuters.com", "bloomberg.com", "wired.com", "fortune.com", "cnbc.com",
                "arstechnica.com", "theguardian.com", "telegraph.co", "404media.co",
                "venturebeat.com", "cnbetacdn", "36kr.com")
TOOL_DOMAINS = ("github.com", "npmjs.com", "pypi.org", "huggingface.co")


def _hits(text: str, pats: list) -> int:
    low = text.lower()
    return sum(1 for p in pats if p.search(low))


def classify(rec: dict) -> str:
    title = rec.get("title", "") or ""
    body = rec.get("text", "") or ""
    url = (rec.get("url") or "").lower()
    plat = rec.get("platform")
    eng = rec.get("engagement") or {}

    scores = {k: 2.0 * _hits(title, p) + 1.0 * _hits(body, p) for k, p in COMPILED.items()}

    # 域名特征
    if any(d in url for d in TOOL_DOMAINS):
        scores["工具"] += 3.0
    if any(d in url for d in NEWS_DOMAINS):
        scores["资讯"] += 3.0

    # 互动形状：评论相对赞越高，越像讨论/争议；Reddit 的 comment/upvote 同理
    likes = float(eng.get("likes") or eng.get("upvotes") or 0)
    replies = float(eng.get("replies") or eng.get("comments") or 0)
    if likes >= 20 and replies:
        ratio = replies / (likes + 1)
        if ratio >= 0.8:
            scores["争议"] += 3.0
        elif ratio >= 0.4:
            scores["争议"] += 1.5
            scores["观点"] += 1.0
        elif ratio <= 0.1:
            scores["工具"] += 1.0  # 高赞低讨论 ≈ 资源/工具型传播

    # TikTok/YouTube 类视频平台默认资讯/工具，避免误判争议
    if plat in ("tiktok", "youtube") and scores["争议"] < 4:
        scores["争议"] *= 0.5

    best = max(scores, key=lambda k: scores[k])
    if scores[best] <= 1.5:  # 无任何特征命中
        return "资讯"
    return best


CTYPE_COLORS = {"工具": "#34d399", "资讯": "#7aa2ff", "观点": "#c4b5fd", "争议": "#f87171"}
