"""自包含 HTML 日报看板：暗色卡片风、日期切换、近14天趋势、平台环形图、Top分数柱状图。

零外部依赖（无CDN/无JS库），双击本地打开即可。数据源：data/*/meta.json（富字段）。
产出固定路径 dashboard/index.html（deploy.py 再复制到 docs/ 发布）。
"""
import html
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pipeline.classify import CTYPE_COLORS
from settings import DASHBOARD

PLATFORM_COLORS = {
    "Hacker News": "#ff6600", "Reddit": "#ff4500", "X/Twitter": "#1d9bf0",
    "TikTok": "#ee1d52", "YouTube": "#ff0033", "Product Hunt": "#da552f",
}
PLATFORM_SHORT = {"Hacker News": "HN", "Reddit": "RD", "X/Twitter": "X",
                  "TikTok": "TT", "YouTube": "YT", "Product Hunt": "PH"}
SCORE_COLORS = [(85, "#34d399"), (70, "#a3e635"), (55, "#fbbf24"), (0, "#f87171")]


def _esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def _score_color(v: float) -> str:
    for floor, color in SCORE_COLORS:
        if v >= floor:
            return color
    return SCORE_COLORS[-1][1]


def _score_block(v: float) -> str:
    return (f'<div class="score" style="color:{_score_color(v)};border-color:{_score_color(v)}55">'
            f'<b>{v:.1f}</b><span>总分</span></div>')


def _badge(platform_name: str) -> str:
    c = PLATFORM_COLORS.get(platform_name, "#8b93a7")
    return (f'<span class="badge" style="color:{c};border-color:{c}66;'
            f'background:{c}14">{_esc(platform_name)}</span>')


def _bars(r: dict) -> str:
    rows = [("热度", r.get("s_engagement")), ("速度", r.get("s_velocity")),
            ("相关", r.get("s_relevance")), ("时效", r.get("s_recency"))]
    out = ['<div class="bars">']
    for name, v in rows:
        v = float(v or 0)
        out.append(f'<div class="bar"><em>{name}</em><div class="track">'
                   f'<i style="width:{v:.0f}%;background:{_score_color(v)}"></i></div>'
                   f'<b>{v:.0f}</b></div>')
    out.append("</div>")
    chips = []
    if r.get("llm_relevance") is not None:
        chips.append(f'<span class="chip">AI相关 {_esc(r["llm_relevance"])}/10</span>')
    if r.get("llm_value") is not None:
        chips.append(f'<span class="chip">内容价值 {_esc(r["llm_value"])}/10</span>')
    for p in r.get("same_story_platforms") or []:
        chips.append(f'<span class="chip warn">同题热传·{_esc(p)}</span>')
    if chips:
        out.append(f'<div class="chips">{"".join(chips)}</div>')
    return "".join(out)


def _item_card(r: dict) -> str:
    rank = int(r.get("rank") or 0)
    rank_html = ("🥇🥈🥉"[rank - 1] if 1 <= rank <= 3 else f"<span>#{rank}</span>")
    title = _esc(r.get("title", ""))
    why = r.get("why") or "—"
    ctype = r.get("ctype") or ""
    ctype_chip = ""
    if ctype:
        c = CTYPE_COLORS.get(ctype, "#8b93a7")
        ctype_chip = (f'<span class="ctype" style="color:{c};border-color:{c}66;'
                      f'background:{c}14">{_esc(ctype)}</span>')
    return f"""
    <article class="item">
      <div class="rankmedal rank{min(rank,4)}">{rank_html}</div>
      {_score_block(float(r.get('final_score') or 0))}
      <div class="body">
        <div class="meta">{_badge(r.get('platform_name', r.get('platform', '?')))}{ctype_chip}
          <span class="eng">{_esc(r.get('engagement_summary') or '-')}</span>
          <span class="time">{_esc(r.get('published_local') or '')} · {_esc(r.get('hours_display') or '')}前</span>
          {_esc(r.get('author') or '') and f'<span class="author">@{_esc(r.get("author"))}</span>'}
        </div>
        <a class="title" href="{_esc(r.get('url') or '#')}" target="_blank" rel="noopener">{title}</a>
        <div class="why">{_esc(why)}</div>
        {_bars(r)}
      </div>
    </article>"""


def _donut(items: list[dict]) -> str:
    counts = {}
    for r in items:
        p = r.get("platform_name") or r.get("platform") or "?"
        counts[p] = counts.get(p, 0) + 1
    total = sum(counts.values()) or 1
    segs, cum, legend = [], 0.0, []
    for p, n in sorted(counts.items(), key=lambda x: -x[1]):
        color = PLATFORM_COLORS.get(p, "#8b93a7")
        pct = 100.0 * n / total
        segs.append(f"{color} {cum:.2f}% {cum + pct:.2f}%")
        cum += pct
        legend.append(f'<div><i style="background:{color}"></i>'
                      f'{_esc(PLATFORM_SHORT.get(p, p))} ×{n}（{pct:.0f}%）</div>')
    return (f'<div class="panel"><div class="ptitle">本次爆款平台分布</div>'
            f'<div class="donutwrap"><div class="donut" style="background:conic-gradient('
            f'{", ".join(segs)})"><div class="hole"><b>{total}</b><span>Top {total}</span></div></div>'
            f'<div class="legend">{"".join(legend)}</div></div></div>')


def _hbars(items: list[dict]) -> str:
    bars = []
    for r in items[:10]:
        color = PLATFORM_COLORS.get(r.get("platform_name") or "", "#7aa2ff")
        short = PLATFORM_SHORT.get(r.get("platform_name") or "", "?")
        score = float(r.get("final_score") or 0)
        bars.append(f'<div class="hbar"><em>#{r.get("rank")} {short}</em>'
                    f'<div class="track"><i style="width:{score:.1f}%;background:{color}"></i></div>'
                    f'<b>{score:.1f}</b></div>')
    return (f'<div class="panel"><div class="ptitle">Top 综合分排行（颜色=平台）</div>'
            f'<div class="hbars">{"".join(bars)}</div></div>')


def _charts(items: list[dict]) -> str:
    return f'<div class="charts">{_donut(items)}{_hbars(items)}</div>'


def _kpi(label: str, value: str, accent: str = "#7aa2ff") -> str:
    return (f'<div class="kpi"><b style="color:{accent}">{_esc(value)}</b>'
            f'<span>{_esc(label)}</span></div>')


def _trend(days: list[dict]) -> str:
    counts = [len(d["items"]) for d in days][::-1]
    dates = [d["date"][5:] for d in days][::-1]
    peak = max(counts) or 1
    bars = []
    for date, n in zip(dates, counts):
        h = max(6, int(56 * n / peak))
        bars.append(f'<div class="tcol" title="{_esc(date)}: {n}条">'
                    f'<i style="height:{h}px"></i><em>{n}</em><span>{_esc(date)}</span></div>')
    return (f'<div class="trend"><div class="tlabel">每日候选量（近{len(days)}天）'
            f'</div><div class="tchart">{"".join(bars)}</div></div>')


def _day_section(idx: int, d: dict) -> str:
    items = d["items"]
    stats = d.get("stats") or {}
    plats = {}
    for r in items:
        p = r.get("platform_name") or r.get("platform") or "?"
        plats[p] = plats.get(p, 0) + 1
    dist = " · ".join(f"{_esc(k)}×{v}" for k, v in sorted(plats.items(), key=lambda x: -x[1]))
    llm_n = sum(1 for r in items if r.get("llm_relevance") is not None)
    top_score = max((float(r.get("final_score") or 0) for r in items), default=0)
    kpis = (
        _kpi("精选条数", str(len(items)))
        + _kpi("最高分", f"{top_score:.1f}", _score_color(top_score))
        + _kpi("来源分布", dist or "-", "#9ee7ff")
        + _kpi("LLM评审覆盖", f"{llm_n}/{len(items)}", "#c4b5fd")
        + _kpi("采集通道", _esc(stats.get("channels") or "-"), "#fda4af")
    )
    cards = "".join(_item_card(r) for r in items)
    return (f'<section class="day d{idx}">'
            f'<div class="kpis">{kpis}</div>{_charts(items)}<div class="cards">{cards}</div></section>')


_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;min-height:100vh;
  background:linear-gradient(160deg,#0b1020 0%,#101a33 55%,#0d1226 100%);color:#e6ebf8}
.wrap{max-width:1120px;margin:0 auto;padding:28px 20px 60px}
header{margin-bottom:18px}
.logo{font-size:30px;font-weight:800;background:linear-gradient(90deg,#ffd166,#ff6b6b 40%,#7aa2ff);
  -webkit-background-clip:text;background-clip:text;color:transparent;display:inline-block}
.sub{color:#8b93a7;font-size:13px;margin-top:4px}
.trend{margin-top:16px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.07);
  border-radius:14px;padding:12px 16px}
.tlabel{font-size:12px;color:#8b93a7;margin-bottom:8px}
.tchart{display:flex;gap:10px;align-items:flex-end;min-height:96px}
.tcol{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;max-width:80px}
.tcol i{width:70%;max-width:46px;border-radius:6px 6px 2px 2px;
  background:linear-gradient(180deg,#7aa2ff,#4c6ef5);min-height:4px}
.tcol em{font-style:normal;font-size:11px;color:#c7d0e8;margin-top:4px}
.tcol span{font-size:10px;color:#5d6580;margin-top:1px}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0 14px}
.tabs label{cursor:pointer;padding:7px 16px;border-radius:999px;font-size:13px;color:#aeb8d0;
  background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.09);transition:.15s}
.tabs label:hover{color:#fff;border-color:#7aa2ff66}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:16px}
.kpi{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07);border-radius:12px;
  padding:12px 14px;display:flex;flex-direction:column;gap:2px}
.kpi b{font-size:17px}
.kpi span{font-size:11.5px;color:#8b93a7;line-height:1.5;word-break:break-all}
.day{display:none}
.cards{display:flex;flex-direction:column;gap:10px}
.item{display:flex;gap:14px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.07);
  border-radius:14px;padding:14px 16px;transition:.15s}
.item:hover{transform:translateY(-1px);border-color:rgba(122,162,255,.35);background:rgba(255,255,255,.05)}
.rankmedal{font-size:22px;width:44px;display:flex;align-items:center;justify-content:center;flex-shrink:0;
  color:#5d6580;font-weight:800}
.score{flex-shrink:0;width:64px;height:64px;border-radius:14px;border:1.5px solid;
  display:flex;flex-direction:column;align-items:center;justify-content:center;background:rgba(0,0,0,.25)}
.score b{font-size:19px;line-height:1.1}
.score span{font-size:10px;color:#8b93a7}
.body{flex:1;min-width:0}
.meta{display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:12px;color:#8b93a7;margin-bottom:6px}
.badge{padding:2px 9px;border-radius:999px;border:1px solid;font-size:11.5px;font-weight:600}
.ctype{padding:2px 9px;border-radius:999px;border:1px solid;font-size:11.5px;font-weight:600}
.charts{display:grid;grid-template-columns:320px 1fr;gap:12px;margin-bottom:14px}
.panel{background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.07);border-radius:14px;padding:14px 16px}
.ptitle{font-size:12px;color:#8b93a7;margin-bottom:12px}
.donutwrap{display:flex;align-items:center;gap:18px}
.donut{width:150px;height:150px;border-radius:50%;position:relative;flex-shrink:0}
.hole{position:absolute;inset:33px;background:#141d36;border-radius:50%;display:flex;flex-direction:column;align-items:center;justify-content:center}
.hole b{font-size:20px}.hole span{font-size:10px;color:#8b93a7}
.legend{display:flex;flex-direction:column;gap:7px;font-size:12px;color:#c7d0e8}
.legend i{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:7px}
.hbars{display:flex;flex-direction:column;gap:7px}
.hbar{display:flex;align-items:center;gap:10px;font-size:11.5px}
.hbar em{font-style:normal;width:48px;color:#8b93a7;flex-shrink:0}
.hbar .track{flex:1;height:14px;border-radius:4px;background:rgba(255,255,255,.06);overflow:hidden}
.hbar .track i{display:block;height:100%;border-radius:4px}
.hbar b{width:40px;text-align:right;color:#e6ebf8;font-weight:700}
@media(max-width:760px){.charts{grid-template-columns:1fr}.donutwrap{justify-content:flex-start}}
.eng{color:#c7d0e8}
.author{color:#6d7690}
.title{display:block;color:#f2f5ff;font-size:15.5px;font-weight:650;line-height:1.45;
  text-decoration:none;margin-bottom:6px;overflow-wrap:anywhere}
.title:hover{color:#9cc0ff}
.why{font-size:13px;color:#b9c2da;background:rgba(122,162,255,.07);border-left:3px solid #7aa2ff66;
  padding:7px 10px;border-radius:0 8px 8px 0;margin-bottom:9px;line-height:1.6;overflow-wrap:anywhere}
.bars{display:grid;grid-template-columns:1fr 1fr;gap:5px 18px;max-width:560px}
.bar{display:flex;align-items:center;gap:8px;font-size:11px;color:#8b93a7}
.bar em{font-style:normal;width:26px;flex-shrink:0}
.bar .track{flex:1;height:5px;border-radius:3px;background:rgba(255,255,255,.08);overflow:hidden}
.bar .track i{display:block;height:100%;border-radius:3px}
.bar b{width:24px;text-align:right;color:#c7d0e8;font-weight:600}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.chip{font-size:11px;color:#c4b5fd;background:rgba(196,181,253,.1);border:1px solid rgba(196,181,253,.25);
  padding:2px 8px;border-radius:999px}
.chip.warn{color:#fbbf24;background:rgba(251,191,36,.08);border-color:rgba(251,191,36,.3)}
footer{margin-top:26px;color:#5d6580;font-size:12px;line-height:1.8}
footer a{color:#7aa2ff;text-decoration:none}
"""


def generate(data_dir: Path, cfg: dict) -> Path:
    days = []
    for meta_path in sorted(data_dir.glob("*/meta.json"), reverse=True):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            items = meta.get("items") or []
            date = meta_path.parent.name
            if not items or len(date) != 10:
                continue
            days.append({"date": date, "items": items, "stats": meta.get("stats") or {},
                         "generated_at": meta.get("generated_at", "")})
        except Exception:  # noqa: BLE001 - 单天坏数据不影响整体看板
            continue
    if not days:
        return DASHBOARD
    days = days[:14]

    tabs, sections = [], []
    for i, d in enumerate(days):
        checked = " checked" if i == 0 else ""
        tabs.append(f'<input type="radio" name="day" id="t{i}" class="tabhit"{checked}>'
                    f'<label for="t{i}">{_esc(d["date"])}{"（最新）" if i == 0 else ""}</label>')
        sections.append(_day_section(i, d))
    # CSS 兄弟选择器：tab i 选中时显示对应 section（input/label/main 同为 .wrap 直接子元素）
    tab_css = "".join(
        f'#t{i}:checked ~ main .d{i}{{display:block}}#t{i}:checked ~ label[for="t{i}"]'
        f'{{color:#0b1020;background:linear-gradient(90deg,#ffd166,#ffb86b);border-color:transparent;font-weight:700}}'
        for i in range(len(days)))

    latest = days[0]
    gen = latest.get("generated_at") or ""
    try:
        gen_str = (datetime.fromisoformat(gen)
                   + timedelta(hours=cfg["timezone_offset_hours"])).strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        gen_str = "-"
    foot = (f'数据截至 <b>{_esc(latest["date"])}</b> {len(days)} 天历史 · 生成于 {_esc(gen_str)} · '
            f'每 finalize 自动更新本页 · 通道与排障见 README.md<br>'
            f'通道：HN/PH 免key直连 · Reddit/X/TikTok 经 Apify · YouTube 经代理+yt-dlp · '
            f'打分=热度40%+速度25%+AI相关25%+价值10%')

    doc = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI 爆款日报看板</title><style>{tab_css}{_CSS}</style></head>
<body><div class="wrap">
<header><div class="logo">🔥 AI 爆款看板</div>
<div class="sub">海外社媒 AI 内容热度追踪 · 每日 12:00 自动抓取打分更新</div></header>
{_trend(days)}
{''.join(tabs)}
<main>{''.join(sections)}</main>
<footer>{foot}</footer>
</div></body></html>"""
    DASHBOARD.parent.mkdir(exist_ok=True)
    DASHBOARD.write_text(doc, encoding="utf-8")
    return DASHBOARD
