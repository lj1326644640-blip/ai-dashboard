"""AI爆款内容日报主管线（统一入口，支持多主题）。

用法（工作目录=项目根）:
  python src/main.py [--topic <主题id>] <命令>
  命令:
    collect    # 采集全部启用通道 → 过滤 → 规则打分 → data/<主题>/当天/full.json
    deep       # (可选) defuddle 深挖YouTube头部视频内容
    finalize   # 合并LLM打分(如有) → 看板 + Excel榜单 + 日报 + 升温识别 + 发布Pages
    all        # collect + finalize（不做LLM步，直接用规则分排序）
    status     # 输出当日状态JSON（供定时任务/工作流读取）
    ids        # 输出今日候选id清单（供工作流分批打分）
  主题: --topic ai-hot（缺省）/ xhs-stacato / ...（配置在 configs/<主题>.yaml）

流程: fetchers(抓取) → normalize(过滤去重) → scorer(规则分+类型) → LLM打分(人工级)
      → report(Excel/MD) → dashboard(看板) → heat(升温识别) → deploy(GitHub Pages)
"""
import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetchers import apify, hn, producthunt, xhs, youtube  # noqa: E402
from profile import load as load_profile  # noqa: E402
from schema import enrich, now_utc  # noqa: E402
from settings import (DATA, log, setup_logging,  # noqa: E402
                      dashboard_file, topic_data_dir, topic_id)
from pipeline import scorer  # noqa: E402
from pipeline import normalize as flt  # noqa: E402
from report import export_md, export_xlsx, set_tz, write_meta  # noqa: E402

TZ = lambda cfg: timedelta(hours=cfg["timezone_offset_hours"])  # noqa: E731


def local_date_str(cfg) -> str:
    return (now_utc() + TZ(cfg)).strftime("%Y-%m-%d")


def day_dir(cfg) -> Path:
    return topic_data_dir(cfg) / local_date_str(cfg)


def candidates_file(cfg) -> Path:
    return day_dir(cfg) / "full.json"


def run_log(cfg, cmd: str, **kv):
    """运行流水：每次执行追加一行摘要到 data/runs.log（全局，含主题名）。"""
    DATA.mkdir(exist_ok=True)
    stamp = (now_utc() + TZ(cfg)).strftime("%Y-%m-%d %H:%M")
    detail = " ".join(f"{k}={v}" for k, v in kv.items() if v != "")
    with open(DATA / "runs.log", "a", encoding="utf-8") as f:
        f.write(f"[{stamp}] [{topic_id(cfg)}] {cmd} {detail}\n".replace("  ", " "))


def collect(cfg: dict):
    records = []
    channels = []
    collectors_map = [
        ("hn", hn.collect), ("producthunt", producthunt.collect),
        ("apify", apify.collect), ("youtube", youtube.collect),
        ("xhs", xhs.collect),
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


def run_collect(cfg: dict):
    records, channels = collect(cfg)
    # 幂等：当天重复运行时，已有候选不作为重复剔除（增量补新）
    cf = candidates_file(cfg)
    prior_fps: set[str] = set()
    if cf.exists():
        try:
            prior_fps = {r["fingerprint"] for r in json.loads(cf.read_text(encoding="utf-8"))}
        except Exception:  # noqa: BLE001
            prior_fps = set()
    history_fp = flt.load_history(topic_data_dir(cfg) / "history.jsonl")
    kept, stats = flt.apply(records, cfg, history_fp, prior_fps)
    stats["channels"] = "+".join(channels) or "无"
    stats["by_platform"] = {}
    scored = scorer.score(kept, cfg)
    for r in scored:
        stats["by_platform"][r["platform"]] = stats["by_platform"].get(r["platform"], 0) + 1
    flt.update_history(topic_data_dir(cfg) / "history.jsonl", kept, history_fp | prior_fps)
    cf.parent.mkdir(parents=True, exist_ok=True)
    cf.write_text(json.dumps(scored, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("候选 %d 条 → %s | 过滤明细: %s", len(scored), cf, stats)
    run_log(cfg, "collect", candidates=len(scored), channels=stats["channels"])
    print(json.dumps({"ok": True, "candidates": len(scored), "file": str(cf),
                      "stats": stats}, ensure_ascii=False))
    return scored


def load_llm_scores(cfg: dict) -> dict:
    """合并 data/<主题>/当天/llm_scores/*.json（评审员分批写入），按 id 索引。"""
    batch_dir = day_dir(cfg) / "llm_scores"
    scores = {}
    if not batch_dir.exists():
        return scores
    for p in sorted(batch_dir.glob("*.json")):
        try:
            for item in json.loads(p.read_text(encoding="utf-8")):
                if isinstance(item, dict) and item.get("id"):
                    scores[item["id"]] = item
        except Exception as e:  # noqa: BLE001
            log.warning("LLM打分文件 %s 解析失败: %s", p, e)
    return scores


def run_finalize(cfg: dict):
    cf = candidates_file(cfg)
    if not cf.exists():
        print(json.dumps({"ok": False, "error": "请先运行 collect",
                          "missing": str(cf)}, ensure_ascii=False))
        sys.exit(1)
    candidates = json.loads(cf.read_text(encoding="utf-8"))
    llm = load_llm_scores(cfg)
    ranked = scorer.apply_llm_and_rank(candidates, llm, cfg)
    top = ranked[:cfg["top_n"]]
    # 统一字段闭环：把 final_score/why/LLM分 回写候选文件，保证每条记录字段齐全
    cf.write_text(json.dumps(ranked, ensure_ascii=False, indent=1), encoding="utf-8")

    out_dir = day_dir(cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    set_tz(cfg["timezone_offset_hours"])
    channels = _channels_of(cf)

    # 长期记忆 + 话题热度（升温领域识别），供报告/看板/Excel标记
    from heat import update as update_heat
    hot = update_heat(cfg, ranked[:10])

    export_xlsx(top, ranked, out_dir / "榜单.xlsx", cfg, hot=hot)
    export_md(top, out_dir / "日报.md", cfg,
              {"kept": len(ranked), "channels": channels}, local_date_str(cfg), hot=hot)
    write_meta(out_dir / "meta.json", top, {"kept": len(ranked), "channels": channels}, hot=hot)

    # 样本库：可拆解价值Top笔记（品牌内容团队拆解仿写用）
    if cfg.get("llm_quota"):
        samples = sorted([r for r in ranked if r.get("deconstruct") is not None],
                         key=lambda r: (-(r.get("deconstruct") or 0), -r["final_score"]))[:20]
        s_lines = [f"# 爆文样本库 {local_date_str(cfg)}（按可拆解价值 Top {len(samples)}）", ""]
        for i, r in enumerate(samples, 1):
            s_lines += [
                f"## {i}. {r['title']}（拆解价值 {r.get('deconstruct')} | "
                f"{r.get('brand_rel', '-')} | {r.get('note_type', '-')}）",
                f"- 链接：{r['url']} ｜ 互动：{r['engagement_summary']} ｜ 总分：{r['final_score']}",
                f"- 拆解要点：{r.get('why', '')}",
                "",
            ]
        (out_dir / "样本库.md").write_text("\n".join(s_lines), encoding="utf-8")
        log.info("样本库: %d 条 → 样本库.md", len(samples))

    from dashboard import generate as generate_dashboard
    dash_path = generate_dashboard(topic_data_dir(cfg), cfg, out_path=dashboard_file(cfg))

    publish_status = ""
    if cfg.get("publish", {}).get("enabled") and "--no-publish" not in sys.argv:
        from deploy import publish
        publish_status = publish(cfg)
        log.info("GitHub Pages 发布: %s", publish_status)
    llm_note = f"LLM打分覆盖 {len(llm)} 条" if llm else "无LLM打分(纯规则分)"
    log.info("完成: Top%d → %s | %s | 看板: %s", len(top), out_dir, llm_note, dash_path)
    run_log(cfg, "finalize", top=len(top), llm=len(llm), publish=publish_status.split(":")[0])
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


def run_deep(cfg: dict):
    from fetchers.defuddle import enrich_candidates
    n = enrich_candidates(candidates_file(cfg), cfg, only_platform="youtube", top=10)
    run_log(cfg, "deep", enriched=n)
    print(json.dumps({"ok": True, "enriched": n}, ensure_ascii=False))


def run_ids(cfg: dict):
    """输出今日候选 id 清单（供工作流分批打分用）。"""
    cf = candidates_file(cfg)
    try:
        data = json.loads(cf.read_text(encoding="utf-8"))
        print(json.dumps([r["id"] for r in data], ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)


def run_status(cfg: dict):
    cf = candidates_file(cfg)
    n, platforms = 0, {}
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
        "topic": topic_id(cfg),
        "date": local_date_str(cfg),
        "candidates_file": str(cf),
        "candidates": n,
        "by_platform": platforms,
        "llm_scores": len(llm),
        "report_dir": str(day_dir(cfg)),
        "dashboard": str(dashboard_file(cfg)),
    }, ensure_ascii=False))


def main():
    argv = sys.argv[1:]
    topic = "ai-hot"
    if "--topic" in argv:
        i = argv.index("--topic")
        topic = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    cmd = argv[0] if argv else "all"
    setup_logging()
    cfg = load_profile(topic)
    if cmd == "collect":
        run_collect(cfg)
    elif cmd == "deep":
        run_deep(cfg)
    elif cmd == "finalize":
        run_finalize(cfg)
    elif cmd == "all":
        run_collect(cfg)
        run_finalize(cfg)
    elif cmd == "status":
        run_status(cfg)
    elif cmd == "ids":
        run_ids(cfg)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
