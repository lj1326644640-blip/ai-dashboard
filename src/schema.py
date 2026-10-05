"""统一记录 schema 的公共逻辑：日期解析、互动合成、指纹、同名题判定。"""
import hashlib
import re
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------- 日期
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_iso_utc(value) -> str | None:
    """把各种时间表示统一成 ISO UTC 字符串；解析失败返回 None。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
        except (ValueError, OSError, OverflowError):
            return None
    s = str(value).strip()
    if not s:
        return None
    if re.fullmatch(r"\d{9,13}", s):  # unix 秒/毫秒
        ts = int(s)
        if ts > 1e12:
            ts //= 1000
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except (ValueError, OSError, OverflowError):
            return None
    try:
        return dateutil_parse(s)
    except Exception:  # noqa: BLE001
        return None


def dateutil_parse(s: str) -> str:
    from email.utils import parsedate_to_datetime
    d = parsedate_to_datetime(s)  # RFC822 (RSS pubDate)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat()


def hours_since(iso_str: str | None) -> float | None:
    if not iso_str:
        return None
    try:
        d = datetime.fromisoformat(iso_str)
        return max(0.0, (now_utc() - d).total_seconds() / 3600)
    except ValueError:
        return None


def fmt_local(iso_str: str | None, offset_hours: int = 8) -> str:
    """报告展示用：UTC → 当地时间字符串。"""
    if not iso_str:
        return "未知"
    try:
        d = datetime.fromisoformat(iso_str) + timedelta(hours=offset_hours)
        return d.strftime("%m-%d %H:%M")
    except ValueError:
        return "未知"


# ---------------------------------------------------------------- 互动合成
def _g(eng: dict, *keys):
    for k in keys:
        v = eng.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0


def composite_engagement(platform: str, eng: dict) -> float:
    """平台内互动合成一个可比数（排序/速度用，不跨平台比较绝对值）。"""
    if platform == "hn":
        return _g(eng, "points") + 0.5 * _g(eng, "comments")
    if platform == "reddit":
        return _g(eng, "upvotes", "score") + 0.5 * _g(eng, "comments")
    if platform == "twitter":
        return _g(eng, "likes") + 2 * _g(eng, "retweets") + _g(eng, "replies") + _g(eng, "quotes")
    if platform == "tiktok":
        return 0.02 * _g(eng, "plays") + _g(eng, "likes") + 2 * _g(eng, "shares") + _g(eng, "comments")
    if platform == "youtube":
        return 0.02 * _g(eng, "views") + 2 * _g(eng, "likes") + 3 * _g(eng, "comments")
    return 0.0  # producthunt 无互动数据，靠LLM分补偿


PLATFORM_NAMES = {
    "hn": "Hacker News", "producthunt": "Product Hunt", "reddit": "Reddit",
    "twitter": "X/Twitter", "tiktok": "TikTok", "youtube": "YouTube",
}


def engagement_summary(platform: str, eng: dict) -> str:
    p = lambda *ns: f"{int(_g(eng, *ns)):,}"  # noqa: E731
    if platform == "hn":
        return f"{p('points')} points · {p('comments')} comments"
    if platform == "reddit":
        return f"{p('upvotes', 'score')} upvotes · {p('comments')} comments"
    if platform == "twitter":
        return f"{p('likes')} likes · {p('retweets')} RT · {p('replies')} replies"
    if platform == "tiktok":
        return f"{p('plays')} plays · {p('likes')} likes · {p('comments')} comments"
    if platform == "youtube":
        return f"{p('views')} views · {p('likes')} likes"
    return "-"


def enrich(records: list[dict], cfg: dict) -> list[dict]:
    """采集后统一补齐：engagement_total / summary / collected_at / 指纹。"""
    out = []
    for r in records:
        r["engagement_total"] = composite_engagement(r["platform"], r.get("engagement") or {})
        r["engagement_summary"] = engagement_summary(r["platform"], r.get("engagement") or {})
        r["collected_at"] = now_utc().isoformat()
        r["fingerprint"] = fingerprint(r)
        out.append(r)
    return out


# ---------------------------------------------------------------- 指纹
_UTM = re.compile(r"[?&](utm_\w+|ref|ref_src|fbclid|gclid|si)=[^&]*")
_PUNCT = re.compile(r"[^\w\s]")


def normalize_title(t: str) -> str:
    return re.sub(r"\s+", " ", _PUNCT.sub(" ", (t or "").lower())).strip()


def fingerprint(rec: dict) -> str:
    url = (rec.get("url") or "").strip()
    if url:
        u = _UTM.sub("", url).split("#")[0].lower().rstrip("/")
        return "u:" + hashlib.md5(u.encode()).hexdigest()
    return "t:" + hashlib.md5(normalize_title(rec.get("title", "")).encode()).hexdigest()


def title_similarity(a: str, b: str) -> float:
    ta, tb = set(normalize_title(a).split()), set(normalize_title(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def strip_html(html_s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_s or "")).strip()
