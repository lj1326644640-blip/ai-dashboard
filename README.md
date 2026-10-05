# AI 爆款日报工作流

海外社媒（HN / Product Hunt / Reddit / X / TikTok / YouTube）AI 爆款内容
**每日 12:00 自动抓取 → 打分 → 看板 → 上线分享**。

- 公开看板: https://lj1326644640-blip.github.io/ai-dashboard/
- 打分细节: [打分机制.md](打分机制.md) · LLM评审规则: [docs/llm_rubric.md](docs/llm_rubric.md)

## 工作流梳理：流程 / 资产 / 数据

### 1. 流程（怎么跑）

**主运行流程**（每天 12:00 由 ZCode 定时任务触发 saved workflow `ai-viral-daily`；本机入口 `task.cmd` 兜底）：

```
采集 fetchers → 过滤去重 normalize → 规则打分+分类 scorer → LLM评审(分批)
   → 报告 report(Excel/MD) → 看板 dashboard → 发布 deploy(GitHub Pages) → 自动打开看板
```

- 手动全流程: `python src/main.py all`（无LLM步的兜底版）
- 手动补报当天: `python src/main.py collect && python src/main.py finalize`
- 凭据体检: `python src/check_secrets.py`

**固定脚本**（一次写好、每天复用）：

| 脚本 | 职责 |
|---|---|
| `src/main.py` | 主管线入口：collect / ids / deep / finalize / status / all |
| `src/fetchers/hn.py` | Hacker News（Algolia API 主 + hnrss.org RSS 兜底）|
| `src/fetchers/producthunt.py` | Product Hunt 官方 Atom feed |
| `src/fetchers/apify.py` | Reddit / X / TikTok（Apify 服务端抓取）|
| `src/fetchers/youtube.py` | YouTube（代理探测 + yt-dlp 搜索）|
| `src/fetchers/defuddle.py` | 视频正文/字幕深挖（Node defuddle）|
| `src/pipeline/normalize.py` | 72h窗口 + 跨天去重 + 关键词过滤 + 同题合并 |
| `src/pipeline/classify.py` | 内容类型分类（工具/资讯/观点/争议）|
| `src/pipeline/scorer.py` | 基准分规则打分 + LLM分合并 + 加权合成 |
| `src/report.py` | Excel榜单 + Markdown日报 + meta.json |
| `src/dashboard.py` | 看板 HTML 生成（环形图/柱状图/日期切换）|
| `src/deploy.py` | GitHub Pages 发布（commit + push，重试3次）|
| `src/check_secrets.py` | 凭据体检（token/代理端口）|

### 2. 资产（配置与看板）

| 资产 | 说明 |
|---|---|
| `config.json` | 全局配置：平台开关、关键词表、打分权重、基准线 `scoring_refs`、发布开关 |
| `secrets.json` | 🔐 凭据（Apify token、代理端口）——**仅本机，永不入库** |
| `dashboard/index.html` | 看板正式产出（每次 finalize 更新；deploy 复制到 docs/ 发布）|
| `.zcode/workflows/ai-viral-daily.dwf.ts` | 保存的动态工作流定义（LLM评审编排）|
| ZCode 定时任务 `automation-fd7cc40a` | 每天 12:00 触发（cron `0 12 * * *`）|

### 3. 数据（按日归档）

```
data\
├── 2026-10-05\            # 按日归档
│   ├── full.json          # 全量候选（23个统一字段，含LLM分回写）
│   ├── llm_scores\        # 评审员分批打分（中间数据，不入库）
│   ├── 日报.md             # 人读日报（升温领域+Top20+为什么火）
│   └── 榜单.xlsx           # 打分明细表（Top20+全部候选+升温领域 三个sheet）
├── longterm_memory.jsonl  # 长期记忆表：历史+原始数据聚合（每行一条内容+话题标签）
├── topic_heat.json        # 热度表：每话题每日条数/均分/最高分/首次出现/升温状态
├── history.jsonl          # 跨天去重指纹库（不入库）
└── runs.log               # 运行流水（每次执行一行摘要）
logs\collect.log           # 详细日志
docs\index.html            # GitHub Pages 发布副本
```

**升温领域识别**（每次 finalize 自动执行，`src/heat.py`）：
- 聚合历史+当天数据 → `longterm_memory.jsonl` 长期记忆表（幂等重建）
- 按话题（config.json `topic_lexicon` 词表 + 标题专名兜底）维护热度表 `topic_heat.json`
- 判定升温：今日条数或均分 ≥ 近7天均值2倍且今日≥3条；或话题首次出现当天就进Top10
- 标记到：看板"升温领域"面板、日报章节、Excel"升温领域"sheet
- 判定规则单测：`python tests/test_heat.py`（7项）

## 目录总览

```
task.cmd                  # Windows 本机入口（备用，可挂系统任务计划程序）
config.json               # 全局配置(渠道/关键词/打分权重/发布)
secrets.json              # 🔐 凭据(仅本机，不入库)
requirements.txt          # Python 依赖
README.md                 # 本文件（使用说明+运维手册）
打分机制.md                # 打分机制详解
.gitignore
src\
  main.py                 # 主管线：采集→过滤去重→打分→报告→看板→发布
  settings.py             # 配置加载(合并 secrets.json) + 日志 + 全局路径
  http_util.py            # 代理感知请求 + 自动重试 + 代理探测
  schema.py               # 统一记录schema：日期/互动合成/指纹/同题判定
  report.py               # Excel/MD 报告生成 + meta.json
  deploy.py               # GitHub Pages 发布
  dashboard.py            # 看板HTML生成(环形图/柱状图/趋势)
  check_secrets.py        # 凭据体检
  fetchers\               # 抓取
    hn.py                 #   Hacker News(Algolia主+RSS兜底)
    producthunt.py        #   Product Hunt 官方feed
    apify.py              #   Reddit/X/TikTok (Apify REST)
    youtube.py            #   YouTube(代理+yt-dlp)
    defuddle.py           #   视频正文/字幕提取
  pipeline\
    normalize.py          #   关键词过滤+跨天去重+同题合并
    classify.py           #   内容类型分类(工具/资讯/观点/争议)
    scorer.py             #   基准分规则 + LLM分 + 加权合成
    topics.py             #   话题识别(词表+专名兜底)
  heat.py                 # 长期记忆聚合 + 热度表 + 升温领域判定
dashboard\
  index.html              # 在线/本地看板
docs\
  index.html              # Pages 发布副本（deploy.py 生成）
  llm_rubric.md           # LLM评审规则
data\                     # 按日归档（见上）
tests\acceptance_check.py # 验收测试（python tests/acceptance_check.py）
```

## 运维手册（故障速查表）

| 症状 | 原因 | 处理 |
|---|---|---|
| Reddit/X/TikTok 无产出 | Apify token 失效或免费额度($5/月)耗尽 | `python src/check_secrets.py` 查token；额度月底重置或升 Starter |
| X 只有10条 | Apify免费档限5次/月×10条 | 预期内；要上量需 Starter $19/月 |
| YouTube 无产出 | 本机无可用代理 | 开 Clash；或把端口填入 secrets.json 的 `proxy.port` |
| 推送失败 push fail | github.com 间歇被阻断 | publish 已自动重试3次；失败的commit留本地，下次运行自动补推 |
| 当天没生成日报 | 12点时电脑关机/容器未运行 | 开机后 `python src/main.py all` 补跑（去重保证不重复推送）|
| LLM打分缺失 | 评审步骤未跑 | finalize 会自动降级为纯规则分；手动补：按 docs/llm_rubric.md 打分写入 data/当天/llm_scores/ |
| 看板分数和昨天比变化大 | 打分是绝对基准分，与当日样本无关 | 检查 scoring_refs 是否被改动；对照 打分机制.md |
| hnrss 慢/502 | 主通道是 Algolia，hnrss 仅兜底 | 无需处理；确认 logs/collect.log 里 Algolia 正常 |

## 首次部署备忘（已完成的配置）

1. Apify token → `secrets.json`（已配，账号 sumptuous_xylol）
2. GitHub 仓库 `lj1326644640-blip/ai-dashboard`（Public）+ Pages（main 分支 /docs 目录）
3. git 推送凭据：GCM 存的 lj1326644640-blip token；github.com 走代理或直连重试
4. ZCode 定时任务 + saved workflow `ai-viral-daily`
