# Game Keyword Radar V2.1 · 2.1.0rc1

**先有入选理由，再分配研究预算。** 本地优先的游戏需求雷达与关键词／页面研究工作台，不是热榜聚合，也不预测爆款概率。

发布状态：**RC**。新增筛选逻辑已通过本轮离线回归和 Chromium 离线 DOM/ASGI 集成检查；真实 Steam + Twitch + YouTube 联合链路、跨日窗口和人工业务有用性尚未通过本环境验收。见 `docs/V2_1_ACCEPTANCE.md`，不把 Demo 当作实时数据。

## 启动与升级

Python 3.11+，macOS / Linux；本地跨进程锁使用 `fcntl`，不支持 Windows 原生 Python。已有项目请先停止服务，使用交付包的 `apply_upgrade.py --check/--apply`，不要覆盖本机 `.env`、`radar.toml`、data 或 reports。

```bash
cd game-keyword-radar
# 已有虚拟环境就继续使用；没有时才创建。
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
test -f .env || cp .env.example .env
test -f radar.toml || cp radar.example.toml radar.toml
game-radar serve
```

打开 `http://127.0.0.1:3000`。先体验明确标记的合成示例；要查看当前数据，需要点击一次新的真实扫描。旧快照只读兼容，不会被追溯改写为 V2.1 判断。服务仅绑定回环地址，没有登录系统，不应暴露到公网。

## 这次修正了什么

Steam 近期发行入口／Twitch 类别／本地观察项 → 游戏身份和发行阶段 → Steam / Twitch 定向轻量观测 → **先比较历史** → 四通道准入与预算 → YouTube / Reddit / 可选 Trends → Page Graph → 人工 Semrush / SERP。

已知成熟游戏只有在线人数多、观看人数多时保留观察，不靠旧 Demand 分占据今日机会。新游不在 Twitch Top Games，也可按游戏 ID 定向观察。日期未知、低基数、单主播集中等有解释的弱信号保留探索，而不是要求五源齐全后才入选。

默认 Deep=10 时为新游4、增长3、老游新需求1、探索2。小预算采用最大余数法；空缺有序复用，自动探索最多 `ceil(0.4*N)`，可以留下空位。人工强制研究单独标记并占本轮预算。重复触发的自动 Deep 冷却24小时；具体阈值是待校准的初始规则。

## 浏览器日常工作流

“今日机会”显示分组、WHY NOW、来源数、增长状态和页面证据；“成熟／观察”“预算延后”“全部实体”保留未精选条目。游戏详情中的旧 Demand 是折叠诊断，不代表爆发概率。

“观察与监测”可以保存人工游戏种子、来源 URL、观察标签、发行／别名／平台 ID 纠正。新种子在下一轮参与发现；不会自动抓取用户粘贴的任意 URL。人工发行与问题事实必须提供理由与出处，具体问题还需要发布时间。

该页可启停本地监测，或只运行一轮。默认不自动开启。只有本地服务存活且电脑没有休眠时才采样；恢复后只做下一轮实际请求，记录缺口，不补造过去样本。轻量监测不调用 YouTube / Reddit / Trends，也不覆盖最近完整报告。

策略编辑器只改变**当前服务会话**，重启不持久化。长期配置请编辑 `radar.toml`。未知段名、未知字段、非法配额比例会报错。

## 数据来源与凭据

`.env` 中保留原有 `TWITCH_CLIENT_ID`、`TWITCH_CLIENT_SECRET`、`YOUTUBE_API_KEY`。Steam 不需要这三个值；Twitch 或 YouTube 未配置只会降级，不以缺失判定零需求。App Token 的缓存和过期更新保留在本地私有目录，密钥不进入前端、快照或报告。

Twitch 观众数／频道数是采集窗口观测；未完成分页时标成样本下限。类别排名与单游戏流观测分开，缺席 Top K 不等于0观众。Top1 / Top3、非头部观众、频道ID集合用于解释广度，不是搜索量。

Reddit RSS 保留 best-effort 与显式专属社区配置；403 / 429 不绕过限制。Trends Legacy 是可选依赖；Official Provider 仍需授权适配器，并未自动开通官方 Alpha。YouTube 视频属于内容代理，不能计作真实玩家提问。

## 历史与判断

首次本机发现与首次公开发行分开。平台近期发行但全球首发未知可暂入新游通道；明确旧发行、移植、改名或转正式事件不能重置游戏年龄。历史 app 再次返回较新的发行日期时保留旧来源记录。

默认轻量周期2小时；合格24h/7d比较使用6小时窗口、至少3个独立观测、跨度至少4小时、一对一时间匹配与中位数。低基数百分比为空；单点、日内苗头和部分样本不认证持续增长。无历史为 unknown，不写 stable。跨平台冲突为 mixed，不平均抵消。

V1 / V2 旧快照继续只读。V2 历史计数改为 entities/page_opportunities，Twitch-only 不再漏计；unchanged、分数变化、排名变化和页面变化分别统计；策略、覆盖或口径改变时不解释为需求涨跌。

## 存储与预算

`data/processed` 是完整报告；`data/observations/<date>` 是独立轻量快照，`latest-monitoring.json` 不覆盖 `latest.json`。`selection/<run>.json` 保存准入和分配，`annotations` 与 `validation` 保存人工记录；Demo / Live 分开。无可用实体的失败不覆盖最近有效 Live。

Steam、Twitch 默认每轮各260次网络尝试预算，失败和 Token 请求计入，缓存命中不计入。来源列表、元数据和活动监测池分别计数，详情补全优先近期发行入口。YouTube 沿用本机调用次数和配额日账本。来源失败不会伪造成功数据。

## CLI 与验收

```bash
game-radar scan --deep 10 --selection-profile opportunity
game-radar monitor-once
game-radar candidates --lane exploration
game-radar explain GAME_SLUG --run-id RUN_ID
game-radar sources
python -m pytest
python scripts/live_acceptance.py
```

`game-radar sources` 仅说明配置，不证明真实 API 成功。实时验收脚本只有 Steam 玩家、Twitch 定向观测、一个双源映射实体以及真实 YouTube 出处都存在才通过；L2 跨日和 L4 人工有用性仍另记。

浏览器离线集成（可选安装 Playwright，使用本机 Chromium）与实际浏览器 HTTP 验收是两件事，见 `scripts/browser_smoke.py --help`。默认 pytest 离线；本轮具体日志与限制见验收记录。

## 已保留的边界

所有页面仍需人工 Semrush / SERP 验证，预验证分上限69。没有证据不自动 Build；粘贴表单只校验记录完整性，不声称系统替人核实了搜索结果。

本仓库不生成小黑盒／公众号／社媒文章，不依赖 `game-content-radar`，不绑定 ShipLean，不引入云数据库或用户系统。全网首发时间考证、全量 Twitch 数据、自动因果解释、预测准确率和自动专属社区发现均不是已交付能力。

规格：`docs/V2_1_PLAN.md`；实施映射：`docs/V2_1_IMPLEMENTATION.md`；验收：`docs/V2_1_ACCEPTANCE.md`。
