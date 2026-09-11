# V2 RC1 交付验收记录

日期：2026-09-11。版本：`2.0.0rc1`。

## 结论

**代码开发和本次离线验收完成，发布为 RC1；不宣称正式 V2 的全部联网验收通过。**

Steam / Twitch / YouTube 联合真实扫描未通过当前环境验收。缺少 Twitch Client ID / Secret 和 YouTube API Key；Steam 请求实际发生连接错误和超时。失败记录见升级包 `evidence/live-acceptance.json`。没有用 Demo、缓存造数或假接口代替成功扫描。

## 已执行的检查

| 检查 | 实际结果 | 边界 |
|---|---|---|
| 增量升级工具自测 | 11 passed | 预检、冲突拦截、备份、回滚、幂等、安全路径与用户数据保留 |
| Python 离线测试 | 118 passed | 新增 V2 测试与 V1 兼容契约；未声称原仓库每个测试文件在完整 Git clone 中原样执行 |
| 覆盖率 | 85% | 本次工作目录的合并语句/分支口径；不是整个原仓库的覆盖率 |
| Chromium 界面与 ASGI 集成 | 14 checks passed，0 JavaScript page errors | 合成数据，不是外部 API 联网验收 |
| 桌面 / 手机 / 平板 | 1440 / 390 / 768px | 实际浏览器渲染；列表、详情、队列、历史、来源与弹窗无水平溢出 |
| CLI / JS | 模块 CLI help 与 JavaScript 语法检查通过 | Python 环境已装依赖；没有完成 wheel 构建或全新虚拟环境安装验收 |
| 真实三源扫描 | not_passed | Steam 网络不可达；Twitch / YouTube 未提供凭据 |

测试执行环境为 Python 3.13.5、pytest 9.0.2。项目声明 Python >=3.11，开发依赖仍保留 pytest >=8.3,<9；本次并未执行 Python 3.11 与 pytest 8 的独立版本矩阵。建议本地安装项目依赖后再执行 `python -m pytest`。

浏览器的直接本机 HTTP 导航被运行环境的管理员策略阻止；没有绕过该限制。改为在 Chromium 中运行实际 HTML/CSS/JavaScript，由页面 fetch 经进程内 ASGI TestClient 桥接至真实后端路由。因此这些检查证明 DOM、前端交互、路由和持久化集成，不证明真实浏览器网络、CSP 执行路径或第三方服务可用。

## 测试覆盖内容

来源缓存、预算、OAuth 刷新、分页去重、样本下限、单主播集中度、RSS 解析、缺凭据/上游失败降级、实体匹配与 ID 冲突、缺数据不计零、页面证据触发、codes/tier-list 限制、现有站点优先、人工验证门禁与零搜索量、快照只读兼容、市场/Demo 隔离、缓存观测时间、24h/7d 时间窗口、CSV/Markdown 导出、浏览器队列持久化及移动端布局。

界面检查证据和终端原始输出在升级包 `evidence/`。截图中的游戏、问题和数值均是明确标注的合成数据。

## 对方案的实施状态

M0–M7 的主要代码路径已经实现。以下不是已完成能力：

- 官方 Trends Alpha：仅留有获授权适配器的注入接口，未取得权限、未接入真实官方端点。
- Reddit 游戏专属 subreddit 自动发现：本版通过人工核实的实体配置接入；默认通用社区 RSS，不靠猜名称创建映射。
- 第三方 API 的真实访问稳定性、实际 OAuth 权限和 YouTube 项目额度：必须在用户本机通过小规模扫描确认。
- 不自动验证人工录入的 Semrush/SERP 内容真伪；门禁检查的是证据记录完整性。

## 在本机完成最后验收

先应用升级包、安装依赖，并在未覆盖旧配置的前提下填写 `.env`。然后运行：

```bash
python -m pytest
python scripts/live_acceptance.py
```

只有真实三源均产生可用观测，验收脚本才退出 `0`。退出 `2` 表示三源条件未全部满足；输出的 `source_statuses` 给出逐源原因。运行前可用 `game-radar sources` 检查配置，但它只表示配置就绪，不等于已联网通过。

首次扫描没有 24h/7d 历史样本很正常；应积累真实快照后再检查变化，不能把“尚无历史”解释成“没有增长”。
