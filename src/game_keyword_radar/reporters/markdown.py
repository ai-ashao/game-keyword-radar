from __future__ import annotations
from game_keyword_radar.models import ScanSnapshot

def cell(value):
    return str(value if value is not None else 'unavailable').replace('|','\\|').replace('\n',' ').replace('\r',' ')

class MarkdownReporter:
    def __init__(self,settings):self.settings=settings
    def render(self,snapshot:ScanSnapshot):
        if snapshot.analysis_version == "2.1":
            from game_keyword_radar.reporters.research import render_research
            return render_research(snapshot)
        lines=[f'# Game Keyword Radar - {snapshot.generated_at.date().isoformat()}','',
            f'> Run `{snapshot.run_id}` | Market `{snapshot.country}` | Language `{snapshot.language}`','']
        if snapshot.is_demo:lines += ['> **示例数据**：游戏、数值和问题均为合成测试素材，不是实时平台事实。','']
        lines += ['## 扫描摘要','',f'- 游戏候选：{len(snapshot.entities) or len(snapshot.games)}',
            f'- 页面/工具机会：{len(snapshot.page_opportunities) or len(snapshot.opportunities)}',f'- 扫描状态：{snapshot.state.value}','',
            '## 数据来源状态','','| Source | State | Records | Message |','|---|---|---:|---|']
        for s in snapshot.source_statuses:lines.append(f'| {s.source} | {s.state.value} | {s.records} | {cell(s.message)} |')
        if snapshot.entities:
            lookup={e.slug:e for e in snapshot.entities}
            lines += ['','## Top Game Opportunities','','| Game | Demand | Coverage | Pages | Action |','|---|---:|---:|---:|---|']
            for g in snapshot.game_opportunities:
                lines.append(f'| {cell(lookup[g.game_slug].canonical_name)} | {cell(g.demand.score)} | {g.demand.coverage:.0%} | {len(g.page_ids)} | {g.action} |')
            for g in snapshot.game_opportunities:
                lines += ['',f'## {cell(lookup[g.game_slug].canonical_name)}','',g.action_reason,'',
                    '| Platform | Status | Captured at | Metrics |','|---|---|---|---|']
                for s in snapshot.platform_signals:
                    if s.game_slug!=g.game_slug:continue
                    lines.append(f'| {s.source} | {s.status.value} | {s.captured_at.isoformat()} | {cell(s.metrics)} |')
                    for note in s.notes:lines.append(f'\n> {cell(note)}')
                lines += ['','### Page Graph / WHY THIS PAGE EXISTS','']
                for p in snapshot.page_opportunities:
                    if p.game_slug!=g.game_slug:continue
                    lines += [f'#### `{cell(p.primary_keyword_hypothesis)}`','',
                        f'- 路径：`{p.path}`；页面类型：{p.page_type}',f'- 待验证分：{p.score}/69；研究原始分：{p.raw_score}/100',
                        f'- 证据层级：{p.evidence_level}；状态：needs_validation',f'- 难度：{p.build_difficulty}；维护：{p.maintenance_level}',
                        f'- 现有站点：{p.existing_site_fit or "尚无匹配"}',f'- 页面价值：{p.page_value}', '- 触发证据：']
                    for e in p.trigger_signals:
                        lines.append(f'  - [{cell(e.title)}]({e.url}) — {e.source} / {e.captured_at.isoformat()}' if e.url else f'  - {cell(e.title)} — {e.source}')
        else:
            lines += ['','## 机会排名（V1 只读兼容）','','| Game | Keyword | Raw score | Score | Status |','|---|---|---:|---:|---|']
            for o in snapshot.opportunities:
                lines.append(f'| {cell(o.game_name)} | {cell(o.keyword.keyword)} | {o.raw_score} | {o.score}/69 | {o.status.value} |')
            lines += ['','关键词由 Steam 元数据和规则生成，不代表已观察到的搜索需求。']
        lines += ['','## 数据局限','',
            '- 缺失值不是零；各平台指标不直接相加。',
            '- Steam 当前玩家不是日均在线；Twitch 分页可能不完整，见 sampling_complete。',
            '- YouTube / Reddit 仅为有限样本；视频播放、直播观看和 Trends 指数不是 Google 月搜索量。',
            '- 本地快照变化不等于搜索量预测。评分仅供研究排序，不是成功率。',
            '- Trends 是相对方向信号，不是搜索量；缺少 live SERP evidence 时不得立即建站。',
            '- 没有人工 Semrush + SERP 证据，不得视为立即建站。验证记录独立保存，不改写扫描快照。',
            '- Steam 商店公开端点和 Reddit RSS 可能变化或拒绝访问。']
        if snapshot.errors:lines += ['','## 本次错误','',*[f'- {cell(e)}' for e in snapshot.errors]]
        return '\n'.join(lines).rstrip()+'\n'
    def save(self,snapshot):
        from game_keyword_radar.storage import SnapshotStore
        if not SnapshotStore._safe_run_id(snapshot.run_id):raise ValueError('Invalid run ID')
        self.settings.reports_dir.mkdir(parents=True,exist_ok=True)
        path=self.settings.reports_dir / f'{snapshot.run_id}-game-keywords.md'
        path.write_text(self.render(snapshot),encoding='utf-8')
        return path
