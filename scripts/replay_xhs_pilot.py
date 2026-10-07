"""把 Phase A 试点数据回放进 xhs-stacato 主题管线（替代一次 collect，零花费）。

用法: python scripts/replay_xhs_pilot.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fetchers import xhs  # noqa: E402
from main import candidates_file, run_log  # noqa: E402
from pipeline import normalize as flt  # noqa: E402
from pipeline import scorer  # noqa: E402
from profile import load  # noqa: E402
from schema import enrich  # noqa: E402
from settings import log, setup_logging, topic_data_dir  # noqa: E402


def main():
    setup_logging()
    cfg = load("xhs-stacato")
    src = ROOT / "data" / "xhs-stacato-pilot_zen-studio.json"
    items = json.loads(src.read_text(encoding="utf-8"))
    records = enrich([xhs._norm(it, "brand", "思加图") for it in items], cfg)

    tdir = topic_data_dir(cfg)
    history_fp = flt.load_history(tdir / "history.jsonl")
    kept, stats = flt.apply(records, cfg, history_fp, set())
    stats["channels"] = "xhs-replay"
    scored = scorer.score(kept, cfg)
    flt.update_history(tdir / "history.jsonl", kept, history_fp)

    cf = candidates_file(cfg)
    cf.parent.mkdir(parents=True, exist_ok=True)
    cf.write_text(json.dumps(scored, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("回放完成: %d/%d 条 → %s", len(scored), len(items), cf)
    run_log(cfg, "collect", candidates=len(scored), channels="xhs-replay")
    print(json.dumps({"ok": True, "candidates": len(scored), "file": str(cf)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
