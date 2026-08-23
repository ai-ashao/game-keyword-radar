# Game Keyword Radar 技术架构

本文描述当前本地优先实现。产品范围与运行方式见根目录 `README.md`，阶段边界见 `IMPLEMENTATION_PLAN.md`。

## 技术栈

- Python 3.11+，以 `src/game_keyword_radar` 作为可安装包。
- Typer 提供 `game-radar` 命令行入口。
- FastAPI、Jinja2 和 Uvicorn 提供仅绑定本机的 Dashboard。
- Pydantic 模型承载候选、证据、来源状态、评分和扫描快照。

## 模块责任

| 模块 | 责任 |
|---|---|
| `cli.py` | `serve`、`scan`、`demo`、`report` 命令入口 |
| `config.py` | 环境变量和运行参数 |
| `pipeline.py` | 候选发现、证据采集、关键词生成和评分流水线 |
| `models.py` | 数据契约、来源状态、置信度和机会状态 |
| `storage.py` | 原始数据、标准化快照、历史索引和 latest 指针的本地持久化 |
| `history.py` | 双快照可比性检查，以及游戏和关键词机会变化计算 |
| `web/` | Dashboard 路由、模板和静态资源 |
| `sources/` | Steam 与可选 Google Trends 适配器 |
| `reporting.py` | Markdown 研究报告输出 |

## 数据流

`scan` 从 Steam 发现候选并保存原始响应，流水线把来源数据映射为强类型候选与证据，再生成可追溯评分和机会项。处理后的快照写入 `data/processed`，`data/latest.json` 供 Dashboard 读取，报告写入 `reports`。

Dashboard 通过 `/api/snapshots` 读取历史索引，通过 `/api/snapshots/{run_id}` 回看单次扫描，通过 `/api/compare` 对比两个快照。对比只使用已保存的本地数据，不调用 Steam、Trends 或 SERP。历史快照缺少早期版本的可推导字段时，模型会进行只读兼容恢复，不改写原文件。

## 可靠性边界

- 机会分是研究排序，不是搜索量或流量预测。
- Steam 页面接口和非官方 Trends 采集均可能变化；失败必须写入 `SourceStatus`，缺失数据不能当作零需求。
- Google Trends 默认关闭，主流程必须能在离线测试和无 Trends 配置时运行。
- 当前不包含账号、云数据库、自动 SERP 抓取或自动建站。
- 没有 SERP 证据时，机会状态保持 `needs_validation`，研究优先级上限为 69；历史变化不改变这一规则。
