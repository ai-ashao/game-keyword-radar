# Changelog

## 2.2.0rc1 - 2026-09-12

- 新增零新增凭据的数据源分层与降级规则；
- 实体解析改为平台 ID 优先，同名跨平台或同平台不同 ID 只生成待确认建议；
- 历史增长仅允许同 provider / metric scope / window / market 的可比观测参与；
- Sitemap / Sitemap Index 增量发现采用首次 baseline、部分覆盖不推断删除；
- 新增 Google Trends Trending RSS 与持久化 Discovery Inbox，候选默认保持 unresolved；
- Page Graph 从 intent 粗粒度升级到 task-level cluster；
- 增加验证包导出、Semrush CSV 与 Google Trends CSV 追加式证据导入；
- YouTube 在既有 API Key 缺失时可选使用本机已安装 yt-dlp 做 Deep best-effort 搜索；
- SullyGnome 等明确禁止 scraping 的第三方统计站不自动抓取；Roblox 保持 Experimental。

## 0.2.0 - 2026-08-23

- 新增历史扫描索引、快照回看和双快照变化对比；
- 新增游戏信号和关键词机会变化面板；
- 报告下载跟随选中的历史快照；
- 兼容缺少可推导 `raw_score` 的早期本地快照；
- 首次启动没有快照时禁用报告下载，并为静态资源加入版本化缓存键；
- 保持 SERP 人工输入关闭、69 分上限和 `needs_validation` 规则不变。

## 0.1.0 - 2026-08-16

- 发布本地 Web Dashboard、Steam 采集、规则评分、Markdown 报告和 Codex Skill；
- Google Trends 作为默认关闭、可失败降级的可选来源。
