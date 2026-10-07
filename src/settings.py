"""配置加载 + 日志 + 全局路径（主题相关路径见 profile/topic helpers）。"""
import json
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(__file__).resolve().parent
DATA = ROOT / "data"          # 数据根（主题数据在其下 data/<topic>/）
LOGS = ROOT / "logs"
DOCS = ROOT / "docs"          # GitHub Pages 发布目录根（deploy.py 写入）

log = logging.getLogger("collector")


def topic_id(cfg: dict) -> str:
    return cfg.get("topic") or "ai-hot"


def topic_data_dir(cfg: dict) -> Path:
    """主题数据目录：data/<topic>/（按日归档、history、记忆、热度都在内）。"""
    return DATA / topic_id(cfg)


def dashboard_file(cfg: dict) -> Path:
    return ROOT / "dashboard" / topic_id(cfg) / "index.html"


def docs_file(cfg: dict) -> Path:
    return DOCS / topic_id(cfg) / "index.html"


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


def load_config(topic: str | None = None) -> dict:
    """兼容入口：委托 profile.load（configs/base + 主题 + secrets 深合并）。"""
    try:
        from profile import load as profile_load
        return profile_load(topic)
    except Exception as e:  # noqa: BLE001 - configs/ 缺失时退回旧 config.json
        log.warning("profile 加载失败(%s)，退回 config.json", e)
        with open(ROOT / "config.json", encoding="utf-8") as f:
            cfg = json.load(f)
        _inject_secrets_compat(cfg)
        return cfg


def _inject_secrets_compat(cfg: dict):
    sp = ROOT / "secrets.json"
    if sp.exists():
        try:
            _deep_merge(cfg, json.loads(sp.read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            log.warning("secrets.json 解析失败，已忽略: %s", e)
