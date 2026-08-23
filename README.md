# Game Keyword Radar

Game Keyword Radar 是一个运行在本地浏览器中的游戏关键词研究 Dashboard。它从 Steam 发现候选游戏，用可追溯的规则生成工具、攻略和数据库类关键词，并明确告诉你下一步还需要验证什么。

> 机会分是研究优先级，不是搜索量或流量预测。

## 快速开始

需要 Python 3.11 或更高版本。macOS 自带的 `python3` 可能仍是 3.9，请先确认版本；如果已安装 Python 3.12，可把下面的 `python3` 替换为 `python3.12`。

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
game-radar demo
game-radar serve
```

打开 <http://127.0.0.1:3000>。

## 真实扫描

```bash
game-radar scan --limit 10
```

扫描结果保存在：

- `data/raw/`：采集结果；
- `data/processed/`：标准化快照；
- `data/latest.json`：Dashboard 当前读取的数据；
- `reports/`：Markdown 报告。

也可以在 Dashboard 中点击“扫描 Steam”。

## 扫描变化

完成至少两次扫描后，Dashboard 会自动显示“扫描变化”：

- 切换任意历史快照，回看当时的游戏与关键词机会；
- 对比两个快照中的新增、离场和信号变化；
- 查看机会研究优先级的上升、下降、新增与移除；
- 下载当前选中快照对应的 Markdown 报告。

这些变化来自本机保存的扫描快照，不是搜索量或需求趋势。当前无需录入 SERP；没有实时 SERP 证据时，机会仍保持 `needs_validation`，最高 69 分。

## 可选 Google Trends

Google Trends 默认关闭，不影响主流程：

```bash
python -m pip install -e '.[trends]'
game-radar scan --limit 5 --with-trends
```

这是非官方采集路径，可能出现 429、空响应或接口变化。程序会记录 `insufficient_data`，不会把缺失值解释成零需求。

## 常用命令

```bash
game-radar --help
game-radar serve --port 3000
game-radar scan --limit 10
game-radar demo
game-radar report
```

## 配置

复制 `.env.example` 为 `.env`，或设置同名环境变量。默认市场为美国、Steam 语言为英语，服务仅绑定本机地址。

## 当前不做

V1 不包含 Twitch、数据库、登录、云部署、付费关键词 API、自动 SERP 抓取和自动建站。当前实现见[功能状态](docs/FEATURE_STATUS.md)和[技术架构](docs/ARCHITECTURE.md)；完整 V1 决策基线见 [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md)，历史对比增量见 [`docs/V1_1_HISTORY_PLAN.md`](docs/V1_1_HISTORY_PLAN.md)。

## 数据源风险

Steam 商店搜索结果接口不是稳定公开契约，字段可能改变。程序会保存来源状态并继续生成部分报告。Google Trends 是可选的非官方采集路径。

## 测试

```bash
pytest
```

默认测试全部离线，不访问真实平台。
