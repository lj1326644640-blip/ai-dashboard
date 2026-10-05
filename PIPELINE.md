# AI 爆款内容每日抓取管线 — 执行手册

每天中午 12:00 由 ZCode 定时任务自动执行。本文档是人工执行/排障手册，
也是定时任务在无法启动工作流时的兜底执行依据。

## 一、每日执行流程（三步）

工作目录：`D:\自动信息流agent`

### 第 1 步：采集
```bash
python run_daily.py collect
```
- 自动运行所有已启用通道：HN Algolia、Product Hunt feed、Apify(Reddit/X/TikTok，需token)、YouTube(需代理)
- 自动做：72小时窗口过滤 → 跨天去重(history.jsonl) → AI关键词粗筛 → 平台内Top50 → 规则打分
- 产出：`data/candidates_YYYY-MM-DD.json`
- 某个通道失败不影响其他通道； Apify/YouTube 未配置时打日志跳过

### 第 2 步：LLM 打分（由 AI 代理执行）
1. 读 `pipeline/llm_rubric.md`（打分规则和输出格式）
2. 读 `data/candidates_YYYY-MM-DD.json`，按 rubric 逐条打分
3. 结果写入 `data/llm_scores_YYYY-MM-DD.json`（JSON数组，含 id/ai_relevance/value/why）
   - 分批打分时可写入 `data/llm_scores/batch_1.json`、`batch_2.json`…，finalize 自动合并
4. **没做这一步也能出报告**（纯规则分排序），但"为什么火"是模板文案，质量低

### 第 3 步：导出
```bash
python run_daily.py finalize
```
- 合并 LLM 打分 → 最终总分排序 → Top 20
- 产出：`reports/YYYY-MM-DD/榜单.xlsx` + `reports/YYYY-MM-DD/日报.md` + `meta.json`
- **看板**：`reports/dashboard.html`（固定路径，每次 finalize 自动更新；暗色卡片风，
  最新Top20 + 历史日期切换 + 近14天候选量趋势，零依赖双击即开）
- 默认 finalize 后自动在浏览器打开看板（config.json `auto_open_dashboard: false` 可关）；
  脚本/无人值守场景加 `--no-open` 参数跳过

一键（跳过LLM步）：`python run_daily.py all`

查状态：`python run_daily.py status`（输出JSON：候选数、平台分布、LLM覆盖数）

## 二、配置项（config.json）

| 项 | 说明 |
|---|---|
| `apify.token` | Apify Personal API Token（console.apify.com → Settings → API）|
| `proxy.port` | 本地代理端口（null=自动探测常见端口 7890/1080 等）|
| `keywords` | AI 关键词表（硬过滤用，命中至少1个才保留）|
| `queries.*` | 各平台搜索词 |
| `platforms.*` | 平台开关（false 可停用某通道）|
| `window_hours` | 时间窗口，默认72小时 |
| `top_n` | 日报条数，默认20 |

改完配置立即生效，无需重启。

## 三、通道说明与排障

| 通道 | 依赖 | 常见问题 |
|---|---|---|
| Hacker News | 无（Algolia API 直连）| hnrss.org 慢属正常，主通道是 Algolia |
| Product Hunt | 无（官方 /feed）| feed 无投票数，PH条目靠LLM分补偿排名 |
| Reddit/X/TikTok | Apify token | token过期/额度用尽 → 日志 collect.log 有明确报错；X actor 偶发不稳定，重跑一次即可 |
| YouTube | 本地代理 + yt-dlp | 无代理自动跳过；`data/proxy_state.json` 缓存探测结果12小时，换端口可删掉重探 |
| 内容深挖(defuddle) | Node + npx + 代理 | 仅深挖YouTube头部视频的字幕/描述，失败不影响主流程 |

手动重探代理：删 `data/proxy_state.json` 后重跑。
日志：`logs/collect.log`。

## 四、补跑

定时任务在当天 12:00 未运行（关机等），开机后手动执行：
```bash
python run_daily.py all
```
跨天去重保证不会重复推送前几天的内容。

## 五、成本参考

- HN / Product Hunt / 兜底搜索：免费
- Apify 免费额度 $5/月：够小流量试跑（X actor 免费档限5次/月×10条，基本不可用）
- 三平台各 ~200条/天：约 $19–33/月（推荐 Starter 档 + 便宜 actor 组合，见 config.json 里的 actor 名）
