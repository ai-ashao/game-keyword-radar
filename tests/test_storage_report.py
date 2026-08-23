from __future__ import annotations

import json
from datetime import timedelta

from game_keyword_radar.config import Settings
from game_keyword_radar.demo import build_demo_snapshot
from game_keyword_radar.reporters.markdown import MarkdownReporter
from game_keyword_radar.storage import SnapshotStore


def test_snapshot_round_trip(tmp_path):
    settings = Settings(project_root=tmp_path)
    snapshot = build_demo_snapshot(settings)
    store = SnapshotStore(settings)
    path = store.save_snapshot(snapshot)
    assert path.exists()
    assert store.load_latest() == snapshot


def test_raw_payload_is_written_as_json(tmp_path):
    settings = Settings(project_root=tmp_path)
    path = SnapshotStore(settings).save_raw("steam", {"records": [1, 2]})
    assert json.loads(path.read_text(encoding="utf-8"))["records"] == [1, 2]


def test_demo_snapshot_is_explicitly_flagged(tmp_path):
    snapshot = build_demo_snapshot(Settings(project_root=tmp_path))
    assert snapshot.is_demo is True
    assert snapshot.raw_metadata["dataset"] == "fixture"


def test_report_warns_about_fixture_and_limits(tmp_path):
    settings = Settings(project_root=tmp_path)
    report = MarkdownReporter(settings).render(build_demo_snapshot(settings))
    assert "示例数据" in report
    assert "不是搜索量" in report
    assert "live SERP evidence" in report


def test_report_save_uses_run_id(tmp_path):
    settings = Settings(project_root=tmp_path)
    snapshot = build_demo_snapshot(settings)
    path = MarkdownReporter(settings).save(snapshot)
    assert snapshot.run_id in path.name
    assert path.exists()


def test_snapshot_history_is_newest_first_and_loadable(tmp_path):
    settings = Settings(project_root=tmp_path)
    store = SnapshotStore(settings)
    older = build_demo_snapshot(settings).model_copy(deep=True)
    older.run_id = "older-run"
    newer = older.model_copy(deep=True)
    newer.run_id = "newer-run"
    newer.generated_at = older.generated_at + timedelta(hours=1)
    store.save_snapshot(older)
    store.save_snapshot(newer)

    history = store.list_snapshots()

    assert [item.run_id for item in history] == ["newer-run", "older-run"]
    assert history[0].games_count == len(newer.games)
    assert store.load_snapshot("older-run") == older


def test_snapshot_history_skips_invalid_files_and_rejects_unsafe_ids(tmp_path):
    settings = Settings(project_root=tmp_path)
    store = SnapshotStore(settings)
    store.ensure_directories()
    invalid = settings.data_dir / "processed" / "broken-snapshot.json"
    invalid.write_text("not-json", encoding="utf-8")

    assert store.list_snapshots() == []
    assert store.load_snapshot("../latest") is None


def test_snapshot_history_skips_mismatched_filename_but_keeps_valid_files(tmp_path):
    settings = Settings(project_root=tmp_path)
    store = SnapshotStore(settings)
    valid = build_demo_snapshot(settings).model_copy(deep=True)
    valid.run_id = "valid-run"
    store.save_snapshot(valid)

    mismatched = valid.model_copy(deep=True)
    mismatched.run_id = "internal-run"
    wrong_path = settings.data_dir / "processed" / "different-run-snapshot.json"
    wrong_path.write_text(mismatched.model_dump_json(), encoding="utf-8")

    assert [item.run_id for item in store.list_snapshots()] == ["valid-run"]
