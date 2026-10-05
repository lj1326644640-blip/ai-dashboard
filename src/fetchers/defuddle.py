"""defuddle 内容深挖：对入选的 YouTube（及可选其他）视频提取描述/字幕，充实日报摘要。

用法：python src/fetchers/defuddle.py <candidates.json路径> [--only youtube] [--top 10]
依赖 Node(npx) 与网络可达 youtube.com（需代理，自动探测）。失败静默降级，不阻塞主管线。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from http_util import detect_proxy  # noqa: E402
from settings import load_config, log, setup_logging  # noqa: E402


def extract(url: str, proxy: str | None, timeout: int = 90) -> dict | None:
    env = dict(os.environ)
    if proxy:
        env["HTTPS_PROXY"] = proxy
        env["HTTP_PROXY"] = proxy
        env["NODE_USE_ENV_PROXY"] = "1"  # Node 24+ fetch 走环境变量代理
    try:
        r = subprocess.run(
            ["npx", "-y", "defuddle", "parse", url, "--json"],
            capture_output=True, text=True, timeout=timeout, env=env,
            shell=False, encoding="utf-8", errors="replace",
        )
        if r.returncode != 0 or not r.stdout.strip():
            log.warning("defuddle %s 失败: %s", url, (r.stderr or "")[:200])
            return None
        start = r.stdout.find("{")
        return json.loads(r.stdout[start:]) if start >= 0 else None
    except Exception as e:  # noqa: BLE001
        log.warning("defuddle %s 异常: %s", url, e)
        return None


def enrich_candidates(candidates_file: Path, cfg: dict, only_platform: str = "youtube",
                      top: int = 10):
    """给候选JSON中指定平台的头部条目补 description/transcript，原地更新。"""
    data = json.loads(candidates_file.read_text(encoding="utf-8"))
    proxy = detect_proxy(cfg)
    if not proxy:
        log.info("defuddle: 无代理，跳过内容深挖")
        return 0
    targets = [r for r in data if r.get("platform") == only_platform][:top]
    count = 0
    for r in targets:
        result = extract(r["url"], proxy)
        if not result:
            continue
        bits = []
        if result.get("description"):
            bits.append(str(result["description"])[:600])
        if result.get("content"):
            bits.append(str(result["content"])[:1500])
        if bits:
            r["text"] = (r.get("text", "") + "\n" + "\n".join(bits)).strip()[:2000]
            if result.get("author") and not r.get("author"):
                r["author"] = result["author"]
            count += 1
    candidates_file.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("defuddle: 深挖 %d/%d 条", count, len(targets))
    return count


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("candidates_file")
    ap.add_argument("--only", default="youtube")
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()
    from collectors.common import setup_logging, load_config
    setup_logging()
    enrich_candidates(Path(args.candidates_file), load_config(), args.only, args.top)
