from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from game_keyword_radar.config import Settings
from game_keyword_radar.demo import build_demo_snapshot
from game_keyword_radar.storage import SnapshotStore
from game_keyword_radar.web.app import create_app


def client(tmp_path) -> TestClient:
    return TestClient(create_app(Settings(project_root=tmp_path)))


def test_health_endpoint(tmp_path):
    response = client(tmp_path).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_dashboard_renders_empty_shell(tmp_path):
    response = client(tmp_path).get("/")
    assert response.status_code == 200
    assert "Game Keyword Radar" in response.text
    assert "今天，什么值得" in response.text
    assert "/static/favicon.svg" in response.text
    assert "/static/styles.css?v=2.1.0rc1" in response.text
    assert 'id="download-report" aria-disabled="true"' in response.text
    assert 'href="/api/report"' not in response.text


def test_snapshot_is_404_before_first_run(tmp_path):
    response = client(tmp_path).get("/api/snapshot")
    assert response.status_code == 404


def test_demo_endpoint_persists_snapshot(tmp_path):
    api = client(tmp_path)
    response = api.post("/api/demo")
    assert response.status_code == 200
    assert response.json()["is_demo"] is True
    latest = api.get("/api/snapshot")
    assert latest.status_code == 200
    assert latest.json()["run_id"] == "demo-fixture"


def test_report_endpoint_downloads_markdown(tmp_path):
    api = client(tmp_path)
    api.post("/api/demo")
    response = api.get("/api/report")
    assert response.status_code == 200
    assert "Game Keyword Radar" in response.text
    assert "attachment" in response.headers["content-disposition"]


def test_scan_endpoint_validates_limit(tmp_path):
    response = client(tmp_path).post("/api/scan", json={"limit": 31, "with_trends": False})
    assert response.status_code == 422


def test_status_is_idle_initially(tmp_path):
    response = client(tmp_path).get("/api/status")
    assert response.status_code == 200
    assert response.json()["running"] is False


def save_history(tmp_path):
    settings = Settings(project_root=tmp_path)
    store = SnapshotStore(settings)
    older = build_demo_snapshot(settings).model_copy(deep=True)
    older.run_id = "older-run"
    newer = older.model_copy(deep=True)
    newer.run_id = "newer-run"
    newer.generated_at = older.generated_at + timedelta(hours=1)
    newer.games[0].current_players += 500
    newer.opportunities[0].score += 1
    store.save_snapshot(older)
    store.save_snapshot(newer)
    return older, newer


def test_snapshot_history_endpoints_and_automatic_baseline(tmp_path):
    older, newer = save_history(tmp_path)
    api = client(tmp_path)

    history = api.get("/api/snapshots")
    selected = api.get(f"/api/snapshots/{older.run_id}")
    comparison = api.get("/api/compare", params={"current_run_id": newer.run_id})

    assert history.status_code == 200
    assert [item["run_id"] for item in history.json()] == [newer.run_id, older.run_id]
    assert selected.status_code == 200
    assert selected.json()["run_id"] == older.run_id
    assert comparison.status_code == 200
    assert comparison.json()["baseline_run_id"] == older.run_id
    assert comparison.json()["rising_opportunities"] == 1


def test_snapshot_compare_accepts_explicit_baseline(tmp_path):
    older, newer = save_history(tmp_path)

    response = client(tmp_path).get(
        "/api/compare",
        params={
            "current_run_id": newer.run_id,
            "baseline_run_id": older.run_id,
        },
    )

    assert response.status_code == 200
    assert response.json()["current_run_id"] == newer.run_id
    assert response.json()["baseline_run_id"] == older.run_id


def test_snapshot_compare_rejects_same_or_missing_runs(tmp_path):
    _, newer = save_history(tmp_path)
    api = client(tmp_path)

    same = api.get(
        "/api/compare",
        params={"current_run_id": newer.run_id, "baseline_run_id": newer.run_id},
    )
    missing = api.get(
        "/api/compare", params={"current_run_id": "missing-run"}
    )

    assert same.status_code == 422
    assert missing.status_code == 404


def test_snapshot_compare_rejects_missing_baseline_and_oldest_auto_compare(tmp_path):
    older, newer = save_history(tmp_path)
    api = client(tmp_path)

    missing_baseline = api.get(
        "/api/compare",
        params={
            "current_run_id": newer.run_id,
            "baseline_run_id": "missing-run",
        },
    )
    no_earlier = api.get(
        "/api/compare",
        params={"current_run_id": older.run_id},
    )

    assert missing_baseline.status_code == 404
    assert no_earlier.status_code == 404


def test_report_can_render_a_selected_historical_snapshot(tmp_path):
    older, _ = save_history(tmp_path)

    response = client(tmp_path).get("/api/report", params={"run_id": older.run_id})

    assert response.status_code == 200
    assert older.run_id in response.headers["content-disposition"]
