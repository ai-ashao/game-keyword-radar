# Game Keyword Radar：增量优化方案（零新增 API Key · 保留可采集数据版）

原方案日期：2026-09-11  
本次修订：2026-09-12  
状态：**V2.2 实施规格（复审修订版）**。本版冻结“零新增凭据”架构边界，并补齐实体消歧、同口径比较、Best-Effort 调度、熔断与证据新鲜度要求。代码实现与验收结果必须单独记录，不能用方案文档冒充已通过。  
核对仓库：`ai-ashao/game-keyword-radar`  
原方案源码审查基线：`c897d86cb4e7d1ccbe8ec505deae83673ce69265`  
当前 README：`2.1.0rc1`。

---

## 0. 本轮总原则

本轮目标不是“删除所有需要 API 的数据源”，而是：

> **砍掉新增 API Key / OAuth / 开发者账号 / 付费搜索 API 的硬依赖，但尽可能保留公开网页、公开接口、RSS、CSV 导入和本地采集能获得的数据。**

系统必须在**没有新增第三方凭据**的环境下完成核心工作流：

```text
发现候选
  ↓
保存实体与 WHY NOW
  ↓
积累公开活动/内容/趋势信号
  ↓
生成任务与页面假设
  ↓
导出搜索验证包
  ↓
Semrush / Trends / SERP 人工验证
  ↓
回填结果
  ↓
WATCH / VALIDATE / EXPAND_EXISTING_SITE / VALIDATE_NEW_SITE / SKIP
```

已经存在并由用户配置的 Twitch / YouTube 等凭据**不删除、不覆盖、不迁移**；它们继续作为可选增强来源，但不得成为新版最低运行条件。

---

## 1. 数据源重新分级

以后所有数据源按稳定性和依赖方式分成 A / B / C 三层，避免把“免 Key”“可抓”“可验证”混成一个概念。

### A 级：自动 + 无新增 Key

这些来源构成 Radar 的主干。失败需要记录，但设计上不能依赖新账号或新 API Key。

| 来源 | 主要数据 | 用途 |
|---|---|---|
| Steam 现有免密钥路径 | 游戏身份、发行/活动类可取得信息、现有项目已使用的公开数据 | 实体发现、生命周期、活动观测 |
| Competitor Sitemap | 新游戏页、新攻略页、新工具页、页面任务 | 发现候选与内容供给变化 |
| Google Trends Trending Now RSS | 正在上涨的搜索主题、时间、地区等 | 趋势发现，不当绝对搜索量 |
| 公开 RSS / Feed | 新闻、更新、社区公开 Feed | WHY NOW 辅助信号 |
| 人工种子 | 游戏名、URL、平台 ID、观察理由 | 补充长尾与人工发现 |

A 级来源的基本要求：

- 无新增 Key 也能调用；
- 来源失败不能写成业务值 `0`；
- 保存采集时间、来源、覆盖状态；
- 数据只能证明它实际观察到的事实，不能越级推导搜索需求。

### B 级：自动 + Best Effort

这些来源可以提供高价值信号，但依赖公开网页或非官方自动化方式，可能因页面、限流或反自动化策略变化而失败。

| 来源 | 主要数据 | 用途 |
|---|---|---|
| Twitch 第三方公开统计（人工查看/结构化录入） | 可见的观看/频道/时间窗口统计 | 仅人工辅助；不自动抓取明确禁止 scraping 的站点 |
| `yt-dlp` 的 YouTube 搜索能力 | 视频标题、频道、发布时间、搜索结果等可取得公开信息 | 内容扩散、创作者覆盖、任务词发现 |
| 公开游戏平台榜单页 | 排名、新增游戏、可见热度指标 | 候选发现 |
| 其他无需登录的公开页面 | 页面新增或可见公开统计 | 辅助来源 |
| Roblox Experimental | 仅实施时真实验证仍可匿名取得的字段；否则 unavailable | Roblox-only 实验观察，不属于主干 |

B 级来源必须遵守：

- 低频、限量、可缓存；
- 单独标记 `best_effort`；
- 失败、验证码、结构变化、访问拒绝均记状态，不写 `0`；
- 不能成为系统启动或候选保存的硬门槛；
- 不为了恢复 B 级来源而要求用户购买代理、验证码服务或新 API。

### C 级：人工高价值验证

这些数据不追求全自动，但直接影响“这个词/页面/游戏是否值得做”。

| 来源 | 输入方式 | 用途 |
|---|---|---|
| Semrush | 网页查询后 CSV/XLSX 导出或人工录入 | Volume、KD、Intent、Trend、SERP 竞争研究 |
| Google Trends Explore | CSV 导入 | 已知游戏/词的趋势比较；与 Trending RSS 明确分层 |
| Google SERP | 人工打开与结构化记录 | 搜索意图、强站占位、独立站机会 |
| 人工判断 | 表单/注释 | 同名实体纠错、页面拆分、机会确认 |

C 级不是“低级数据”。相反，它是最终业务决策的关键验证层。

---

## 2. 明确删除的依赖

本轮真正砍掉的是下面这些**必须申请凭据才能运行的新接入**：

| 项目 | 本轮处理 |
|---|---|
| 新申请 Twitch Client ID / Secret | 不要求；现有已配置凭据继续可选使用 |
| 新申请 YouTube Data API Key | 不要求；改用 best-effort 公开搜索补充 |
| Google Trends 官方 API Alpha | 不申请；使用 Trending RSS/公开导出 + Explore CSV |
| Serper / SerpApi | 不接入；SERP 保留人工验证 |
| Semrush API | 不接入；使用网页功能 + CSV 导出 |
| 云 LLM API 做任务聚类 | 不接入；先用本地规则、词典和人工校正 |
| Roblox 需要 Cookie / Open Cloud Key / OAuth 的端点 | 不接入；Roblox 仅保留 Experimental 探测，匿名路径实测不可用即 `unavailable` |
| 新代理池 / CAPTCHA 服务 | 不接入 |

因此：

> **砍的是 API 依赖，不是 Twitch、YouTube、Trends、Semrush、SERP 这些数据维度。**

---

## 3. 现有 Game Keyword Radar：保留，不重构

### 3.0 V2.2 四条 P0 工程约束

1. **Roblox 不属于 A 级稳定源。** 仅作为 Experimental / B 级待验证来源；如果匿名请求不再可用，标记 `unavailable`，不得要求新增 Cookie、Open Cloud Key、OAuth 或其他凭据。
2. **B 级自动来源只对 Deep candidates 运行。** YouTube `yt-dlp`、Roblox Experimental 不参与全量宽筛；SullyGnome 等明确禁止 scraping 的第三方统计站只提供人工查看入口，不作为自动 Provider。
3. **所有跨来源候选先过 Entity Resolution Gate。** 同平台 ID 可自动合并；跨平台仅凭同名/标准化同名不得自动合并，必须有人工 override、强别名/上下文证据或保持 `unresolved_entity`。
4. **数值增长只允许同口径比较。** 至少要求 `provider + metric + metric_unit + window/measurement + market (+ language when applicable)` 可比；跨 Provider 只做佐证，不平均、不计算百分比。



继续使用现有 Python、本地优先架构，不换成其他 Radar，也不绑定 ShipLean。

原有以下能力全部保留：

| 能力 | 处理 |
|---|---|
| Steam / Twitch 发现与定向观察框架 | 保留；Twitch API 成为 optional enhancement |
| 历史观测与生命周期 | 继续复用 |
| Observe → Compare → Admit → Allocate → Deep | 继续复用 |
| 新游 / 增长 / 老游新需求 / 探索四通道 | 保留 |
| WHY NOW / explain / 来源状态 | 保留并增强 |
| 本地观察项与人工种子 | 保留 |
| Page Graph | 继续使用，并细化到具体任务 |
| 人工 Semrush / SERP 验证 | 保留为最终决策门槛 |
| 旧快照和历史数据 | 只读兼容，不重新解释 |

原有动作不扩散：

`WATCH / VALIDATE / EXPAND_EXISTING_SITE / VALIDATE_NEW_SITE / SKIP`

`VALIDATE_NEW_SITE` 仍然只是“值得进一步验证独立站”，不是自动建站命令。

---

## 4. 第一优先：竞品 Sitemap 增量发现

### 4.1 目标

把经过人工挑选的攻略站、Wiki、游戏工具站、小游戏站变成持续观察源。

Radar 关注的是：

- 新增了什么游戏；
- 新增了什么页面类型；
- 某个旧游戏突然出现了什么新任务；
- 多个独立网站是否开始同时铺某类内容。

### 4.2 最小实现

支持：

- Sitemap；
- Sitemap Index；
- 首次导入建立 baseline；
- 后续只识别真实新增；
- URL 规范化；
- `lastmod` 保存但不当发布时间；
- 从 URL、标题、公开页面信息提取游戏和任务候选；
- 保存出处与首次观察时间。

核心字段：

```text
source_id
canonical_url
observed_at
first_seen_at
lastmod
coverage_status
candidate_game
candidate_task
confidence
```

### 4.3 关键边界

Sitemap 是**内容供给信号**，不是玩家需求或搜索量证明。

同一个网站一次新增 20 个页面：

- 可以证明该网站在铺内容；
- 不能算 20 个独立需求来源；
- 不能直接推导“搜索量暴涨”。

---

## 5. Google Trends：恢复自动发现，但不接官方 API

上一版把 Trends 过度收缩成了“仅 CSV”。本版调整为两条路径。

### 5.1 自动路径：Trending RSS / 公开数据

用于发现：

- 突然进入趋势的游戏名；
- 游戏更新、版本、活动相关上升主题；
- 与已知 Game Entity 匹配的新趋势事件。

建议流程：

```text
Trending RSS / 公开趋势入口
    ↓
本地规则过滤游戏相关主题
    ↓
实体匹配
    ↓
记录 trend_signal
    ↓
进入 exploration / watch
```

保存：

```text
query_or_topic
region
observed_at
source_url
matched_entity
match_confidence
trend_type
```

它只说明“趋势正在形成或被观察到”，不能代替 Semrush Volume。

### 5.2 人工路径：Google Trends Explore CSV

对已经进入研究队列的游戏或关键词：

1. Radar 生成待比较词；
2. 用户在 Trends Explore 中查询；
3. 下载 CSV；
4. 导入 Radar；
5. 保存地区、时间范围、搜索类型、同组比较关系。

Trends 指数保持相对指标，禁止转换成伪造的绝对搜索量。

### 5.3 降级规则

自动趋势入口失败时：

- 不阻塞主流程；
- 标记 unavailable / failed；
- 仍可使用 Explore CSV 人工补充。

---

## 6. Twitch：API 非必需；无 Key 时只保留人工公开统计验证

### 6.1 保留现有 Twitch API

如果用户原来已经有：

```text
TWITCH_CLIENT_ID
TWITCH_CLIENT_SECRET
```

现有 Twitch Provider 继续可用，不删除。

但：

- 不要求现在申请；
- 不作为新版最低验收条件；
- 没配置时不提示“必须补 Key 才能继续”。

### 6.2 无 Key 路径：人工公开统计

第三方 Twitch 统计网站可用于人工确认游戏观看规模、频道广度和时间窗口变化，但**不得默认自动抓取**。例如 SullyGnome 页面明确提示不要 scrape，因此本项目只生成人工查看入口/结构化记录，不建设自动爬虫。

人工记录至少保存：

```text
provider
metric
metric_unit
window
observed_at
source_url
notes
```

这类数据只能作为 `secondary_public_page / manual_evidence`，不能伪装成 Twitch 官方 API 数据，也不能与官方 API 瞬时观测拼接成同一增长序列。

### 6.3 降级规则

- 没有 Twitch Key：不阻塞主流程；
- 不为了自动化购买代理、验证码服务或新账号；
- 第三方页面禁止抓取时仅提供人工链接；
- 人工未检查不是“0 viewers”。

---

## 7. YouTube：API 非必需，保留公开搜索 best-effort 信号

### 7.1 目的

YouTube 在 Radar 中不是搜索量来源，而是：

- 内容扩散；
- 创作者数量；
- 视频发布时间；
- 新出现的玩法、问题、攻略任务；
- 某游戏是否开始被多名创作者覆盖。

### 7.2 路径

如果已有 `YOUTUBE_API_KEY`，原官方 API Provider 可以继续可选使用。

没有 Key 时，允许使用 `yt-dlp` 等公开搜索能力做低频 best-effort 查询，例如：

```text
ytsearch10:<game name>
ytsearch10:<game name> guide
ytsearch10:<game name> codes
ytsearch10:<game name> how to
```

可取得什么字段由实际运行结果决定，不在设计文档里假定所有字段永远存在。

### 7.3 任务词提取

例如发现标题：

```text
Game X Beginner Guide
Game X All Endings
Game X Secret Room Location
Game X Best Build
```

Radar 可以提取：

```text
beginner guide
all endings
secret room location
best build
```

作为 `content_proxy_task`，进入 Page Graph 候选。

注意：

> YouTube 标题是内容代理，不是玩家真实提问；不能计入 question_count。

### 7.4 失败语义

YouTube 公开抓取失败属于正常降级场景。

失败时：

- 不阻塞扫描；
- 不写 0；
- 不自动切换付费服务；
- 不要求用户申请 API。

---

## 8. Semrush：不接 API，但把 CSV 工作流做顺

这是最终验证层之一，优先级高于继续增加自动数据源。

### 8.1 Radar 生成验证包

每个候选输出：

```text
Game Entity
WHY NOW
aliases
platform IDs
candidate queries
candidate tasks
existing evidence
missing evidence
recommended validation
```

可导出：

- CSV；
- Markdown；
- 可复制查询列表。

### 8.2 用户在 Semrush 网页批量查询

然后导出 CSV/XLSX，再导入 Radar。

系统允许列名映射，并尽量识别：

```text
Keyword
Volume
KD
Intent
Trend
CPC
Competition
Database / Country
```

套餐或导出格式不提供的字段保持空值。

### 8.3 导入要求

保存：

- 来源；
- 数据库/国家；
- 查询日期；
- 导入时间；
- 原始关键词；
- 原始指标；
- 与 Entity / Task / Page 的绑定。

重复导入不能重复计分；新证据不能覆盖旧证据而不留版本。

---

## 9. Google SERP：彻底砍 Serper / SerpApi，保留人工结构化验证

Radar 为候选自动生成查询：

```text
"game name"
"game name wiki"
"game name codes"
"game name guide"
"game name calculator"
"game name <task>"
```

用户点击即可打开 SERP，并在 Radar 中记录：

```text
official_site_present
fandom_present
large_publisher_present
reddit_present
youtube_present
independent_site_present
dedicated_tool_present
intent_summary
content_gap
notes
checked_at
market
```

这一步不追求完全自动化。

目标是让一个高价值候选在几十秒到几分钟内完成结构化竞争判断，而不是为了省这一步去引入不稳定的 Google 抓取链路。

---

## 10. Roblox：Experimental，不作为零 Key 主干

### 10.1 原则

Roblox 对游戏站选品有价值，但公开端点的匿名可用性会变化。本轮**不假设** Games/Open Cloud 指标长期免认证，也不为了接入 Roblox 申请新凭据。

### 10.2 启用条件

只有同时满足以下条件才启用 Experimental Provider：

- 实施当天真实请求确认无需登录；
- 不携带 Cookie；
- 不需要 Open Cloud Key / OAuth；
- 响应字段与口径可以保存并解释；
- 失败可独立降级，不拖累主流程。

否则：

```text
provider = roblox_experimental
state = unavailable
reason = anonymous_access_unavailable
```

### 10.3 调度

Roblox Experimental **只对人工种子或已进入 Deep 的 Roblox-only 候选运行**，不做全量市场榜单，不加入 Broad Discovery 的最低验收。

在线人数/访问量等即使取得，也只属于活动信号：

```text
在线规模 ≠ 搜索量 ≠ 攻略需求 ≠ 独立站机会
```

仍需 Task 证据和 C 级 Semrush / Trends / SERP 验证。

---

## 11. Page Graph：从 Intent 粗粒度升级到 Task 粒度

当前设计的主要问题不是没有 Page Graph，而是任务粒度仍然偏粗。

目标结构：

```text
Game Entity
   ↓
Intent
   ↓
Task Cluster
   ↓
Page Hypothesis
   ↓
Search Validation
   ↓
Page Decision
```

例如：

```text
errors
 ├─ startup crash
 ├─ microphone not working
 └─ multiplayer connection failed
```

这些任务不能因为都属于 `errors` 就自动成为同一个页面。

另一方面：

```text
no sound
sound not working
audio not working
```

如果搜索意图一致，可以归并成同一个 Task Cluster。

### 11.1 本轮聚类方式

不用云 LLM API。

采用：

1. 本地规则；
2. 规范化；
3. 词典与同义词映射；
4. 结构化对象识别；
5. 人工 Merge / Split。

每个 Cluster 保存：

```text
task_key
normalized_task
intent
sources
first_seen
last_seen
question_evidence_count
content_proxy_count
validation_status
manual_overrides
```

### 11.2 Page Graph 不自动建页

Task Cluster 只是页面研究候选。

只有完成必要搜索验证后，才能进入：

- EXPAND_EXISTING_SITE；
- VALIDATE_NEW_SITE；
- WATCH；
- SKIP。

---

## 11.5 Entity Resolution Gate（新增 P0）

所有 Steam / Twitch / Sitemap / Trends / YouTube / Roblox 候选进入统一实体表前，先输出解析结果：

```text
raw_name
normalized_name
platform
platform_id
source_url
matched_entity_id
match_method
match_confidence
resolution_status = resolved | probable | unresolved_entity
```

自动合并优先级：

1. 已存在的相同 `platform + platform_id`；
2. 明确人工 override；
3. 已验证 alias + 足够上下文；
4. 跨平台仅同名：**不得自动合并**，进入建议队列。

`unresolved_entity` 可以保存、观察和人工核实，但不能把另一个同名游戏的历史、搜索验证或页面任务继承过来。

---

## 11.6 Evidence Scope、可比性与 Freshness（新增 P0）

所有可进行增长比较的数值证据至少保存：

```text
provider
metric
metric_unit
measurement_or_window
market
language (when applicable)
observed_at
scope_version
coverage
```

只有同口径观测才能计算 delta / percent change。跨 Provider 允许并列佐证，但禁止数值平均或拼接时间序列。

人工搜索证据另保存新鲜度：

```text
freshness_status = fresh | aging | stale
checked_at
```

具体阈值由配置决定；UI/报告必须显示“证据多久以前验证”，不得把 30/60 天前 SERP 当成刚检查。

---

## 11.7 Best-Effort Circuit Breaker（新增）

B 级 Provider 至少保存：

```text
last_success_at
failure_count
retry_after
disabled_until
last_failure_reason
```

连续 `blocked / rate_limited / parse_failed` 时进入退避，不得每个监测周期重复撞同一来源；恢复后先以单个候选探测，再恢复有限流量。若稳定运行必须新增登录、Cookie、PO Token、代理或验证码服务，则 Provider 自动降级 `unavailable`。

---

## 11.8 Scan / Monitor / Deep 职责冻结（新增）

```text
monitor-once
  -> cheap observation only（保持 V2.1：不调用 YouTube / Reddit / Trends / B 级网页）

full scan / broad discovery
  -> Steam + Sitemap + Trends Trending RSS + RSS/低成本公开榜单

Deep
  -> YouTube public + Roblox Experimental + Task Mining
```

这样可避免 Best-Effort 采集随候选池线性膨胀。

---

## 12. 来源状态与证据等级必须彻底分开

新版最重要的工程规则之一：

> **“没有拿到数据”不能等于“没有需求”。**

每个来源至少区分：

```text
success
partial
not_configured
unavailable
rate_limited
blocked
parse_failed
budget_exhausted
not_checked
```

数据层还要区分：

```text
primary_official
secondary_public_page
content_proxy
search_validation
manual_evidence
hypothesis
```

例如：

```text
Twitch API 未配置
Twitch 人工公开统计已核对
YouTube best-effort 失败
Google Trends RSS 命中
Semrush 尚未验证
```

这是一个正常候选状态，不能被汇总成“3/5 来源失败，所以分数低”。

---

## 13. 新的日常工作流

### 第一阶段：机器宽筛

自动运行：

```text
Steam
Sitemap
Google Trends Trending RSS
RSS / Feed
低成本公开游戏平台榜单
```

得到：

```text
大量实体
   ↓
少量值得研究的候选
```

### 第二阶段：分配 Deep 预算后运行 Best-Effort

只针对 `selected_for_deep`（默认约 Top 10）运行：

```text
YouTube / yt-dlp
Roblox Experimental（仅匹配对象）
```

任何 B 级失败只记录状态并触发退避/熔断，不改变候选实体本身。

### 第三阶段：Radar 整理研究材料

自动整理：

- WHY NOW；
- 来源状态；
- 历史变化；
- 任务簇；
- 页面假设；
- 缺失证据；
- Semrush 查询包；
- Trends 查询包；
- SERP 查询包。

### 第四阶段：人工高价值确认

人工使用：

```text
Semrush
Google Trends Explore
Google SERP
```

然后导入或录入。

最终 Radar 输出的是：

> **今天最值得继续花 5–10 分钟研究的游戏 / 关键词 / 页面机会。**

而不是试图自动预测“爆款概率”。

---

## 14. 实施顺序

按 ROI 与工程风险重新排序：

| 顺序 | 工作包 | 目的 |
|---|---|---|
| 0 | 无新增 Key 运行模式与来源状态统一 | 先保证没有新凭据也能完整工作 |
| 1 | Sitemap 增量发现 | 最直接增加游戏与页面候选入口 |
| 2 | 搜索验证包 + Semrush/Trends CSV + SERP 回填 | 让候选真正能快速转成决策 |
| 3 | Google Trends Trending 自动发现 | 增加搜索侧早期信号 |
| 4 | Twitch 人工公开统计入口/记录 | 无 Key 时保留辅助热度判断，不建设违规抓取链路 |
| 5 | YouTube `yt-dlp` best-effort Provider | 恢复内容扩散与任务词发现 |
| 6 | Roblox Experimental Provider | 仅在匿名访问真实可用时补充 Roblox-only 覆盖 |
| 7 | Task-level Page Graph | 把发现进一步落到具体页面机会 |

这里有一个刻意调整：

**搜索验证包放在大量新数据源之前。**

原因是 Radar 的瓶颈不只是“候选不够多”，还包括“发现之后能不能迅速判断值不值得做”。

---

## 15. 最低验收标准

新版不能继续使用“Steam + Twitch API + YouTube API 全部成功”作为唯一 Live Acceptance。

需要拆成独立层级。

### L0：离线回归

- 单元测试；
- Parser 测试；
- CSV 导入；
- Task Cluster；
- 来源状态；
- 旧快照兼容。

### L1：Zero-New-Key Live

不新增任何 Key 时，至少完成：

- 一个真实 Steam / 公开来源实体；
- Sitemap 真实读取；
- 一个公开趋势/Feed 信号；
- 候选保存；
- WHY NOW；
- 验证包导出；
- CSV 回填；
- Page Graph 输出。

B 级来源允许部分失败。

### L2：Best-Effort Providers

分别验证：

- Twitch 人工公开统计记录（不要求自动抓取）；
- YouTube 公开搜索；
- Roblox Experimental（仅在匿名访问真实可用时；否则允许 `unavailable` 通过降级验收）。

每个独立通过，不互相成为前置条件。

### L3：跨日数据

真实积累 24h / 7d 数据后，才能验证持续增长逻辑。

单次成功不能冒充跨日验证。

### L4：业务有用性

人工抽查：

- 今日入选；
- 近门槛未入选；
- WATCH；
- VALIDATE；
- SKIP。

确认 Radar 是否真的减少无效研究，而不是只追求测试全部变绿。

---

## 16. 暂缓项

当前不做：

- Serper；
- SerpApi；
- Semrush API；
- Google Trends 官方 API Alpha；
- 新申请 Twitch / YouTube API 作为交付要求；
- 全网 Twitch 数据；
- 全量 Roblox 榜单；
- 为 Roblox 新申请 Cookie / Open Cloud Key / OAuth；
- 一次接入所有小游戏网站；
- 云端 LLM 聚类；
- 自动建站；
- 自动写文章；
- 云数据库；
- 用户系统；
- 代理池 / CAPTCHA 绕过；
- “爆款概率”预测模型。

后续任何新数据源必须回答三个问题后才能进入：

1. 能不能显著提高候选召回或判断质量？
2. 如果失败，会不会拖死主流程？
3. 维护成本是不是比它提供的信息价值还高？

---

## 17. 版本迁移要求

升级必须保证：

- 不覆盖 `.env`；
- 不覆盖 `radar.toml`；
- 不删除现有 Twitch / YouTube 凭据；
- 不删除历史 snapshots；
- 不覆盖人工 annotations / validation；
- 旧 Page ID 可追溯；
- 新 Task Cluster 拆分不能自动继承全部旧验证；
- Provider 改变记录 policy / schema version；
- 来源变多导致的排名变化不能伪装成真实需求增长。

---


## 17.1 V2.2 开发完成判据

本规格不能只以“文件存在”验收。至少应有离线测试覆盖：

- 跨平台同名不自动合并，人工 override 可合并；
- 不同 provider/window/market 的观测不可比较；
- Sitemap 首次建立 baseline 不产生新增，第二次只输出真实增量；
- Sitemap 局部失败不会把历史 URL 当成删除/新增；
- Semrush / Trends CSV 重复导入不重复计分，缺列不补 0；
- B 级 Provider 只收到 Deep candidates；
- monitor-once 不调用 B 级 Provider；
- Best-Effort 连续失败会退避；
- 旧快照和旧 ValidationRecord 仍可读取。

---
## 18. 最终定位

Game Keyword Radar 不应发展成：

> 一个依赖十几个 API、每天维护爬虫、试图替人自动决定建什么站的庞大平台。

它应该是：

> **低成本游戏机会研究雷达：机器负责宽筛、积累和整理证据；高价值搜索判断由 Semrush / Trends / SERP 完成；最终把每天几千个游戏信号压缩成少量真正值得继续研究的候选。**

技术路线因此冻结为：

```text
A · Broad Discovery：Steam / Sitemap / Trends RSS / Feed
        ↓
Entity Resolution Gate
        ↓
Observe → Compare → Admit → Allocate
        ↓
B · Deep Best-Effort：YouTube public / Roblox Experimental
        ↓
Task / Keyword / Page Graph
        ↓
C · Search Validation：Semrush CSV / Trends Explore CSV / SERP
        ↓
WATCH / VALIDATE / EXPAND_EXISTING_SITE / VALIDATE_NEW_SITE / SKIP
```

核心原则：

> **不为了自动化而自动化，不为了免 Key 而丢掉有价值的数据，也不为了多一个数据源把 Radar 本身做成第二个创业项目。**

---

## 19. 参考依据

### 当前项目

- `https://github.com/ai-ashao/game-keyword-radar`
- README：`https://github.com/ai-ashao/game-keyword-radar/blob/main/README.md`
- 原源码审查基线：`c897d86cb4e7d1ccbe8ec505deae83673ce69265`

### 参考开源项目

- Game Name Radar：`https://github.com/foxigaoqian/game-name-radar`
- Roblox Radar：`https://github.com/Leobartz/roblox-radar`
- Google Trends Skills：`https://github.com/WaytoAIC/google-trends-skills`
- yt-dlp：`https://github.com/yt-dlp/yt-dlp`

### 数据源/官方说明

- Twitch Authentication：`https://dev.twitch.tv/docs/authentication/`
- YouTube Data API：`https://developers.google.com/youtube/v3/getting-started`
- Google Trends Trending Now：`https://support.google.com/trends/answer/3076011`
- Google Trends Export：`https://support.google.com/trends/answer/4365538`
- Google Trends API Alpha：`https://developers.google.com/search/apis/trends`
- Semrush Keyword Overview：`https://www.semrush.com/kb/257-keyword-overview`
- Roblox Games API reference：`https://create.roblox.com/docs/cloud/reference/domains/games`
- SullyGnome：`https://sullygnome.com/`

上述 B 级公开网页来源的可访问性、HTML 结构和自动化兼容性均视为可变化条件，实施时必须真实测试，不把方案文档当成长期可用性保证。
