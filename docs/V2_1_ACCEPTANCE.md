# Game Keyword Radar V2.1 — 本轮验收记录

版本：**2.1.0rc1**。分析2.1，默认政策selection-2.1-r1。
基线：99f7f9e42cae7967f53ffde3c7b339eea08a9963（用户GitHub main，已通过连接器读取确认）。
记录时间：2026-09-11T08:13:02.365920+00:00。
本次只交付代码升级包，没有提交或推送 GitHub。

## 已执行的检查

| 检查 | 本轮结果 | 证据与口径 |
|---|---|---|
| 本地 Python 回归 | **203 passed** | regression.xml / regression.txt；包含73个本轮新增V2.1参数化回归、118个本地V1兼容/V2回归、恢复的12个原仓库Web测试 |
| 升级脚本单元检查 | **15 passed** | upgrade-tests.xml / .txt；保护路径、冲突、哈希、符号链接、幂等、强制备份、回滚与后续编辑保护 |
| 整包应用／回滚 | 见bundle-roundtrip.json | 对重建的基线副本应用整包；逐文件核对；保留哨兵.env、radar.toml、data、reports；验证重复应用与回滚 |
| Chromium离线集成 | **11项通过，JS页面错误0** | browser/browser-results.json；真实Chromium执行真实HTML/CSS/JS，通过测试绑定调用进程内ASGI，不是浏览器直接HTTP或真实上游 |
| 实际本地HTTP服务 | 通过 | http-smoke.json；Python HTTP连接Uvicorn，health2.1.0rc1、主页、策略API、响应安全头 |
| JavaScript与Python语法 | 通过 | node --check app.js；compileall src/scripts |
| 示例TOML、CLI帮助 | 通过 | 解析完整配置示例、六条命令帮助。新配置段被实际Settings读取 |

**测试范围说明：**当前执行容器不能直接克隆GitHub。源码以本会话已交付V2 RC1的47文件覆盖层重建，补入已读取的5个未修改原模块及原test_web.py；新增和修改的代码在此基础上执行。203不是“在全新克隆的完整仓库中跑完所有原始测试”的声明。未挂载的其他V1原测试没有在这轮重新运行；升级包不删除它们。用户安装后仍应执行项目自己的完整 `python -m pytest`。上一轮118个测试已在本轮重跑，不是直接搬用旧日志。

本机测试版本：Python3.13、pydantic2.13.4、FastAPI0.128.2、httpx0.28.1、pytest9.0.2。项目仍要求Python3.11+；3.11/3.12未在本容器另起矩阵。由于hatchling未安装且没有外部包网络，**wheel/editable打包安装过程未在此环境验证**，直接以PYTHONPATH=src运行源代码测试。交付为升级源码，不是预编译wheel。

## 确认修正的核心行为

- 已知成熟高规模而没有新触发的样本留在monitor_only，不占自动Deep。
- 新游未出现在Twitch Top Games也会被单游戏定向观察；观察和历史比较早于Deep选择。
- 新游、增长、近期具体任务、探索独立分配4/3/1/2；允许空位，探索上限、单实体去重、冷却和人工预算已测。
- 首次扫描不等于发行；新平台日期不覆盖已保存更早的发行证据；试玩／未知／provisional区分。
- 低基数、缓存复用、口径变化、部分样本、单主播集中不冒充持续增长；24h/7d配对用例是合成回放。
- 真实问题与YouTube内容代理分开；旧问题首次采到不当新需求；没有人工验证不允许Build。
- Twitch-only历史摘要1/1，unchanged分数变化0，排名／页面／规则差异分开。
- 轻量监测使用独立快照与共享锁，不覆盖完整报告，不补造休眠期样本。

## 浏览器范围与截图

浏览器直接导航HTTP被当前Chromium管理员策略阻止，未修改或关闭该限制。使用离线set_content + 本地CSS/JS + 明确的ASGI测试绑定完成DOM交互验证；HTTP服务另用Python客户端验证。这两项不能合并宣称“浏览器真实端到端联网验收”。

截图全部为**合成示例**：overview-desktop.png、growth-detail-desktop.png、mature-observation-desktop.png、overview/detail-mobile.png、overview/detail-tablet.png。已检查桌面、390px手机、768px平板；未出现横向溢出或JS页面错误。

## 真实来源验收：未通过

实际尝试run_id：`2026-09-11T08-11-13Z-a2ad4579`，不是Demo。
Twitch凭据配置：False；YouTube凭据配置：False。
Steam列表请求返回ConnectError／ConnectTimeout；Twitch与YouTube缺凭据，没有伪造回退数据。

L1核心双源与映射：未通过。L2真实多次／跨日窗口：未取得。L3真实YouTube页面证据：未通过。L4真实入选及近门槛样本的人工有用性：待验证。空输入时没有误入者不是L4成功证明。

所以保持RC。`scripts/live_acceptance.py` 已加强为真实Steam玩家＋Twitch定向观测＋双源同实体＋YouTube出处门禁；仅Token、排名、HTTP200或模板节点不足以通过。单次联网通过不自动宣称预测有效。

## 明确不包含的能力

没有自动全网核实首发、自动发现所有专属社区、全市场历史库、付费SERP、云端定时任务、自动Build或爆发概率预测。策略编辑器只作用于当前服务会话；永久配置仍用radar.toml。需要持续观察的榜外成熟游戏可手动加入观察列表，不能假设所有成熟游戏都已被监测。

## 重现

```bash
python -m pytest
python scripts/live_acceptance.py
# 可选Playwright；在隔离测试目录执行，浏览器样例写入为合成数据
python scripts/browser_smoke.py --asgi-fixture --chromium /你的Chromium可执行文件 --output evidence/browser
```

升级脚本只读取需要替换的代码并备份，不访问凭据，不操作Git，不覆盖用户业务数据。使用前停止运行中的本地服务。
