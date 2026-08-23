from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from game_keyword_radar import __version__
from game_keyword_radar.config import Settings
from game_keyword_radar.demo import build_demo_snapshot
from game_keyword_radar.history import compare_snapshots
from game_keyword_radar.models import ScanSnapshot
from game_keyword_radar.pipeline import Scanner
from game_keyword_radar.reporters.markdown import MarkdownReporter
from game_keyword_radar.storage import SnapshotStore


WEB_ROOT = Path(__file__).resolve().parent


def snapshot_payload(snapshot: ScanSnapshot) -> dict[str, Any]:
    payload = snapshot.model_dump(mode="json")
    payload["state"] = snapshot.state.value
    return payload


class ScanRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=30)
    with_trends: bool = False


@dataclass
class ScanManager:
    settings: Settings
    running: bool = False
    phase: str = "idle"
    message: str = "Ready"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_run_id: str | None = None
    error: str | None = None
    _task: asyncio.Task[None] | None = field(default=None, repr=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "phase": self.phase,
            "message": self.message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "last_run_id": self.last_run_id,
            "error": self.error,
        }

    def start(self, request: ScanRequest) -> bool:
        if self.running:
            return False
        self.running = True
        self.phase = "collecting"
        self.message = "正在读取 Steam 候选和详情"
        self.started_at = datetime.now(timezone.utc)
        self.finished_at = None
        self.error = None
        self._task = asyncio.create_task(self._run(request))
        return True

    async def _run(self, request: ScanRequest) -> None:
        try:
            snapshot = await Scanner(self.settings).run(
                limit=request.limit, with_trends=request.with_trends
            )
            self.last_run_id = snapshot.run_id
            self.phase = "complete"
            self.message = (
                f"完成：{len(snapshot.games)} 个游戏，"
                f"{len(snapshot.opportunities)} 个待验证机会"
            )
        except Exception as exc:
            self.phase = "failed"
            self.message = "扫描失败，现有快照没有被覆盖"
            self.error = str(exc)
        finally:
            self.running = False
            self.finished_at = datetime.now(timezone.utc)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings()
    store = SnapshotStore(resolved)
    reporter = MarkdownReporter(resolved)
    manager = ScanManager(resolved)
    templates = Jinja2Templates(directory=str(WEB_ROOT / "templates"))

    web = FastAPI(
        title="Game Keyword Radar",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
    )
    web.state.settings = resolved
    web.state.store = store
    web.state.reporter = reporter
    web.state.scan_manager = manager
    web.mount("/static", StaticFiles(directory=str(WEB_ROOT / "static")), name="static")

    @web.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"version": __version__, "country": resolved.country},
        )

    @web.get("/api/snapshot")
    async def latest_snapshot() -> dict[str, Any]:
        snapshot = store.load_latest()
        if snapshot is None:
            raise HTTPException(status_code=404, detail="No snapshot exists yet.")
        return snapshot_payload(snapshot)

    @web.get("/api/snapshots")
    async def snapshot_history() -> list[dict[str, Any]]:
        return [summary.model_dump(mode="json") for summary in store.list_snapshots()]

    @web.get("/api/snapshots/{run_id}")
    async def historical_snapshot(run_id: str) -> dict[str, Any]:
        snapshot = store.load_snapshot(run_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Snapshot was not found.")
        return snapshot_payload(snapshot)

    @web.get("/api/compare")
    async def compare_snapshot_history(
        current_run_id: str, baseline_run_id: str | None = None
    ) -> dict[str, Any]:
        current = store.load_snapshot(current_run_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Current snapshot was not found.")
        if baseline_run_id is None:
            history = store.list_snapshots()
            current_index = next(
                (index for index, item in enumerate(history) if item.run_id == current_run_id),
                None,
            )
            if current_index is None or current_index + 1 >= len(history):
                raise HTTPException(
                    status_code=404, detail="No earlier snapshot exists for comparison."
                )
            baseline_run_id = history[current_index + 1].run_id
        if baseline_run_id == current_run_id:
            raise HTTPException(
                status_code=422, detail="Current and baseline snapshots must differ."
            )
        baseline = store.load_snapshot(baseline_run_id)
        if baseline is None:
            raise HTTPException(status_code=404, detail="Baseline snapshot was not found.")
        return compare_snapshots(current, baseline).model_dump(mode="json")

    @web.get("/api/status")
    async def scan_status() -> dict[str, Any]:
        return manager.as_dict()

    @web.post("/api/scan", status_code=status.HTTP_202_ACCEPTED)
    async def start_scan(scan_request: ScanRequest) -> dict[str, Any]:
        if not manager.start(scan_request):
            raise HTTPException(status_code=409, detail="A scan is already running.")
        return manager.as_dict()

    @web.post("/api/demo")
    async def load_demo() -> dict[str, Any]:
        if manager.running:
            raise HTTPException(status_code=409, detail="Wait for the active scan to finish.")
        snapshot = build_demo_snapshot(resolved)
        store.save_snapshot(snapshot)
        reporter.save(snapshot)
        return snapshot_payload(snapshot)

    @web.get("/api/report", response_class=PlainTextResponse)
    async def latest_report(run_id: str | None = None) -> PlainTextResponse:
        snapshot = store.load_snapshot(run_id) if run_id else store.load_latest()
        if snapshot is None:
            raise HTTPException(status_code=404, detail="No snapshot exists yet.")
        return PlainTextResponse(
            reporter.render(snapshot),
            headers={
                "Content-Disposition": f'attachment; filename="{snapshot.run_id}-game-keywords.md"'
            },
        )

    @web.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return web


app = create_app()
