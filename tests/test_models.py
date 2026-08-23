from __future__ import annotations

import pytest
from pydantic import ValidationError

from game_keyword_radar.config import Settings
from game_keyword_radar.demo import build_demo_snapshot
from game_keyword_radar.models import ScoreBreakdown, SourceState, SourceStatus


def test_settings_rejects_limit_above_thirty(tmp_path):
    with pytest.raises(ValidationError):
        Settings(project_root=tmp_path, default_limit=31)


def test_settings_builds_project_directories(tmp_path):
    settings = Settings(project_root=tmp_path)
    assert settings.data_dir == tmp_path / "data"
    assert settings.reports_dir == tmp_path / "reports"


def test_score_breakdown_total_is_sum():
    breakdown = ScoreBreakdown(
        problem_intensity=20,
        page_intent=15,
        feasibility=10,
        maintenance=5,
        game_signal=7.5,
        evidence_confidence=4,
    )
    assert breakdown.total == 61.5


def test_score_breakdown_rejects_out_of_range_value():
    with pytest.raises(ValidationError):
        ScoreBreakdown(
            problem_intensity=26,
            page_intent=10,
            feasibility=10,
            maintenance=5,
            game_signal=5,
            evidence_confidence=5,
        )


def test_source_status_defaults_to_zero_records():
    status = SourceStatus(source="steam", state=SourceState.OK, message="ok")
    assert status.records == 0


def test_skipped_optional_source_does_not_degrade_snapshot(tmp_path):
    snapshot = build_demo_snapshot(Settings(project_root=tmp_path))
    assert any(item.state == SourceState.SKIPPED for item in snapshot.source_statuses)
    assert snapshot.state == SourceState.OK


def test_legacy_opportunity_restores_raw_score(tmp_path):
    snapshot = build_demo_snapshot(Settings(project_root=tmp_path))
    payload = snapshot.model_dump(mode="json")
    payload["opportunities"][0].pop("raw_score")

    restored = type(snapshot).model_validate(payload)

    assert restored.opportunities[0].raw_score == restored.opportunities[0].score_breakdown.total
