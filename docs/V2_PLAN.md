# Game Keyword Radar V2 改造方案

> 仓库：`ai-ashao/game-keyword-radar`
>
> 定位：**Game Demand Radar + Keyword/Page Opportunity Research Workbench**
>
> 本文用于指导 V2 改造。现有 V1/V1.1 不推倒重写，优先复用 Steam 扫描、本地 Dashboard、历史快照、关键词规则、Google Trends 可选能力、CLI 与 Codex Skill。

---

## 1. 改造背景

当前 `game-keyword-radar` 已经具备：

- Steam 候选游戏扫描；
- Steam 游戏详情、当前玩家、评论规模等基础信号；
- 规则化关键词候选；
- 关键词机会评分与证据完整度；
- 本地 Dashboard；
- 历史快照与双快照变化对比；
- 可选 Google Trends；
- Markdown 报告；
- `game-keyword-scan` Codex Skill。

当前 V1 的核心逻辑仍然偏：

```text
Steam 发现游戏
→ 理解玩法
→ 根据玩法模板生成关键词
→ 评分
→ 等待 SERP 验证
```

V2 需要升级为：

```text
多平台发现游戏正在起量
→ 判断热度是否为真实需求而非单平台噪声
→ 挖玩家正在主动寻找的问题/答案
→ 生成 Page Graph
→ 输出建站/扩页机会
→ 进入 Semrush + SERP 验证
```

核心变化不是“多加几个数据源”，而是把产品从 **Steam Keyword Generator** 升级成 **跨平台 Game Demand Radar**。

---

# 2. 职责边界冻结

## 2.1 `game-keyword-radar` 只负责什么

回答一个核心问题：

> **现在有哪些游戏正在形成可被搜索承接的需求，值得进一步做站或做页面？**

它负责：

- 游戏发现；
- 游戏热度变化；
- 跨平台 Demand Signal；
- 玩家问题挖掘；
- 关键词假设；
- Page Graph；
- Preliminary Opportunity Score；
- Semrush / SERP Validation Queue；
- Existing Site vs New Site 初步路由。

## 2.2 明确不负责

以下全部移出本项目职责：

- 小黑盒每天发什么；
- 小黑盒标题；
- 小黑盒文章生成；
- 内容运营 Reach / Value Pick；
- 游戏新闻编辑；
- 自动社媒发帖；
- 自动写公众号/视频脚本。

这些属于独立的 `game-content-radar`。

## 2.3 两项目之间的关系

两边不共享业务代码，不相互硬依赖。

只允许未来通过标准 Signal JSON 做松耦合交换，例如：

```json
{
  "game_name": "Example Game",
  "signal_type": "community_spike",
  "source": "xiaoheihe",
  "observed_at": "2026-09-11T08:00:00Z"
}
```

`game-keyword-radar` 可把这种外部 Signal 当辅助输入，但不是必需来源。

---

# 3. V2 产品目标

V2 每次扫描必须回答 4 个问题：

## Q1：哪些游戏正在起量？

输出：

```text
Top Game Opportunities
```

## Q2：热度是不是跨平台成立？

至少判断：

```text
Steam
Twitch
Google Trends
YouTube
Reddit
```

不要求每个游戏五源齐全，但必须明确哪些来源有数据、哪些缺失。

## Q3：玩家正在找什么？

输出：

```text
Question Clusters
Keyword Hypotheses
Page Opportunities
```

## Q4：下一步做什么？

输出明确 Action：

```text
WATCH
VALIDATE
EXPAND_EXISTING_SITE
VALIDATE_NEW_SITE
SKIP
```

注意：

`VALIDATE_NEW_SITE` ≠ 立即建站。

仍需：

```text
Semrush
→ Google SERP
→ Build / Skip
```

---

# 4. 数据源架构

V2 数据源分为三层。

## Tier 1：核心 Demand Sources

### 4.1 Steam

继续作为游戏实体和玩家规模的基础来源。

保留现有：

- Top Sellers；
- Popular New Releases；
- App Detail；
- Release Date；
- Review Count；
- Genres / Categories；
- Current Players。

V2 增强：

- 每次扫描保存 Current Players；
- 基于历史快照计算：
  - 24h 变化；
  - 7d 变化；
  - 相对扫描变化；
- 区分：
  - 绝对规模；
  - 增长速度；
  - 新发售期爆发；
  - 老游戏复苏。

Steam 不单独决定“值得建站”，它只是需求证据的一部分。

---

### 4.2 Twitch

V2 新增核心来源。

使用 Twitch 官方 Helix API。

推荐技术路径：

```text
OAuth App Access Token
→ GET /helix/streams
→ 按 game_id 聚合
→ GET /helix/games 补全游戏实体
```

官方 `Get Streams` 返回实时直播流，并按观看人数降序，可获取：

- `game_id`
- `game_name`
- `viewer_count`
- `language`
- `started_at`
- channel/stream 信息

V2 不关心单个主播，而是按游戏聚合。

每个游戏计算：

```text
total_viewers
live_channels
avg_viewers_per_channel
top_stream_viewers
twitch_rank
```

历史快照后计算：

```text
viewer_growth_24h
viewer_growth_7d
rank_change
channel_growth
```

### Twitch Signal 的意义

重点判断：

> 这个游戏是否正在获得“观看与讨论注意力”。

示例：

```text
7d 前 4,300 viewers
今天 38,000 viewers
Rank #42 → #9
```

属于强 Demand Momentum Signal。

### 配置

环境变量：

```text
TWITCH_CLIENT_ID
TWITCH_CLIENT_SECRET
```

Token 自动缓存并在过期时刷新。

Twitch 失败不得阻塞主扫描。

---

### 4.3 Google Trends

现有 Trends 能力保留，但 Provider 抽象需要升级。

截至 V2 设计时，Google 已提供 **Google Trends API Alpha**，但仍属于受限 Alpha，并非所有账号都默认可用。

因此设计两个 Provider：

```text
OfficialTrendsProvider   # 有 Alpha 权限时优先
LegacyTrendsProvider     # 现有非官方方案，best-effort
```

统一接口：

```python
class TrendsProvider:
    def fetch(self, terms, geo, timeframe) -> TrendsSignal:
        ...
```

不得让 Trends 成为硬依赖。

建议检查：

```text
<Game Name>
<Game Name> codes
<Game Name> wiki
<Game Name> tier list
<Game Name> map
```

但附加词只在玩法适配时查询，避免无意义请求。

核心指标：

```text
trend_direction
recent_vs_baseline
peak_ratio
geo_strength
related_query_signals
```

Trends 缺失必须标记：

```text
insufficient_data
```

而不是 0 分需求。

---

### 4.4 YouTube

V2 新增核心需求验证源。

使用 YouTube Data API v3。

推荐流程：

```text
search.list
→ 得到近期相关视频 IDs
→ videos.list
→ 获取统计字段
→ 聚合为游戏内容需求信号
```

查询范围不是泛搜一个游戏名后直接看总结果数，而是有意图区分：

```text
<Game Name>
<Game Name> guide
<Game Name> beginner guide
<Game Name> best build
<Game Name> codes
<Game Name> tier list
<Game Name> map
<Game Name> how to
```

同样只对适配玩法的模板查询。

建议采集最近：

```text
7 days
30 days
```

核心指标：

```text
recent_video_count
recent_guide_video_count
creator_count
top_video_views
median_views
view_velocity_proxy
intent_video_share
```

### YouTube Signal 的意义

YouTube 用来回答：

> 玩家是否已经开始大量寻找攻略、Build、教程、路线、Codes 等“答案型内容”？

例如：

```text
最近 7 天 83 个攻略类视频
Top Guide 48h 220K views
多个不同创作者同时产出
```

属于强内容需求信号。

### 配置

```text
YOUTUBE_API_KEY
```

必须做缓存、请求预算和候选游戏上限，避免无控制查询消耗配额。

---

### 4.5 Reddit

V2 新增“玩家问题源”。

目标不是采新闻，而是挖重复问题。

默认低门槛路径：

```text
Reddit public RSS / public pages
```

未来如需要更完整数据，可再增加凭证化 Provider；V2 不把付费/复杂 Reddit API 作为硬依赖。

来源优先：

```text
r/gaming
r/Steam
```

再根据候选游戏自动发现/配置游戏专属 subreddit。

重点提取：

```text
how do I...
where is...
best...
codes
tier list
build
map
item
boss
error
not working
stuck
```

核心指标：

```text
question_count
repeated_question_clusters
unique_authors
comment_activity
problem_intent_share
```

Reddit 的主要产物不是 Game Heat，而是：

```text
Question Cluster
→ Keyword Hypothesis
→ Page Opportunity
```

---

# 5. Tier 2：辅助来源

未来可以追加，但不作为 V2 首发阻塞项：

- SteamDB；
- 游戏官方 Discord；
- 游戏官方 X；
- Steam Community Discussions；
- itch.io；
- Roblox / Fortnite 等平台专项来源；
- 小黑盒社区 Signal 导入。

原则：

> Tier 2 只做补强，不改变 Tier 1 任一来源失败时主流程仍可运行的要求。

---

# 6. 统一游戏实体：Game Entity Resolution

这是 V2 必须新增的核心层。

同一游戏在不同平台可能有不同 ID：

```text
Steam appid
Twitch game_id
YouTube query name
Reddit subreddit / alias
Google Trends term/topic
```

建立统一 `GameEntity`：

```json
{
  "canonical_name": "Example Game",
  "slug": "example-game",
  "aliases": ["ExampleGame", "Example Game 2026"],
  "steam_appid": 123456,
  "twitch_game_id": "987654",
  "subreddits": ["ExampleGame"],
  "youtube_queries": [],
  "trends_terms": []
}
```

匹配优先级：

```text
明确平台 ID
>
完全名称
>
规范化名称
>
alias
>
模糊匹配（低置信度）
```

模糊匹配不得自动覆盖已有实体；必须保存 `entity_match_confidence`。

---

# 7. V2 数据模型

## 7.1 GameEntity

字段至少包括：

```text
canonical_name
slug
aliases
platform_ids
release_date
genres
categories
mechanics
understanding_confidence
```

## 7.2 PlatformSignal

统一不同平台信号：

```json
{
  "source": "twitch",
  "game_slug": "example-game",
  "captured_at": "...",
  "metrics": {},
  "confidence": "high",
  "status": "ok"
}
```

## 7.3 QuestionCluster

```text
cluster_name
examples
source_count
question_count
intent
confidence
```

例如：

```text
Boss locations
Best builds
Redeem codes
Workshop/download error
```

## 7.4 PageOpportunity

替代 V1 过于模板化的 KeywordCandidate 作为更高层对象。

```text
page_type
primary_keyword_hypothesis
supporting_queries
trigger_signals
user_problem
page_value
maintenance_level
build_difficulty
existing_site_fit
validation_status
```

KeywordCandidate 可以继续保留为 PageOpportunity 下层字段，避免破坏历史兼容。

## 7.5 ScanSnapshot V2

增加：

```text
schema_version: 2
entities
platform_signals
question_clusters
page_opportunities
source_statuses
```

现有 V1/V1.1 快照必须保持只读兼容。

---

# 8. 新 Pipeline

V2 建议流水线：

```text
1. Discover
   Steam + Twitch
          ↓
2. Entity Resolution
          ↓
3. Basic Enrichment
   Steam profile / release / reviews / CCU
          ↓
4. Cross-platform Enrichment
   Twitch / Trends / YouTube / Reddit
          ↓
5. Historical Comparison
          ↓
6. Demand Momentum Scoring
          ↓
7. Question Mining
          ↓
8. Page Graph Generation
          ↓
9. Preliminary Site Opportunity Scoring
          ↓
10. Existing Site Routing
          ↓
11. Semrush / SERP Validation Queue
          ↓
12. Snapshot + Dashboard + Report
```

---

# 9. Demand Momentum Score

V1 的 Game Signal Score 主要来自 Steam。

V2 改成 **Game Demand Momentum Score，0–100**。

建议初始权重：

| 维度 | 权重 |
|---|---:|
| Steam Traction | 25 |
| Twitch Momentum | 20 |
| Google Trends Momentum | 15 |
| YouTube Demand | 15 |
| Reddit Question Demand | 15 |
| Cross-platform Confirmation | 10 |
| **总计** | **100** |

## 9.1 Steam Traction — 25

综合：

- 当前玩家；
- 排名；
- 24h/7d 增长；
- 评论规模；
- Release Recency。

## 9.2 Twitch Momentum — 20

综合：

- total viewers；
- rank；
- viewer growth；
- channel growth；
- audience concentration。

避免单个大主播造成错误信号：

若一个主播占总 Viewer 极高比例，需要降低 `breadth_confidence`。

## 9.3 Google Trends — 15

看变化方向，不把 Trends 的相对值当搜索量。

## 9.4 YouTube Demand — 15

重点是：

- 攻略内容数量；
- 播放速度；
- 创作者覆盖；
- 意图型内容占比。

## 9.5 Reddit Question Demand — 15

重点是重复问题，而不是总帖子量。

## 9.6 Cross-platform Confirmation — 10

例如：

```text
Steam ↑
Twitch ↑
Trends ↑
```

比：

```text
Twitch ↑
其他全部无变化
```

置信度高。

建议规则：

```text
≥4个平台方向一致：10
3个平台：7
2个平台：4
1个平台：0
```

但“缺失数据”不能当“方向不一致”。

---

# 10. Page Opportunity Score

必须与 Game Demand Momentum 分开。

原因：

```text
游戏很火 ≠ 有适合个人站承接的搜索需求
```

例如大型竞技游戏很火，但 SERP 可能极强；反过来一个新 Roblox 游戏总体热度稍低，却可能产生大量 `codes/wiki/tier list` 机会。

Pre-SERP Page Opportunity 原始分 0–100：

| 维度 | 权重 |
|---|---:|
| Problem / Query Evidence | 20 |
| Search / Page Intent | 20 |
| Page Graph Breadth | 15 |
| Build Feasibility | 15 |
| Maintenance Cost | 10 |
| Game Demand Contribution | 10 |
| Evidence Confidence | 10 |
| **总计** | **100** |

继续沿用现有纪律：

> **没有真实 SERP / 关键词验证时，不得把机会解释成“可以立即开发”。**

建议维持：

```text
Pre-SERP Score Cap = 69
status = needs_validation
```

或者在 UI 上直接显示：

```text
Research Priority: 0–100
Validation Status: NEEDS_SEMRUSH_SERP
```

两者都可，但不得把 90 分误解为“90%成功率”。

---

# 11. Page Graph：替代纯模板关键词生成

V1 的关键词模板保留，但 V2 需要变成 **Evidence-triggered Page Graph**。

不是每个游戏都生成：

```text
codes
wiki
tier list
map
```

而是根据玩法 + 外部问题信号生成。

例如：

## Codes

只有检测到：

```text
redeem
code
promo
gift code
```

或游戏机制明确支持兑换码时才生成。

## Tier List

只有检测到：

```text
characters
weapons
classes
units
heroes
```

且有明显比较需求时才生成。

## Map / Locations

只有游戏有：

```text
open world
collectibles
NPC locations
boss locations
resource nodes
```

且 Reddit/YouTube 出现 location 类问题才提升优先级。

## Builds

适合：

```text
RPG
ARPG
looter
class-based games
```

## Tracker / Calculator / Tool

这是最值得重点识别的类别。

信号包括：

```text
重复手工计算
掉率
材料需求
角色属性
配装比较
进度跟踪
价格/交易
资源定位
```

最终页面图示例：

```text
Example Game
├── /codes
├── /tier-list
├── /best-builds
├── /boss-locations
├── /items
└── /calculator
```

每个节点必须注明：

```text
WHY THIS PAGE EXISTS
```

即：由什么玩法、什么问题、什么跨平台 Signal 触发。

---

# 12. Existing Site Routing

V2 增加已有站点路由。

例如：

```text
Steam Workshop / SteamCMD
→ WorkshopFetch

通用游戏工具
→ GameKitHQ

Fortnite Sprite
→ FN Sprite Hub
```

输出：

```text
EXPAND_EXISTING_SITE
```

优先于：

```text
VALIDATE_NEW_SITE
```

避免每个词都新建站。

配置示例：

```yaml
existing_sites:
  WorkshopFetch:
    intents:
      - steam workshop
      - workshop download
      - steamcmd
  GameKitHQ:
    intents:
      - calculator
      - tracker
      - generator
```

---

# 13. Dashboard V2 信息架构

Dashboard 继续作为主入口，不退回 CLI-first。

首页应该先回答：

> **今天最值得研究的游戏是什么？**

而不是先显示大量关键词表格。

## 13.1 首页

建议：

```text
┌─────────────────────────────────────────────┐
│ Game Keyword Radar                         │
│ [扫描今日机会]              数据源状态      │
├─────────────────────────────────────────────┤
│ Top Opportunities                          │
│                                             │
│ #1 Game A     Demand 91    Pages 8          │
│ Steam ↑ Twitch ↑ Trends ↑ YouTube ↑        │
│ [查看机会]                                  │
│                                             │
│ #2 Game B     Demand 84    Pages 5          │
├─────────────────────────────────────────────┤
│ 新增机会 | 快速上升 | 待验证 | 已忽略        │
└─────────────────────────────────────────────┘
```

## 13.2 游戏详情页

顶部展示：

```text
Game Demand Momentum: 88
Validation: Needs Semrush/SERP
```

然后五个平台卡片：

```text
Steam
Twitch
Trends
YouTube
Reddit
```

每张卡必须显示：

```text
当前值
历史变化
数据时间
状态/置信度
```

## 13.3 Page Graph

展示：

```text
Page Opportunity
Score
Trigger Evidence
Build Difficulty
Maintenance
Existing Site Fit
```

## 13.4 Validation Queue

单独一页：

```text
待 Semrush
待 SERP
验证通过
Skip
```

人工录入后才能进入 `validated`。

## 13.5 历史变化

保留 V1.1 已实现的历史快照能力，并升级为：

```text
Game Rank Change
Demand Score Change
Platform Signal Change
New Page Opportunities
Removed Page Opportunities
```

仍需明确：

> 本地快照变化 ≠ 搜索量预测。

---

# 14. 技术模块改造建议

在现有项目结构上增加，不重写整个包。

建议：

```text
src/game_keyword_radar/
├── sources/
│   ├── steam.py              # 现有，增强
│   ├── trends.py             # 现有，Provider 化
│   ├── twitch.py             # 新增
│   ├── youtube.py            # 新增
│   └── reddit.py             # 新增
│
├── analyzers/
│   ├── game_profile.py       # 现有
│   ├── keywords.py           # 现有，逐步变成 page graph 下层
│   ├── entity_resolution.py  # 新增
│   ├── demand_momentum.py    # 新增
│   ├── question_mining.py    # 新增
│   ├── page_graph.py         # 新增
│   └── scoring.py            # 升级 V2
│
├── history.py                # 现有，扩展平台信号对比
├── models.py                 # schema_version 2
├── pipeline.py               # V2 pipeline
├── storage.py                # 继续本地 JSON 持久化
├── reporting.py
├── web/
└── cli.py
```

---

# 15. 本地存储策略

V2 继续坚持 Local-first。

不引入外部数据库。

建议目录：

```text
data/
├── raw/
│   ├── steam/
│   ├── twitch/
│   ├── trends/
│   ├── youtube/
│   └── reddit/
│
├── processed/
│   └── <run-id>.json
│
├── entities.json
├── history-index.json
└── latest.json
```

每次 scan 都必须保存：

```text
source
captured_at
market
status
raw evidence
```

上游失败不得覆写成空数据。

---

# 16. 请求预算与性能原则

V2 不应对每个候选游戏无脑跑全部来源。

采用两阶段扫描：

## Stage A：Broad Discovery

低成本发现：

```text
Steam
Twitch Top Games
```

得到例如 50–100 个候选。

## Stage B：Deep Enrichment

只对 Top N 做：

```text
Trends
YouTube
Reddit
```

默认：

```text
Top 10
```

最大：

```text
Top 30
```

这样控制：

- API 配额；
- 扫描时长；
- Google Trends 稳定性；
- YouTube 搜索请求量。

所有 Provider 必须支持缓存。

---

# 17. 配置建议

`.env.example` 增加：

```text
TWITCH_CLIENT_ID=
TWITCH_CLIENT_SECRET=
YOUTUBE_API_KEY=
```

配置文件增加：

```yaml
sources:
  steam: true
  twitch: true
  trends: true
  youtube: true
  reddit: true

scan:
  discovery_limit: 80
  deep_analysis_limit: 10

markets:
  steam_country: US
  youtube_region: US
  trends_geo: US

history:
  compare_24h: true
  compare_7d: true
```

来源没有凭据时：

```text
status = unavailable
```

不能导致扫描失败。

---

# 18. CLI V2

保留现有：

```bash
game-radar serve
game-radar scan
game-radar demo
game-radar report
```

建议新增：

```bash
game-radar scan --deep 10
game-radar sources
game-radar validate
game-radar compare
```

`game-radar sources` 输出：

```text
Steam      OK
Twitch     OK
Trends     LIMITED
YouTube    OK
Reddit     OK
```

Dashboard 仍然是日常入口。

---

# 19. Codex Skill 改造

现有 `game-keyword-scan` Skill 保留。

但 Skill 的任务从：

> 读取 Steam 快照 + 关键词候选

升级为：

> 读取跨平台 Demand Snapshot + Page Graph + Validation Queue。

Skill 不负责伪造搜索量。

它可以做：

- 解读 Top Opportunities；
- 合并问题簇；
- 检查 Page Graph 是否与玩法匹配；
- 根据人工提供的 Semrush/GSC/SERP 数据补充验证；
- 输出 Build / Skip 研究结论。

不得把：

```text
Twitch viewers
YouTube views
Trends index
```

直接换算成 Google 月搜索量。

---

# 20. 评分与事实边界

以下必须继续成为硬规则：

1. 缺失数据 ≠ 0；
2. 不同平台指标不能直接相加；
3. Trends 是方向信号，不是搜索量；
4. YouTube Views 是内容需求代理，不是 Google Volume；
5. Twitch Viewers 是注意力信号，不是搜索意图；
6. Reddit 问题是需求证据，但可能存在社区偏差；
7. 无 SERP / Semrush 验证，不得给出“立即建站”；
8. 所有分数都是研究排序，不是成功率。

---

# 21. 建议的行动状态

统一输出：

## WATCH

有早期 Signal，但证据不足。

## VALIDATE

跨平台需求较强，值得进入 Semrush + SERP。

## EXPAND_EXISTING_SITE

需求适配现有站点，应优先扩页。

## VALIDATE_NEW_SITE

Page Graph 足够宽，且更适合独立站，但仍需 SERP 验证。

## SKIP

热度/意图/页面宽度不足，或维护成本过高。

---

# 22. V2 Dashboard 北极星

首页不是：

```text
今天抓了多少游戏
```

也不是：

```text
生成了多少关键词
```

而是：

> **今天有哪些游戏值得我花 10–20 分钟继续做 Semrush / SERP 验证？**

理想输出每天：

```text
3–10 个值得验证的游戏
```

而不是 100 个低质量候选。

---

# 23. 实施里程碑

## M0 — Scope Cleanup

目标：冻结职责。

- 更新 README / PROJECT_CONTEXT；
- 明确小黑盒内容功能不进入本项目；
- 标记 V2 schema；
- 保留 V1 快照兼容。

验收：文档、UI、代码命名都不再出现内容运营职责。

---

## M1 — V2 Models + Entity Resolution

- `GameEntity`；
- `PlatformSignal`；
- `QuestionCluster`；
- `PageOpportunity`；
- entity alias 与 match confidence；
- schema v2 snapshot。

验收：Steam 游戏可稳定映射成统一 Entity，历史 V1 数据仍可读。

---

## M2 — Twitch

- OAuth App Token；
- Get Streams；
- 按游戏聚合；
- Snapshot；
- 24h/7d 变化；
- Source Status / Cache。

验收：Dashboard 可显示 Steam + Twitch 双源热度。

---

## M3 — YouTube + Reddit

### YouTube

- search/list；
- videos/list；
- Intent queries；
- view velocity proxy；
- creator breadth。

### Reddit

- 游戏问题采集；
- Question clustering；
- 重复需求检测。

验收：一个候选游戏能输出真实问题簇，而不是仅靠模板猜词。

---

## M4 — Trends Provider Upgrade + Demand Momentum

- Trends Provider interface；
- 当前非官方 Provider 适配；
- Official Alpha Provider 预留/接入；
- Cross-platform scoring；
- Demand Momentum。

验收：任一来源失败时仍生成部分结果，并显示 confidence/completeness。

---

## M5 — Evidence-triggered Page Graph

- 把现有关键词模板纳入 Page Graph；
- 引入玩法触发条件；
- 引入 Reddit/YouTube evidence；
- Existing Site Routing；
- Preliminary Site Opportunity Score。

验收：不再给所有游戏机械生成相同页面类型。

---

## M6 — Dashboard V2

页面：

```text
Overview
Game Detail
Page Graph
Validation Queue
History Compare
Source Status
```

验收：浏览器内可以完成：

```text
扫描
→ 找 Top Game
→ 看跨平台 Signal
→ 看 Page Graph
→ 加入验证队列
→ 回看历史
```

无需使用 CLI。

---

## M7 — Skill + Reporting

- 更新 Skill；
- 更新 scoring reference；
- Markdown 报告；
- Build/Skip 研究模板；
- 完整回归测试。

---

# 24. V2 验收标准

必须满足：

1. Dashboard 仍是主要入口；
2. Steam + Twitch 至少两个核心发现源可运行；
3. YouTube / Reddit 可用于深度候选验证；
4. Google Trends 保持可选、失败降级；
5. 同一游戏跨平台 Entity 可以合并；
6. 保存完整 Source Status；
7. 缺失数据不会当成零；
8. 支持本地历史对比；
9. Demand Score 与 Page Opportunity Score 分离；
10. Page Graph 有 Evidence Trigger；
11. 不机械生成无关 codes/tier-list/map 页面；
12. 未做 SERP / Semrush 验证时保持 `needs_validation`；
13. Existing Site Opportunity 优先于新建站建议；
14. 任一第三方来源失败不导致页面白屏；
15. Demo / Fixture 与 Live 数据明确区分；
16. 所有自动测试默认离线可运行；
17. 至少完成一次真实 Steam + Twitch + YouTube 扫描验收。

---

# 25. V2 明确不做

V2 不做：

- 小黑盒内容生成；
- 社媒自动发布；
- 自动文章生成；
- 自动 Google SERP 大规模抓取；
- 自动购买 Semrush/API；
- 自动建站；
- 云端 SaaS；
- 用户系统；
- 多租户；
- 账号农场；
- 代理/反检测体系。

---

# 26. 最终产品定义

V2 不再定义为：

> 游戏关键词生成器

而是：

> **Game Demand Radar**
>
> 用 Steam、Twitch、Google Trends、YouTube、Reddit 的跨平台信号，发现正在形成需求的游戏，再把真实玩家问题组织成可验证的 Keyword / Page Graph，帮助个人站长决定“下一个游戏站或页面值得不值得做”。

最终工作流：

```text
Steam + Twitch
      ↓
发现正在起量的游戏
      ↓
Trends + YouTube + Reddit
      ↓
确认搜索/内容/问题需求
      ↓
Page Graph
      ↓
Preliminary Opportunity
      ↓
Semrush Keyword Graph
      ↓
Google SERP
      ↓
Build / Skip
```

---

# 27. 外部接口实施备注（2026-09）

- Twitch：优先使用官方 Helix API；`Get Streams` 需要 App Access Token 或 User Access Token，并支持按 `game_id` 查询/分页。
- YouTube：使用 YouTube Data API v3 的 `search.list` 做关键词/近期视频发现，再用 `videos.list` 取得视频统计；需要 API Key，并必须控制查询预算和缓存。
- Google Trends：Google 已提供官方 Trends API Alpha，但仍为受限测试；有权限时优先使用官方 Provider，没有权限时继续保留现有 best-effort Provider。

官方参考：

- Twitch API Reference: https://dev.twitch.tv/docs/api/reference
- YouTube Data API: https://developers.google.com/youtube/v3/docs
- Google Trends API Alpha: https://developers.google.com/search/apis/trends

