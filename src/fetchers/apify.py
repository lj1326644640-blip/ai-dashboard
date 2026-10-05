"""Reddit / X / TikTok 采集：统一走 Apify 第三方服务。

抓取发生在 Apify 服务端（自带代理池），本地只调 api.apify.com，
与本地网络代理和 Reddit 账号状态无关。无 token 时优雅跳过。
"""
from datetime import timedelta

from schema import now_utc, to_iso_utc
from http_util import http_get
from settings import log


def _num(item: dict, *keys):
    for k in keys:
        v = item.get(k)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return v
        if isinstance(v, str) and v.replace(".", "").isdigit():
            return float(v)
    return 0


def _str(item: dict, *keys) -> str:
    for k in keys:
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _author(item: dict, *keys) -> str:
    """author 字段可能是字符串，也可能是 {nickname, uniqueId...} 对象。"""
    for k in keys:
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            for kk in ("nickname", "nickName", "name", "username", "uniqueId", "handle"):
                vv = v.get(kk)
                if isinstance(vv, str) and vv.strip():
                    return vv.strip()
    return ""


def collect(cfg: dict) -> list[dict]:
    token = (cfg.get("apify", {}).get("token") or "").strip()
    if not token:
        log.info("Apify: 未配置 token，跳过 Reddit/X/TikTok 通道（填入 config.json 后自动启用）")
        return []
    try:
        from apify_client import ApifyClient
    except ImportError:
        log.error("Apify: 缺少 apify-client，请 pip install apify-client")
        return []

    client = ApifyClient(token)
    since = (now_utc() - timedelta(hours=cfg["window_hours"])).strftime("%Y-%m-%d")
    results = []
    for platform, fn in (("reddit", _collect_reddit), ("twitter", _collect_twitter),
                         ("tiktok", _collect_tiktok)):
        if not cfg["platforms"].get(platform, False):
            continue
        try:
            items = fn(client, cfg, since)
            log.info("Apify %s: 拿到 %d 条", platform, len(items))
            results.extend(items)
        except Exception as e:  # noqa: BLE001
            log.error("Apify %s 采集失败: %s", platform, e)
    return results


def _run_actor(client, actor_name: str, run_input: dict) -> list[dict]:
    run = client.actor(actor_name).call(run_input=run_input)
    return client.dataset(run["defaultDatasetId"]).list_items(clean=True).items


def _collect_reddit(client, cfg: dict, since: str) -> list[dict]:
    acfg = cfg["apify"]
    items = _run_actor(client, acfg["reddit_actor"], {
        "searches": cfg["queries"].get("reddit_searches", ["AI"]),
        "sort": "top", "time": "week",
        "includeMediaLinks": True,   # 不开拿不到 upVotes/评论数
        "maxItems": acfg["max_items"]["reddit"],
    })
    records = []
    for it in items:
        published = to_iso_utc(_str(it, "createdAt", "created_utc", "created", "postedAt")
                               or it.get("created_utc"))
        # reddit-scraper-lite 的 url/link 交替存"站内帖页"和"外链"，按域名判别
        u, lk = _str(it, "url"), _str(it, "link")
        redditish = lambda x: "reddit.com" in x  # noqa: E731
        discussion = lk if redditish(lk) else (u if redditish(u) else (lk or u))
        external = u if (u and not redditish(u)) else (lk if lk and not redditish(lk) else "")
        records.append({
            "id": "reddit_" + _str(it, "id", "postId", "parsedId").lstrip("t3_"),
            "platform": "reddit",
            "title": _str(it, "title"),
            "url": external or discussion,
            "discussion": discussion,
            "author": _author(it, "username", "author"),
            "published": published,
            "engagement": {
                "upvotes": _num(it, "upVotes", "upvotes", "score", "numberOfUpvotes"),
                "comments": _num(it, "numberOfComments", "numComments", "commentCount", "comments"),
                "upvote_ratio": _num(it, "upVoteRatio", "upvoteRatio"),
            },
            "text": _str(it, "body", "text", "selftext")[:400],
            "subreddit": _str(it, "communityName", "subreddit", "parsedCommunityName"),
        })
    return [r for r in records if r["title"]]


def _collect_twitter(client, cfg: dict, since: str) -> list[dict]:
    acfg = cfg["apify"]
    search_terms = [f"{q} since:{since}" for q in cfg["queries"].get("twitter", ["AI"])]
    items = _run_actor(client, acfg["twitter_actor"], {
        "searchTerms": search_terms,
        "sort": "Top",
        "maxItems": acfg["max_items"]["twitter"],
    })
    records = []
    for it in items:
        published = to_iso_utc(_str(it, "createdAt", "creationDate", "created_at"))
        records.append({
            "id": "twitter_" + _str(it, "id", "tweetId"),
            "platform": "twitter",
            "title": _str(it, "text", "fullText")[:140],
            "url": _str(it, "url", "tweetUrl") or
                   (f"https://x.com/{_str(it, 'username', 'handle')}/status/{_str(it, 'id', 'tweetId')}"
                    if _str(it, "username", "handle") and _str(it, "id", "tweetId") else ""),
            "discussion": _str(it, "url", "tweetUrl"),
            "author": _author(it, "author", "name", "username"),
            "published": published,
            "engagement": {
                "likes": _num(it, "likeCount", "likes", "favoriteCount"),
                "retweets": _num(it, "retweetCount", "retweets"),
                "replies": _num(it, "replyCount", "replies"),
                "quotes": _num(it, "quoteCount", "quotes"),
            },
            "text": _str(it, "text", "fullText")[:400],
        })
    return [r for r in records if r["title"]]


def _collect_tiktok(client, cfg: dict, since: str) -> list[dict]:
    acfg = cfg["apify"]
    items = _run_actor(client, acfg["tiktok_actor"], {
        "searchQueries": cfg["queries"].get("tiktok_searches", ["AI"]),
        "hashtags": cfg["queries"].get("tiktok_hashtags", []),
        "searchSection": "/video",
        "resultsPerPage": acfg["max_items"]["tiktok"],
        "shouldDownloadCovers": False,
        "shouldDownloadSlideshowImages": False,
        "shouldDownloadSubtitles": False,
    })
    records = []
    for it in items:
        published = to_iso_utc(_num(it, "createTime", "create_time")
                               or _str(it, "createTimeISO", "createdAt"))
        records.append({
            "id": "tiktok_" + _str(it, "id", "videoId", "video_id"),
            "platform": "tiktok",
            "title": _str(it, "description", "text", "title")[:140],
            "url": _str(it, "url", "webVideoUrl", "videoUrl"),
            "discussion": _str(it, "url", "webVideoUrl"),
            "author": _author(it, "authorMeta", "author", "uniqueId"),
            "published": published,
            "engagement": {
                "plays": _num(it, "playCount", "play_count", "plays"),
                "likes": _num(it, "diggCount", "digg_count", "likes"),
                "comments": _num(it, "commentCount", "comment_count", "comments"),
                "shares": _num(it, "shareCount", "share_count", "shares"),
            },
            "text": _str(it, "description", "text")[:400],
        })
    return [r for r in records if r["title"]]
