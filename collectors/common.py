"""采集器共用工具：HTTP、代理探测、日期解析、互动合成、指纹。"""
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
LOGS = ROOT / "logs"

log = logging.getLogger("collector")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def setup_logging():
    LOGS.mkdir(exist_ok=True)
    if log.handlers:
        return
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(LOGS / "collect.log", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _deep_merge(base: dict, override: dict) -> dict:
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load_config() -> dict:
    """config.json 为基础配置；secrets.json（密钥/端口等敏感项）存在时覆盖合并。"""
    with open(ROOT / "config.json", encoding="utf-8") as f:
        cfg = json.load(f)
    sp = ROOT / "secrets.json"
    if sp.exists():
        try:
            _deep_merge(cfg, json.loads(sp.read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            log.warning("secrets.json 解析失败，已忽略: %s", e)
    return cfg


def http_get(url, *, params=None, timeout=20, retries=2, proxies=None, headers=None):
    hdrs = {"User-Agent": UA}
    if headers:
        hdrs.update(headers)
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, timeout=timeout,
                             proxies=proxies, headers=hdrs)
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001 - 网络错误统一重试
            last_err = e
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    raise last_err


# ---------------------------------------------------------------- 代理探测
_PROXY_CACHE = DATA / "proxy_state.json"
_PROBE_URL = "https://www.google.com/generate_204"
_PROXY_TTL_HOURS = 12


def _proxy_works(host: str, port: int) -> bool:
    try:
        r = requests.get(_PROBE_URL, timeout=6,
                         proxies={"http": f"http://{host}:{port}",
                                  "https": f"http://{host}:{port}"})
        return r.status_code < 400
    except Exception:  # noqa: BLE001
        return False


def detect_proxy(cfg: dict) -> str | None:
    """返回可用的本地代理 http://host:port，探测结果缓存；找不到返回 None。"""
    pcfg = cfg.get("proxy", {})
    if pcfg.get("mode") == "off":
        return None
    host = pcfg.get("host", "127.0.0.1")

    if _PROXY_CACHE.exists():
        try:
            state = json.loads(_PROXY_CACHE.read_text(encoding="utf-8"))
            age_h = (now_utc() - datetime.fromisoformat(state["checked_at"])).total_seconds() / 3600
            if age_h < _PROXY_TTL_HOURS:
                return state.get("proxy")
        except Exception:  # noqa: BLE001
            pass

    proxy = None
    explicit = pcfg.get("port")
    ports = [explicit] if explicit else pcfg.get("common_ports", [])
    for port in ports:
        if _proxy_works(host, int(port)):
            proxy = f"http://{host}:{int(port)}"
            break
    _PROXY_CACHE.parent.mkdir(exist_ok=True)
    _PROXY_CACHE.write_text(json.dumps(
        {"proxy": proxy, "checked_at": now_utc().isoformat()}, ensure_ascii=False), encoding="utf-8")
    if proxy:
        log.info("检测到可用代理: %s", proxy)
    else:
        log.info("未检测到本地代理，走直连/跳过受限通道")
    return proxy


# ---------------------------------------------------------------- 日期
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
    from datetime import datetime as dt
    try:
        d = parsedate_to_datetime(s)  # RFC822 (RSS pubDate)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:  # noqa: BLE001
        pass
    d = dt.fromisoformat(s.replace("Z", "+00:00"))
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


def strip_html(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()
