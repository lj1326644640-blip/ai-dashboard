"""话题识别：词表（含别名）匹配 + 标题专名兜底，输出每条内容的话题标签。

词表在 config.json 的 topic_lexicon（话题 → 别名列表），用户可直接增删；
一条内容可属于多个话题（命中即计入），最多保留4个，保证热度统计不稀释。
"""
import re

# 自动兜底话题时排除的通用词（不构成有意义的领域）
_GENERIC = {
    "the", "and", "for", "with", "new", "how", "why", "what", "your", "you",
    "are", "was", "can", "our", "has", "have", "been", "more", "most", "best",
    "top", "first", "all", "one", "two", "out", "get", "got", "use", "using",
    "used", "via", "into", "over", "after", "before", "about", "they", "them",
    "its", "not", "but", "from", "this", "that", "will", "would", "could",
    "should", "than", "then", "when", "who", "says", "said", "here", "just",
    "like", "made", "make", "real", "free", "open", "pro", "app", "his", "her",
    "why", "end", "own", "off", "now", "day", "way", "big", "run", "runs",
}
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9.+#-]{2,}")


def extract_topics(rec: dict, lexicon: dict) -> list[str]:
    text = f"{rec.get('title', '')} {rec.get('text', '')}".lower()
    hits: list[str] = []
    for topic, aliases in lexicon.items():
        for alias in aliases:
            if alias.lower() in text:
                hits.append(topic)
                break

    if not hits:
        # 兜底：标题中段位置的大写专名（如新产品名），前缀 n: 与词表话题区分
        tokens = _TOKEN_RE.findall(rec.get("title", "") or "")
        known = {a.lower() for aliases in lexicon.values() for a in aliases}
        autos = []
        for i, tok in enumerate(tokens):
            tl = tok.lower().rstrip(".")
            if i == 0 or tl in _GENERIC or tl in known or len(tl) < 3:
                continue
            if tok[0].isupper():
                autos.append("n:" + tl)
        hits = list(dict.fromkeys(autos))[:2]

    return hits[:4]
