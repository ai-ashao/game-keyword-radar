"""Opt-in, process-local monitoring. No cloud jobs and no fabricated catch-up samples."""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta
from game_keyword_radar.models import utc_now
from game_keyword_radar.pipeline import Scanner
from game_keyword_radar.storage import SnapshotStore
from game_keyword_radar.sources.base import safe_error


class MonitorController:
    def __init__(self, settings, *, scanner_factory=Scanner, clock=utc_now):
        self.settings = settings
        self.scanner_factory = scanner_factory
        self.clock = clock
        self.enabled = False
        self.running = False
        self.task = None
        self.error = None
        self.next_due_at = None
        self.message = '定时监测未开启；关闭服务或电脑休眠期间不会采样'

    def status(self):
        state = SnapshotStore(self.settings).monitoring_state()
        return {**state, 'enabled': self.enabled, 'running': self.running,
                'next_due_at': self.next_due_at.isoformat() if self.next_due_at else None,
                'interval_minutes': self.settings.monitoring.interval_minutes,
                'message': self.message, 'error': self.error}

    def once(self):
        if self.task and not self.task.done():
            return False
        self.task = asyncio.create_task(self._observe())
        return True

    def start(self):
        if self.task and not self.task.done():
            return False
        self.enabled = True
        self.task = asyncio.create_task(self._loop())
        return True

    async def stop(self):
        self.enabled = False
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.running = False
        self.next_due_at = None
        self.message = '监测已停止；已保存的真实观测不变'

    async def _observe(self):
        self.running = True
        self.error = None
        self.message = '正在进行 Steam / Twitch 轻量观测'
        try:
            result = await self.scanner_factory(self.settings).monitor_once()
            self.message = f'监测完成：{result.run_id}；完整报告未覆盖'
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = safe_error(exc)
            self.message = '本轮未完成（可能有另一任务运行）；不补造历史'
        finally:
            self.running = False

    async def _loop(self):
        while self.enabled:
            await self._observe()
            # Even after a long sleep there is only ONE next real observation.
            self.next_due_at = self.clock() + timedelta(minutes=self.settings.monitoring.interval_minutes)
            await asyncio.sleep(self.settings.monitoring.interval_minutes * 60)
