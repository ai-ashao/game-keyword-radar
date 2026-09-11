"""Conservative release classification. Local first_seen is never a release date."""
from __future__ import annotations
from datetime import datetime, timezone
from game_keyword_radar.config import Settings
from game_keyword_radar.models import GameEntity
from game_keyword_radar.research_models import LifecycleAssessment


def classify_lifecycle(entity: GameEntity, as_of: datetime, settings: Settings) -> LifecycleAssessment:
    if as_of.tzinfo is None:
        raise ValueError("as_of must contain a timezone")
    day = as_of.astimezone(timezone.utc).date()
    result = LifecycleAssessment(as_of=as_of, release_stage=entity.release_stage)
    if entity.release_stage in {"demo", "upcoming"}:
        result.lifecycle = "preview"
        result.reason = "试玩 / 预发布观察，不与正式版玩家规模混算"
        return result
    if entity.release_date_conflict:
        result.reason = "发行来源存在冲突，保留探索并等待核实"
        return result
    public = entity.first_public_playable_at
    if public is not None and entity.release_date_basis in {"verified_public", "manual_verified"} and entity.release_sources:
        age = (day - public).days
        if age < 0:
            result.reason = "首次公开可玩日期在未来，当前不能确认已发行"
            return result
        result.age_days = age
        result.recency_status = "verified"
        result.lifecycle = "new_release" if age <= settings.selection.new_release_days else "established"
        result.recent_eligible = result.lifecycle == "new_release"
        result.reason = f"有来源的首次公开可玩发行：{public.isoformat()}（{age}天）"
        result.evidence_ids = [f"public-release:{public.isoformat()}", *entity.release_sources]
        return result
    # A platform's earlier playable release is enough to disprove a *new* global release.
    facts = [(platform, fact) for platform, fact in entity.platform_release_dates.items()
             if fact.date is not None and fact.source_url and fact.basis != "unknown"
             and (fact.checked_at is None or (fact.checked_at.tzinfo and fact.checked_at <= as_of))]
    older = [(platform, fact) for platform, fact in facts
             if fact.precision == "day" and (day - fact.date).days > settings.selection.new_release_days]
    if older:
        platform, fact = min(older, key=lambda pair: pair[1].date)
        result.lifecycle = "established"
        result.platform_age_days = (day - fact.date).days
        result.recency_status = "verified"
        result.reason = f"{platform}已有早于新游窗口的发行记录；不推定全球首发日期"
        result.evidence_ids = [f"release:{platform}:{fact.date.isoformat()}", str(fact.source_url)]
        return result
    events = {str(event.get("type", event.get("kind", ""))) for event in entity.release_events}
    if events & {"port", "rename", "early_access_exit", "rebrand"}:
        result.reason = "已知移植 / 改名 / 转正式事件，不能用新平台日期重置游戏年龄"
        return result
    recent = [(platform, fact) for platform, fact in facts
              if fact.precision == "day" and 0 <= (day - fact.date).days <= settings.selection.new_release_days]
    if recent and entity.release_stage in {"released", "early_access"}:
        platform, fact = min(recent, key=lambda pair: pair[1].date)
        result.platform_age_days = (day - fact.date).days
        result.recency_status = "provisional_platform_date"
        result.recent_eligible = True
        result.reason = f"{platform}平台近期发行，全球首次公开发行待核实"
        result.evidence_ids = [f"release:{platform}:{fact.date.isoformat()}", str(fact.source_url)]
    else:
        result.reason = "发行阶段 / 精确日期尚未核实；首次扫描时间不是发行时间"
    return result
