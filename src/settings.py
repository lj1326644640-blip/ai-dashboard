"""配置加载（合并 secrets.json）+ 日志 + 全局路径。"""
import json
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(__file__).resolve().parent
DATA = ROOT / "data"
LOGS = ROOT / "logs"
DASHBOARD = ROOT / "dashboard" / "index.html"
DOCS = ROOT / "docs"  # GitHub Pages 发布目录（deploy.py 写入）

log = logging.getLogger("collector")


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
