# Game Keyword Radar V2 · 2.0.0rc1

本地优先的 **Game Demand Radar + Keyword / Page Opportunity Research Workbench**。

从 Steam / Twitch 发现游戏，以可选 YouTube / Reddit / Trends 信号判断玩家在寻找什么，再生成带证据的 Page Graph，进入人工 Semrush / SERP 验证。日常入口是浏览器，不是命令行。

> **发布状态：Release Candidate。代码与离线回归已完成；真实 Steam + Twitch + YouTube 联合扫描尚未通过当前交付环境验收。** 不要把 Demo 当作实时机会。详见 `docs/V2_ACCEPTANCE.md`。

## 启动

需要 Python 3.11+，推荐 macOS / Linux。本版本的本机互斥锁使用标准库 `fcntl`，Windows 原生 Python 暂不在支持范围。

```bash
cd game-keyword-radar
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
# 仅在尚无本机配置时复制，勿覆盖已经填写的密钥。
test -f .env || cp .env.example .env
test -f radar.toml || cp radar.example.toml radar.toml
game-radar serve
```

浏览器打开 `http://127.0.0.1:3000`。可以先点 **体验示例**，查看游戏详情、五个平台卡片、页面证据、验证队列和历史比较。服务仅绑定回环地址，没有登录系统，不应暴露到公网。

`.env` 支持以下凭据；现有环境变量优先，不把密钥返回给前端、写进报告或 raw evidence。

```dotenv
TWITCH_CLIENT_ID=
TWITCH_CLIENT_SECRET=
YOUTUBE_API_KEY=
```

Steam 无需上述凭据。Twitch / YouTube 未配置时显示 `unavailable`，不阻止其他来源。Trends 默认关闭，需要时安装 `python -m pip install -e '.[trends]'`，再在网页开启。Reddit RSS 是 best-effort，可能返回 403 / 429；程序不会绕过访问限制。

## 浏览器工作流

**扫描 → 今日机会 → 游戏详情 → 问题簇 / Page Graph → 加入验证队列 → 人工填写 Semrush / SERP → Build / Skip。**

首页按游戏研究优先级排序，展示 Demand、来源覆盖率、页面数量与行动建议。详情页明确区分实时观测、历史可比变化、样本下限和缺失值。Page Graph 的每个节点均带 `WHY THIS PAGE EXISTS`，区分真实问题、答案型视频代理与玩法推测。

验证队列存入独立 JSON，不改写扫描快照。进入“待 SERP”需要 Semrush 搜索量、证据与检查时间；真实观察到的 `0` 是合法值。进入“人工验证完成”还需要至少三个不同的已检查自然结果 URL、SERP 笔记、检查时间与明确决策理由。此门禁检查记录完整性，不声称系统自动核实了人工输入。

## 已有站点优先

默认配置将 Workshop / SteamCMD 类问题路由至 WorkshopFetch，游戏计算器 / Tracker / Planner 至 GameKitHQ，明确的 Fortnite Sprite 意图至 FN Sprite Hub。匹配到已有站点仍然需要验证，`EXPAND_EXISTING_SITE` 不代表立即开发。

编辑 `radar.toml` 可调整规则，并通过 `[[entity_overrides]]` 配置别名、已核实的平台 ID、游戏专属 subreddit 和查询词。模糊匹配仅输出建议，不自动合并游戏。

## 请求预算

默认 Broad Discovery 上限 80 个实体，Deep Analysis 10 个、最大 30。非深度候选的缺失深层数据标为“未采集”，不是零需求。

YouTube 默认每次扫描最多 20 次 `search.list`、本机配额日最多 80 次，另有 30 次 `videos.list` 上限。计数单位是 API 调用次数，不硬编码旧的 Google 搜索配额点数规则。缓存命中不再次消耗调用预算；失败请求仍记为尝试。配额日按 America/Los_Angeles 计算。本地计数不包括同一 Google 项目的其他客户端。

Twitch 默认全局与单游戏最多各 3 页。未消费完分页时观众 / 频道数标为**样本下限**，不会冒充游戏全量。单主播占比过高会降低来源分。

## 数据与历史

```text
data/
  raw/<source>/...json       # 上游证据，唯一文件名，不覆盖既有 raw
  cache/<source>/...json     # 公开来源缓存
  private/twitch-token-...  # 仅本机 token，文件权限 0600
  budgets/                  # 请求预算账本
  processed/<run>-snapshot.json
  latest.json               # 上次可用快照；空失败不会覆盖
  latest-live.json
  latest-demo.json
  last-attempt.json          # 最近尝试，可能失败
  entities.json
  history-index.json
  validation/               # 独立人工记录
reports/
  <run>-game-keywords.md
```

V1 / V1.1 快照只读兼容；加载不会迁移或改写文件。V2 的同一 Run ID 不允许覆盖。Demo 不覆盖已有 Live 默认视图。

24h 变化需要目标时间前后 6 小时内的可比观测，7d 需要目标时间前后 24 小时内的可比观测；没有合适样本就不计算。前一次扫描独立标为 `previous`。市场、数据类型和来源采样范围必须一致；相同缓存观测不会产生增长，零基线不会生成无穷增长率。

## 评分边界

Steam 25、Twitch 20、Trends 15、YouTube 15、Reddit 15，跨平台方向确认最多 10。各来源先在自己的量纲内归一化，再加权；缺失 component 为 `null`。Demand 按可用来源权重归一化，同时显示覆盖率。完整公式见 `docs/V2_SCORING.md`。

页面分与 Demand 分分离；页面预验证分最多 69，原始分仅供研究排序。没有 Semrush / SERP，不输出自动 Build。视频播放数、直播观众数、Trends 指数不换算成 Google 月搜索量。分数不是成功率。

## CLI 与测试

```bash
game-radar sources                         # 仅配置就绪状态，不是联网通过证明
game-radar scan --discovery-limit 80 --deep 10
game-radar scan --limit 10                 # V1 参数保留，limit 最大 30
game-radar demo
game-radar report
game-radar validate                        # 查看人工队列
game-radar compare CURRENT_RUN BASELINE_RUN
python -m pytest
```

新增测试默认断开网络，用 MockTransport、ASGI TestClient 和合成快照验证。`tests/test_v1_contracts.py` 覆盖现有 V1 接口约定，不删除原仓库测试。附带浏览器检查为真实 Chromium DOM/JS + ASGI 桥接，**不是浏览器直接联网验收**；见验收记录。

真实验收必须另外运行：

```bash
python scripts/live_acceptance.py
```

只有实际获取到 Steam、Twitch、YouTube 三种可用观测，脚本才退出 0。缺凭据、网络失败或只有示例数据都不算通过。

## 职责边界

本项目不生成小黑盒文章、公众号文章、新闻标题或社媒内容；这些属于独立 `game-content-radar`。不依赖该仓库。不自动建站、购买 API、抓取大规模 SERP，也不引入云数据库或用户系统。

## 官方接口参考

- Twitch Helix / OAuth: https://dev.twitch.tv/docs/api/reference/ 、https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/
- YouTube search / videos: https://developers.google.com/youtube/v3/docs/search/list 、https://developers.google.com/youtube/v3/docs/videos/list
- Google Trends Alpha: https://developers.google.com/search/apis/trends

OfficialTrendsProvider 仅提供授权适配器注入接口；没有官方 Alpha 权限和适配器时明确返回 unavailable，不伪造公共接口。
