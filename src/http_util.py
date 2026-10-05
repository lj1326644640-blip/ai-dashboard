"""代理感知 HTTP 请求 + 自动重试 + 本地代理探测（结果缓存12小时）。"""
import json
import time
from datetime import datetime, timezone

import requests

from settings import DATA, log

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


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
            age_h = (datetime.now(timezone.utc)
                     - datetime.fromisoformat(state["checked_at"])).total_seconds() / 3600
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
    DATA.mkdir(parents=True, exist_ok=True)
    _PROXY_CACHE.write_text(json.dumps(
        {"proxy": proxy, "checked_at": datetime.now(timezone.utc).isoformat()},
        ensure_ascii=False), encoding="utf-8")
    if proxy:
        log.info("检测到可用代理: %s", proxy)
    else:
        log.info("未检测到本地代理，走直连/跳过受限通道")
    return proxy
