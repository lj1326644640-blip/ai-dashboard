"""小红书采集：多供应商抽象（zen-studio Apify actor 已验证 / TikHub 待key接入）。

主题配置 configs/<topic>.yaml 的 xhs 段：
  provider: apify | tikhub
  pools: {brand: [...], competitor: [...], category: [...]}
每条记录带 pool/keyword 归属；互动字段统一为 likes/collects/comments/shares（CES合成用）。
"""
import time

from schema import to_iso_utc
from settings import log


def collect(cfg: dict) -> list[dict]:
    xcfg = cfg.get("xhs", {})
    pools = xcfg.get("pools", {})
    if not pools:
        log.info("XHS: 未配置 pools，跳过")
        return []
    provider = xcfg.get("provider", "apify")
    try:
        if provider == "apify":
            records = _collect_apify(cfg, pools)
        elif provider == "tikhub":
            records = _collect_tikhub(cfg, pools)
        else:
            log.error("XHS: 未知 provider %s", provider)
            return []
    except Exception as e:  # noqa: BLE001 - 单通道失败不拖垮整期采集
        log.error("XHS 采集失败(%s): %s", provider, e)
        return []
    log.info("XHS: 拿到 %d 条(%s)", len(records), provider)
    return records


def _norm(it: dict, pool: str, keyword: str) -> dict:
    eng = it.get("engagement") or {}
    author = it.get("author")
    nickname = author.get("nickname", "") if isinstance(author, dict) else str(author or "")
    tags = []
    for t in it.get("tag_info") or []:
        if isinstance(t, dict) and t.get("name"):
            tags.append(t["name"])
    title = (it.get("title") or "").strip() or (it.get("desc") or "").split("\n")[0][:40] or "(视频笔记)"
    return {
        "id": f"xhs_{it.get('id')}",
        "platform": "xhs",
        "title": title,
        "url": it.get("url") or "",
        "discussion": it.get("url") or "",
        "author": nickname,
        "published": to_iso_utc(it.get("timestamp") or it.get("time")),
        "engagement": {
            "likes": eng.get("liked_count") or eng.get("likes") or 0,
            "collects": eng.get("collected_count") or eng.get("collects") or 0,
            "comments": eng.get("comments_count") or eng.get("comments") or 0,
            "shares": eng.get("shared_count") or eng.get("shares") or 0,
        },
        "text": (it.get("desc") or "")[:400],
        "pool": pool,
        "keyword": keyword,
        "note_type": it.get("type") or "",
        "tags": tags[:10],
    }


def _collect_apify(cfg: dict, pools: dict) -> list[dict]:
    from apify_client import ApifyClient

    xcfg = cfg["xhs"]
    client = ApifyClient(cfg["apify"]["token"])
    actor = xcfg.get("apify_actor", "zen-studio/rednote-search-scraper")
    out = []
    for pool, kws in pools.items():
        kws = [k for k in kws if k]
        if not kws:
            continue
        run_input = {
            "keywords": kws,
            "maxResults": xcfg.get("max_results", 30),
            "sortType": xcfg.get("sort_type", "popularity_descending"),
            "timeFilter": xcfg.get("time_filter", "6mo"),
            "topUpFromOtherSorts": False,
        }
        run = client.actor(actor).call(run_input=run_input)
        items = client.dataset(run["defaultDatasetId"]).list_items(clean=True).items
        for it in items:
            kw = it.get("keyword") or (kws[0] if kws else "")
            out.append(_norm(it, pool, kw))
        log.info("XHS %s 池(%d词): %d 条", pool, len(kws), len(items))
        time.sleep(2)
    return out


def _collect_tikhub(cfg: dict, pools: dict) -> list[dict]:
    """TikHub REST（$0.01/请求，搜索自带赞藏评）。响应结构待拿到key实测后校准。"""
    import requests

    xcfg = cfg["xhs"]
    tk = xcfg.get("tikhub") or {}
    key = tk.get("api_key")
    if not key:
        log.info("XHS: TikHub api_key 未配置，跳过（secrets.json 填 tikhub.api_key）")
        return []
    base = tk.get("api_base", "https://api.tikhub.io")
    path = tk.get("search_path", "/api/v1/xhs/search/notes")
    out = []
    for pool, kws in pools.items():
        for kw in kws:
            try:
                r = requests.get(base + path,
                                 headers={"Authorization": f"Bearer {key}"},
                                 params={"keyword": kw, "page": 1}, timeout=20)
                r.raise_for_status()
                data = r.json().get("data") or {}
                items = data.get("items") or data.get("notes") or []
                for it in items:
                    note = it.get("noteCard") or it.get("note") or it
                    interact = note.get("interactInfo") or {}
                    eng = {"likes": interact.get("liked_count"),
                           "collects": interact.get("collected_count"),
                           "comments": interact.get("comment_count"),
                           "shares": interact.get("share_count")}
                    out.append(_norm({**note, "engagement": eng,
                                      "timestamp": note.get("time"),
                                      "url": f"https://www.xiaohongshu.com/explore/{note.get('id','')}"},
                                     pool, kw))
            except Exception as e:  # noqa: BLE001
                log.warning("XHS TikHub '%s' 失败: %s", kw, e)
            time.sleep(1)
        log.info("XHS %s 池: 累计 %d 条", pool, len(out))
    return out
