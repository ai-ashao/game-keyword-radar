# Game Keyword Radar V1 计划审计

审计对象：`Game Keyword Radar 本地版实施计划.pdf`，26 页。

审计日期：2026-08-09。

## 结论

原计划的数据留存、失败降级、意图优先和不编造指标原则可以保留，但原计划不能直接作为 V1 实施规格。它把 Agent Skill、CLI、网页搜索和外部采集混成一条隐式流水线，也没有定义 Dashboard。修订后的 V1 改为“本地 Dashboard + Python 数据引擎 + Codex Skill”，并把 Twitch 移出 V1。

## 已修复的问题

| 原计划问题 | 影响 | 修订决定 |
|---|---|---|
| 产品被描述为“发现游戏流量词” | 没有搜索量和 KD 时容易把趋势或规则分数误写成流量结论 | 改为“发现待验证的页面和工具机会” |
| V1 只有 CLI/Skill，没有用户要求的页面 | 日常使用需要读 Markdown 和 JSON，反馈慢 | Dashboard 成为主入口，CLI 保留为自动化入口 |
| Steam、Twitch、Trends 混合评分 | 不同来源的范围和含义不可直接比较 | Twitch 移出 V1；Steam、Trends 分开显示来源状态 |
| Google Trends 被当作稳定 API | 非官方采集可能 429、空数据或接口变化 | 默认关闭，作为可选辅助信号；失败不影响扫描 |
| 不同 Trends 查询的 0-100 数值横向比较 | Google Trends 数值按查询范围归一化，跨批次不可直接比较 | 只保存单个游戏自身时间窗口的方向变化，不用于跨游戏绝对排序 |
| “理解游戏玩法”没有输入来源 | 规则会凭游戏名猜测功能需求 | 只依据 Steam genres/categories/description 推断，并保存置信度与证据 |
| “Agent 使用网页搜索”是 CLI 的隐含能力 | 扫描不可复现、评分证据无法回放 | SERP 证据由 Skill 或人工补充；缺失时状态最高为 `needs_validation` |
| 总分公式只有权重没有转换规则 | 同样输入可能得到不同分数 | 在实施计划中锁定确定性公式和强制封顶规则 |
| 未限制请求预算 | 30 个游戏可能放大成数百次请求 | V1 深度分析默认 10、最大 30；Trends 最多 5 个游戏 |
| PDF 中命令丢失空格 | 复制后无法运行 | 所有命令迁移为可复制的 Markdown 代码块 |

## 外部事实与风险

### OpenSEO

事实：OpenSEO 的 Agent Skills 强调意图、SERP、证据、聚类和 `unknown`；其完整关键词指标与 SERP 能力依赖 MCP/DataForSEO 数据。

决定：借鉴工作流和输出约束，不复制 Web 应用、数据库或付费数据绑定。V1 的分数不能声称等价于 OpenSEO、Semrush 或 Ahrefs 的关键词机会分数。

参考：

- <https://github.com/every-app/open-seo>
- <https://github.com/every-app/open-seo/tree/main/.agents/skills>
- <https://raw.githubusercontent.com/every-app/open-seo/main/.agents/skills/keyword-research/SKILL.md>
- <https://raw.githubusercontent.com/every-app/open-seo/main/.agents/skills/keyword-clustering/SKILL.md>

### Steam

事实：应用详情和当前玩家数端点在本次审计时可返回数据；Steam 商店搜索结果端点可用于 Top Sellers 和 Popular New Releases，但搜索端点没有稳定公开契约。

决定：把具体 URL 和解析逻辑封装在 collector 中；超时、字段缺失或 HTML 变化时记录 `partial`/`failed`，仍生成报告。所有输出记录采集时间、市场和来源 URL。

### Google Trends

事实：Google Trends 数据是归一化样本，低量词可能显示 0；官方 Trends API 仍处于需申请的 alpha。`pytrends-modern` 是非官方库。

决定：V1 默认不安装、不启用 Trends。启用时只走标准 HTTP 模式，不自动登录、不使用代理或反检测浏览器。任何失败均降级为 `insufficient_data`。

参考：

- <https://support.google.com/trends/answer/4365533>
- <https://developers.google.com/search/apis/trends>
- <https://pypi.org/project/pytrends-modern/>

## 产品承诺边界

Dashboard 中的分数是研究优先级，不是搜索量、流量预测或收入预测。没有 SERP 证据的机会不得显示为“立即开发”；没有 Trends 数据不得自动显示为“零需求”。
