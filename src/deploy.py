"""发布看板到 GitHub Pages：docs/index.html（看板副本）→ git commit → push。

finalize 末尾自动调用；无远程仓库/离线/推送失败都只记日志，不阻塞主管线。
首次推送会弹出 Git Credential Manager 授权窗口（浏览器登录 GitHub 一次即可）。
"""
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from settings import ROOT


def _git(*args: str, timeout: int = 60) -> tuple[int, str]:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                       text=True, timeout=timeout, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def publish(cfg: dict) -> str:
    """返回发布状态描述；绝不抛异常。"""
    try:
        rc, out = _git("remote", "get-url", "origin")
        if rc != 0:
            return "skip: 未配置远程仓库（git remote add origin 后自动启用）"

        # 1) 看板副本 → docs/index.html（Pages 以 /docs 为根，访问首页即看板）
        dash = ROOT / "dashboard" / "index.html"
        if not dash.exists():
            return "skip: dashboard.html 不存在"
        docs = ROOT / "docs"
        docs.mkdir(exist_ok=True)
        shutil.copy2(dash, docs / "index.html")

        # 2) commit（无变化则跳过）
        _git("add", "docs", "data", "dashboard")
        stamp = (datetime.now(timezone.utc) + timedelta(hours=cfg["timezone_offset_hours"])
                 ).strftime("%Y-%m-%d %H:%M")
        rc, out = _git("commit", "-m", f"看板更新 {stamp}")
        if rc != 0 and "nothing to commit" not in out:
            return f"skip: commit 失败 {out.strip()[:150]}"
        if "nothing to commit" in out:
            return "ok: 内容无变化，无需推送"

        # 3) push（首次会弹 GCM 授权窗口，等待用户完成；网络间歇失败自动重试）
        rc, out = 1, ""
        for attempt in range(3):
            rc, out = _git("push", "origin", cfg["publish"]["branch"], timeout=300)
            if rc == 0:
                break
            time.sleep(10)
        if rc != 0:
            return f"fail: push 失败(重试3次) {out.strip()[:200]}"
        return "ok: 已推送到 GitHub Pages"
    except Exception as e:  # noqa: BLE001
        return f"fail: {e}"


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT))
    from collectors.common import setup_logging, load_config, log
    setup_logging()
    print(publish(load_config()))
