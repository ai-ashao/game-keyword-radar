# Game Keyword Radar

Game Keyword Radar 是面向单人 SEO 产品构建者的本地研究工作台。它帮助用户从 Steam 游戏中筛出值得进一步验证的工具、攻略和数据库类页面机会。

## 文档真源

- 产品范围与事实边界：[`docs/AUDIT.md`](docs/AUDIT.md)
- 当前实施计划与验收标准：[`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md)
- 安装和使用：[`README.md`](README.md)

原始 PDF 只作为历史输入，不再作为实施真源。

## 当前边界

- 本地 Web Dashboard 是主要入口。
- Python CLI 和数据模块是可重复执行的底层能力。
- Codex Skill 负责组织研究流程和补充人工可核验的 SERP 证据。
- V1 不含 Twitch、数据库、登录、部署、付费 API 和自动发布。
- V1.1 已加入本地历史快照回看与变化对比；它只表示两次扫描差异，不代表搜索需求趋势。
- 当前阶段不要求录入 SERP，所有未补证据的机会继续标记为 `needs_validation`。
