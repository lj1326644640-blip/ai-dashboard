"""YouTube 采集：走本地代理 + yt-dlp 搜索热榜视频（CLI方式，免API key）。

搜索结果先按播放量排序，再对头部视频取完整元数据（发布时间/点赞）做时间窗过滤。
入选后的视频内容深挖（字幕/描述提取）由 finalize 阶段用 defuddle 完成。
"""
from schema import to_iso_utc
from http_util import detect_proxy
from settings import log


def collect(cfg: dict) -> list[dict]:
    if not cfg["platforms"].get("youtube", False):
        return []
    try:
        import yt_dlp
    except ImportError:
        log.error("YouTube: 缺少 yt-dlp，请 pip install yt-dlp")
        return []

    proxy = detect_proxy(cfg)
    if not proxy:
        log.info("YouTube: 未检测到本地代理，跳过（youtube.com 直连不通）")
        return []

    per_query = 15
    flat_entries = []
    flat_opts = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "extract_flat": "in_playlist", "proxy": proxy,
        "socket_timeout": 20, "retries": 2,
    }
    try:
        with yt_dlp.YoutubeDL(flat_opts) as ydl:
            for q in cfg["queries"].get("youtube", ["AI"]):
                info = ydl.extract_info(f"ytsearch{per_query}:{q}", download=False)
                for e in info.get("entries") or []:
                    if e:
                        e["_query"] = q
                        flat_entries.append(e)
    except Exception as e:  # noqa: BLE001
        log.error("YouTube 搜索失败(代理 %s): %s", proxy, e)
        return []

    if not flat_entries:
        log.info("YouTube: 搜索无结果")
        return []

    # 按播放量排序取头部，再补完整元数据（发布时间/点赞数）
    def views(e):
        return e.get("view_count") or 0
    top = sorted(flat_entries, key=views, reverse=True)[:30]

    full_opts = dict(flat_opts, extract_flat=False)
    records = []
    with yt_dlp.YoutubeDL(full_opts) as ydl:
        for e in top:
            vid = e.get("id")
            if not vid:
                continue
            url = f"https://www.youtube.com/watch?v={vid}"
            try:
                info = ydl.extract_info(url, download=False)
            except Exception as err:  # noqa: BLE001
                log.warning("YouTube 视频 %s 元数据失败: %s", vid, err)
                info = e  # 退回 flat 数据：无发布时间，时间窗过滤时放行
            upload_date = info.get("upload_date")  # yt-dlp 返回 "YYYYMMDD"
            if isinstance(upload_date, str) and len(upload_date) == 8 and upload_date.isdigit():
                upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}T12:00:00+00:00"
            published = to_iso_utc(upload_date
                                   or (info.get("timestamp") and str(info["timestamp"])))
            records.append({
                "id": f"youtube_{vid}",
                "platform": "youtube",
                "title": info.get("title") or e.get("title", ""),
                "url": url,
                "discussion": url,
                "author": info.get("channel") or info.get("uploader") or "",
                "published": published,
                "engagement": {
                    "views": info.get("view_count") or views(e),
                    "likes": info.get("like_count") or 0,
                    "comments": info.get("comment_count") or 0,
                },
                "text": (info.get("description") or "")[:400],
                "_query": e.get("_query", ""),
            })
    log.info("YouTube: 拿到 %d 条(代理 %s)", len(records), proxy)
    return [r for r in records if r["title"]]
