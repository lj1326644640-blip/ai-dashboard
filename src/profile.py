"""主题(profile)配置加载：configs/base.json + configs/<topic>.yaml 深合并 + secrets.json 注入。

主题 = 一套独立的信息流（词表/渠道/产物），数据落 data/<topic>/。
"""
import json
from pathlib import Path

import yaml

from settings import ROOT, log


def _deep_merge(base: dict, override: dict) -> dict:
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _inject_secrets(cfg: dict):
    sp = ROOT / "secrets.json"
    if sp.exists():
        try:
            _deep_merge(cfg, json.loads(sp.read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            log.warning("secrets.json 解析失败，已忽略: %s", e)


def load(topic: str | None = None) -> dict:
    """加载主题配置；缺省 ai-hot（兼容现有行为）。"""
    topic = (topic or "ai-hot").strip()
    base_p = ROOT / "configs" / "base.json"
    cfg = json.loads(base_p.read_text(encoding="utf-8")) if base_p.exists() else {}
    tpath = ROOT / "configs" / f"{topic}.yaml"
    if tpath.exists():
        t = yaml.safe_load(tpath.read_text(encoding="utf-8")) or {}
        _deep_merge(cfg, t)
    elif topic != "ai-hot":
        log.warning("主题配置 %s 不存在，仅用 base 配置", tpath.name)
    _inject_secrets(cfg)
    cfg["topic"] = topic
    return cfg
