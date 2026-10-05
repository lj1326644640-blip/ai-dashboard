"""AI爆款内容每日抓取管线（入口）。

用法:
  python run_daily.py collect    # 采集全部启用平台 → 过滤 → 规则打分 → data/candidates_当天.json
  python run_daily.py deep       # (可选) defuddle 深挖YouTube头部视频内容
  python run_daily.py finalize   # 合并LLM打分(如有) → 导出 Excel榜单 + Markdown日报
  python run_daily.py all        # collect + finalize（不做LLM步，直接用规则分排序）
  python run_daily.py status     # 输出当日状态JSON（供定时任务/工作流读取）
"""
import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from collectors import apify_run, hn, producthunt, youtube  # noqa: E402
from collectors.common import (DATA, LOGS, load_config, log, now_utc,  # noqa: E402
                               enrich, setup_logging)
from pipeline import export, filter as flt, rule_score  # noqa: E402

REPORTS = ROOT / "reports"
TZ = lambda cfg: timedelta(hours=cfg["timezone_offset_hours"])


def local_date_str(cfg) -> str:
    return (now_utc() + TZ(cfg)).strftime("%Y-%m-%d")


def candidates_file(cfg) -> Path:
    return DATA / f"candidates_{local_date_str(cfg)}.json"


def collect(cfg: dict) -> list[dict]:
    setup_logging()
    records = []
    channels = []
    collectors_map = [
        ("hn", hn.collect), ("producthunt", producthunt.collect),
        ("apify", apify_run.collect), ("youtube", youtube.collect),
    ]
    for name, fn in collectors_map:
        try:
            got = fn(cfg)
            records.extend(got)
            if got:
                channels.append(name)
        except Exception as e:  # noqa: BLE001
            log.error("采集器 %s 崩溃: %s", name, e)
    log.info("采集完成: %d 条原始记录 (通道: %s)", len(records), "+".join(channels) or "无")
    return enrich(records, cfg), channels


def run_collect():
    cfg = load_config()
    records, channels = collect(cfg)
    # 幂等：当天重复运行时，已有候选不作为重复剔除（增量补新）
    cf = candidates_file(cfg)
    prior_fps: set[str] = set()
    if cf.exists():
        try:
            prior_fps = {r["fingerprint"] for r in json.loads(cf.read_text(encoding="utf-8"))}
        except Exception:  # noqa: BLE001
            prior_fps = set()
    history_fp = flt.load_history(DATA / "history.jsonl")
    kept, stats = flt.apply(records, cfg, history_fp, prior_fps)
    stats["channels"] = "+".join(channels) or "无"
    stats["by_platform"] = {}
    scored = rule_score.score(kept, cfg)
    for r in scored:
        stats["by_platform"][r["platform"]] = stats["by_platform"].get(r["platform"], 0) + 1
    flt.update_history(DATA / "history.jsonl", kept, history_fp | prior_fps)
    DATA.mkdir(exist_ok=True)
    cf.write_text(json.dumps(scored, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("候选 %d 条 → %s | 过滤明细: %s", len(scored), cf.name,
             {k: v for k, v in stats.items()})
    print(json.dumps({"ok": True, "candidates": len(scored), "file": str(cf),
                      "stats": stats}, ensure_ascii=False))
    return scored


def load_llm_scores(cfg: dict) -> dict:
    """合并 data/llm_scores_*.json 和 data/llm_scores/*.json（工作流分批写入），按 id 索引。"""
    paths = list(DATA.glob("llm_scores_*.json"))
    batch_dir = DATA / "llm_scores"
    if batch_dir.exists():
        paths += list(batch_dir.glob("*.json"))
    scores = {}
    for p in paths:
        try:
            for item in json.loads(p.read_text(encoding="utf-8")):
                if isinstance(item, dict) and item.get("id"):
                    scores[item["id"]] = item
        except Exception as e:  # noqa: BLE001
            log.warning("LLM打分文件 %s 解析失败: %s", p, e)
    return scores


def run_finalize():
    cfg = load_config()
    cf = candidates_file(cfg)
    if not cf.exists():
        print(json.dumps({"ok": False, "error": "请先运行 collect",
                          "missing": str(cf)}, ensure_ascii=False))
        sys.exit(1)
    candidates = json.loads(cf.read_text(encoding="utf-8"))
    llm = load_llm_scores(cfg)
    ranked = rule_score.apply_llm_and_rank(candidates, llm, cfg)
    top = ranked[:cfg["top_n"]]

    out_dir = REPORTS / local_date_str(cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    export.set_tz(cfg["timezone_offset_hours"])
    export.export_xlsx(top, ranked, out_dir / "榜单.xlsx", cfg)
    channels = _channels_of(cf)
    export.export_md(top, out_dir / "日报.md", cfg,
                     {"kept": len(ranked), "channels": channels}, local_date_str(cfg))
    stats = {"kept": len(ranked), "channels": channels}
    export.write_meta(out_dir / "meta.json", top, stats)
    from pipeline import dashboard
    dash_path = dashboard.generate(REPORTS, cfg)
    publish_status = ""
    if cfg.get("publish", {}).get("enabled") and "--no-publish" not in sys.argv:
        from pipeline.publish import publish
        publish_status = publish(cfg)
        log.info("GitHub Pages 发布: %s", publish_status)
    llm_note = f"LLM打分覆盖 {len(llm)} 条" if llm else "无LLM打分(纯规则分)"
    log.info("完成: Top%d → %s | %s | 看板: %s", len(top), out_dir, llm_note, dash_path)
    if cfg.get("auto_open_dashboard", True) and "--no-open" not in sys.argv:
        try:
            import os
            os.startfile(dash_path)  # Windows 下自动在浏览器打开看板
        except Exception as e:  # noqa: BLE001
            log.warning("自动打开看板失败(不影响产出): %s", e)
    print(json.dumps({"ok": True, "top_n": len(top), "report_dir": str(out_dir),
                      "dashboard": str(dash_path), "llm_covered": len(llm),
                      "publish": publish_status}, ensure_ascii=False))
    return top


def _channels_of(cf: Path) -> str:
    try:
        data = json.loads(cf.read_text(encoding="utf-8"))
        return "+".join(sorted({r["platform"] for r in data}))
    except Exception:  # noqa: BLE001
        return "-"


def run_deep():
    cfg = load_config()
    from pipeline.defuddle_extract import enrich_candidates
    n = enrich_candidates(candidates_file(cfg), cfg, only_platform="youtube",
                          top=10)
    print(json.dumps({"ok": True, "enriched": n}, ensure_ascii=False))


def run_ids():
    """输出今日候选 id 清单（供工作流分批打分用）。"""
    cfg = load_config()
    cf = candidates_file(cfg)
    try:
        data = json.loads(cf.read_text(encoding="utf-8"))
        print(json.dumps([r["id"] for r in data], ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)


def run_status():
    cfg = load_config()
    cf = candidates_file(cfg)
    n = 0
    platforms = {}
    if cf.exists():
        try:
            data = json.loads(cf.read_text(encoding="utf-8"))
            n = len(data)
            for r in data:
                platforms[r["platform"]] = platforms.get(r["platform"], 0) + 1
        except Exception:  # noqa: BLE001
            pass
    llm = load_llm_scores(cfg) if cf.exists() else {}
    print(json.dumps({
        "date": local_date_str(cfg),
        "candidates_file": str(cf),
        "candidates": n,
        "by_platform": platforms,
        "llm_scores": len(llm),
        "report_dir": str(REPORTS / local_date_str(cfg)),
    }, ensure_ascii=False))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    setup_logging()
    if cmd == "collect":
        run_collect()
    elif cmd == "deep":
        run_deep()
    elif cmd == "finalize":
        run_finalize()
    elif cmd == "all":
        run_collect()
        run_finalize()
    elif cmd == "status":
        run_status()
    elif cmd == "ids":
        run_ids()
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
