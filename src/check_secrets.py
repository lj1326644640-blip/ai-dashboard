"""凭据体检：secrets.json 完整性、Apify token 有效性、代理端口可用性。

用法: python src/check_secrets.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from http_util import _proxy_works  # noqa: E402
from settings import ROOT, load_config  # noqa: E402


def main():
    cfg = load_config()
    ok = True
    print("====== 凭据体检 ======")

    sp = ROOT / "secrets.json"
    if not sp.exists():
        print("❌ secrets.json 不存在（复制模板并填入 Apify token）")
        ok = False
    else:
        print("✅ secrets.json 存在")

    token = (cfg.get("apify", {}).get("token") or "").strip()
    if not token:
        print("⚠️ Apify token 未配置 → Reddit/X/TikTok 通道跳过")
    else:
        import requests
        try:
            r = requests.get(f"https://api.apify.com/v2/users/me?token={token}", timeout=10)
            if r.status_code == 200:
                print(f"✅ Apify token 有效（账号 {r.json()['data']['username']}）")
            else:
                print(f"❌ Apify token 无效（HTTP {r.status_code}）")
                ok = False
        except Exception as e:  # noqa: BLE001
            print(f"❌ Apify 连不上: {e}")
            ok = False

    port = cfg.get("proxy", {}).get("port")
    if port:
        host = cfg.get("proxy", {}).get("host", "127.0.0.1")
        if _proxy_works(host, int(port)):
            print(f"✅ 代理 {host}:{port} 可用（YouTube 通道+稳定推送）")
        else:
            print(f"⚠️ 代理 {host}:{port} 当前不通（YouTube 跳过；推送走直连重试）")
    else:
        print("ℹ️ 代理端口未固定（自动探测常见端口）")

    print("====== 结论:", "全部通过" if ok else "存在问题，见上", "======")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
