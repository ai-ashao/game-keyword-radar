from __future__ import annotations

from pathlib import Path

from game_keyword_radar.config import Settings
from game_keyword_radar.models import ScanSnapshot


class MarkdownReporter:
    def __init__(self, settings: Settings):
        self.settings = settings

    def render(self, snapshot: ScanSnapshot) -> str:
        lines = [
            f"# Game Keyword Radar - {snapshot.generated_at.date().isoformat()}",
            "",
            f"> Run `{snapshot.run_id}` | Market `{snapshot.country}` | Language `{snapshot.language}`",
            "",
        ]
        if snapshot.is_demo:
            lines.extend(
                [
                    "> **示例数据**：本报告只用于体验界面，数值不是实时平台事实。",
                    "",
                ]
            )
        lines.extend(
            [
                "## 扫描摘要",
                "",
                f"- 游戏候选：{len(snapshot.games)}",
                f"- 页面/工具机会：{len(snapshot.opportunities)}",
                f"- 扫描状态：{snapshot.state.value}",
                f"- 数据错误：{len(snapshot.errors)}",
                "",
                "## 数据来源状态",
                "",
                "| Source | State | Records | Message |",
                "|---|---|---:|---|",
            ]
        )
        for status in snapshot.source_statuses:
            lines.append(
                f"| {status.source} | {status.state.value} | {status.records} | {status.message} |"
            )
        lines.extend(
            [
                "",
                "## 机会排名",
                "",
                "| Rank | Game | Keyword | Type | Score | Status | Missing evidence |",
                "|---:|---|---|---|---:|---|---|",
            ]
        )
        for index, opportunity in enumerate(snapshot.opportunities, 1):
            missing = ", ".join(opportunity.missing_evidence)
            lines.append(
                f"| {index} | {opportunity.game_name} | {opportunity.keyword.keyword} | "
                f"{opportunity.keyword.page_type} | {opportunity.score:.1f} | "
                f"{opportunity.status.value} | {missing} |"
            )
        for game in snapshot.games:
            game_opportunities = [
                item for item in snapshot.opportunities if item.app_id == game.app_id
            ]
            lines.extend(
                [
                    "",
                    f"## {game.name}",
                    "",
                    f"- Steam signal: {game.game_signal_score:.1f}/100",
                    f"- Data completeness: {game.data_completeness:.0%}",
                    f"- Understanding confidence: {game.understanding_confidence.value}",
                    f"- Inferred mechanics: {', '.join(game.mechanics) or 'unknown'}",
                    f"- Store: {game.store_url}",
                    "",
                    "### 候选页面",
                    "",
                ]
            )
            for opportunity in game_opportunities:
                lines.extend(
                    [
                        f"#### {opportunity.keyword.cluster}: `{opportunity.keyword.keyword}`",
                        "",
                        f"- 页面类型：{opportunity.keyword.page_type}",
                        f"- 理由：{opportunity.keyword.rationale}",
                        f"- 规则原始分：{opportunity.raw_score:.1f}/100",
                        f"- 待验证分：{opportunity.score:.1f}/69（预留 SERP/需求验证空间）",
                        f"- 待补证据：{', '.join(opportunity.missing_evidence)}",
                        "- 下一步：",
                        *[f"  - {step}" for step in opportunity.next_steps],
                        "",
                    ]
                )
        lines.extend(["## 数据局限", ""])
        limitations = [
            "Steam 商店搜索端点不是稳定公开契约。",
            "关键词由 Steam 元数据和规则生成，不代表已观察到的搜索需求。",
            "Google Trends 是可选的相对方向信号，不是搜索量。",
            "V1 不自动抓取 SERP，因此所有机会都需要人工验证。",
        ]
        lines.extend(f"- {item}" for item in limitations)
        if snapshot.errors:
            lines.extend(["", "## 本次错误", ""])
            lines.extend(f"- {error}" for error in snapshot.errors)
        return "\n".join(lines).rstrip() + "\n"

    def save(self, snapshot: ScanSnapshot) -> Path:
        self.settings.reports_dir.mkdir(parents=True, exist_ok=True)
        path = self.settings.reports_dir / f"{snapshot.run_id}-game-keywords.md"
        path.write_text(self.render(snapshot), encoding="utf-8")
        return path
