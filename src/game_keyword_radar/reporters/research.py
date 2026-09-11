"""V2.1 report uses stored reasons; never reranks history with today's settings."""
from __future__ import annotations
from game_keyword_radar.reporters.markdown import cell


def render_research(snapshot):
    lines=[f'# Game Keyword Radar V2.1 — {snapshot.generated_at.date()}', '',
           f'> Run `{snapshot.run_id}` · 分析 `{snapshot.analysis_version}` · 政策 `{snapshot.selection_policy_version}` · 配置 `{snapshot.policy_config_hash}`', '']
    if snapshot.is_demo:
        lines+=['> **合成示例**：游戏、数值、时间序列和问题都是测试素材，不是实时平台事实。','']
    lines+=['## 筛选漏斗','', '| 指标 | 数量 |','|---|---:|']
    titles={'raw_discovery_rows':'原始发现行','unique_entities':'去重实体','metadata_entities':'元数据补全实体',
            'monitored_entities':'轻量观测实体','eligible_entities':'符合通道条件','deep_selected':'已分配深度',
            'automatic_selected':'自动分配','manual_selected':'人工指定','validation_candidates':'可人工验证',
            'mature_without_trigger':'成熟无新触发','budget_deferred':'预算延后 / 冷却','unused_deep_slots':'未使用深度名额',
            'question_pages':'真实问题页面','content_proxy_pages':'内容代理页面','hypothesis_pages':'玩法假设页面'}
    for key,title in titles.items():
        lines.append(f'| {title} | {cell(snapshot.selection_summary.get(key))} |')
    lines+=['','名额是上限，不是必须填满。探索、人工指定和自动精选分别计数；游戏很大不等于现在有新机会。','',
            '## 来源状态','','| 来源 | 状态 | 可用实体 | 说明 |','|---|---|---:|---|']
    for s in snapshot.source_statuses:
        lines.append(f'| {cell(s.source)} | {s.state.value} | {s.records} | {cell(s.message)} |')
    names={e.slug:e.canonical_name for e in snapshot.entities}
    lanes={'new_release':'新游候选','rising':'增长线索','new_demand':'老游新需求','exploration':'探索候选'}
    for lane,title in lanes.items():
        lines+=['',f'## {title}','','| 游戏 | 去向 | WHY NOW | 增长状态 | 来源 |','|---|---|---|---|---|']
        rows=[d for d in snapshot.selection_decisions if d.primary_lane==lane]
        if not rows:
            lines+=['| 本通道为空 | 不以热榜填满 | — | — | — |']
        for d in rows:
            origin='人工' if d.entry_origin=='manual' else '自动'
            lines.append(f'| {cell(names[d.game_slug])} | {origin} / {d.decision} | {cell("；".join(d.reasons))} | {d.momentum.state} | {cell(", ".join(d.momentum.rising_sources) or "无持续增长确认")} |')
    lines+=['','## 仅观察 / 排除','','| 游戏 | 去向 | 原因 |','|---|---|---|']
    for d in snapshot.selection_decisions:
        if d.decision in {'monitor_only','excluded'}:
            lines.append(f'| {cell(names[d.game_slug])} | {d.decision} | {cell("；".join(d.reasons))} |')
    for g in snapshot.game_opportunities:
        d=g.selection
        lines+=['',f'## {cell(names[g.game_slug])} — 证据详情','',
                f'- 生命周期：{d.lifecycle.lifecycle}；{cell(d.lifecycle.reason)}',
                f'- 初筛时间：{d.as_of.isoformat()}；通道：{d.primary_lane or "monitor_only"}',
                f'- 入选依据：{cell("；".join(d.reasons))}',
                f'- 行动：{g.action}；{cell(g.action_reason)}',
                f'- 增长：{d.momentum.state}；持续性：{d.momentum.persistence}；传播：{d.momentum.breadth}',
                f'- 缺口：{cell("；".join(d.missing_evidence))}', '',
                '| 来源 / 指标 | 时间 | 当前 / 基线 | 绝对变化 | 百分比 | 比较层级 |',
                '|---|---|---|---:|---:|---|']
        for c in d.momentum.comparisons:
            lines.append(f'| {c.source} / {c.metric} | {c.period} | {c.current_value} / {c.baseline_value} | {c.absolute_delta} | {cell(c.percent_change)} | {c.comparison_kind} / {c.pair_count} 对 / qualified={c.qualified} |')
        lines+=['','### Page Graph / WHY THIS PAGE EXISTS','']
        pages=[p for p in snapshot.page_opportunities if p.game_slug==g.game_slug]
        if not pages:lines+=['暂无可解释页面节点，不用模板凑数。']
        for p in pages:
            lines += [f'#### `{cell(p.primary_keyword_hypothesis)}`','',
                f'- 预验证分：{p.score}/69；原始规则分：{p.raw_score}/100，不是成功率。',
                f'- 证据：{p.evidence_level}；真实问题 {p.question_count} / 内容代理 {p.content_proxy_count}',
                f'- 路由：{p.existing_site_fit or "待验证独立承接"}；维护：{p.maintenance_level}',
                f'- 价值：{cell(p.page_value)}', '- WHY THIS PAGE EXISTS：']
            for e in p.trigger_signals:
                lines.append(f'  - {cell(e.title)} — {e.source}；发布时间 {cell(e.published_at)}；采集 {e.captured_at.isoformat()}；{cell(e.url)}')
    lines+=['','## 边界与未验证项','',
        '- 缺失不是零；首次发现不是首次发售。Steam 商店国家不代表玩家地域。',
        '- Twitch 当前观看人数是注意力；YouTube 是内容代理；Trends 不是搜索量。',
        '- 单点、部分样本、低基数和缓存复用不冒充持续增长；比较实际范围见快照。',
        '- 没有人工 Semrush / live SERP evidence，不自动 Build；人工记录独立保存。',
        '- 阈值、频率和名额比例都是待校准规则，不是已回测的爆发预测。']
    if snapshot.errors:lines+=['','## 本次错误','',*[f'- {cell(x)}' for x in snapshot.errors]]
    return '\n'.join(lines)+'\n'
