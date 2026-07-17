"""Recorder service orchestrating the WS worker."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import TYPE_CHECKING, Any

from app.services.convert_queue import ConvertQueue, create_segment_row
from app.services.ticket_service import TicketService
from app.workers.recorder_worker import RecorderStats, RecorderWorker

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)


class RecorderService:
    def __init__(
        self,
        settings: "Settings",
        ticket_service: TicketService,
        convert_queue: ConvertQueue,
        loop: asyncio.AbstractEventLoop | None = None,
    ):
        self.settings = settings
        self.ticket_service = ticket_service
        self.convert_queue = convert_queue
        self.loop = loop
        self.worker: RecorderWorker | None = None
        self.stats = RecorderStats()
        self.wanted = False  # user wants recording on
        self._lock = threading.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def _schedule(self, coro) -> None:
        loop = self.loop
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, loop)

    def _on_segment_closed(self, meta: dict) -> None:
        async def handle():
            sid = await create_segment_row(meta, self.settings)
            await self.convert_queue.enqueue(sid)

        self._schedule(handle())

    def _on_ticket_expired(self) -> None:
        async def handle():
            result = await self.ticket_service.on_ws_expired()
            self.wanted = True
            if result.get("ok"):
                # restart with new ticket
                await asyncio.sleep(1)
                await self.start()
            else:
                self.stop_worker_only()

        self._schedule(handle())

    def _on_stats(self, stats: RecorderStats) -> None:
        self.stats = stats

    async def start(self) -> dict[str, Any]:
        ticket = await self.ticket_service.get_ticket_value()
        if not ticket:
            snap = await self.ticket_service.snapshot()
            if snap["state"] in ("EXPIRED", "EMPTY", "NEEDS_INPUT"):
                # try auto once
                if self.settings.ticket.auto_refresh:
                    refreshed = await self.ticket_service.auto_refresh()
                    if refreshed.get("ok"):
                        ticket = await self.ticket_service.get_ticket_value()
            if not ticket:
                self.wanted = True
                return {"ok": False, "error": "needs_ticket", "ticket": await self.ticket_service.snapshot()}

        with self._lock:
            self.stop_worker_only()
            self.wanted = True
            out = str(self.settings.resolve_path(self.settings.recording.output_dir))
            self.worker = RecorderWorker(
                ticket,
                device_id=self.settings.device.device_id,
                relay_url=self.settings.device.relay_url,
                vnsp_version=self.settings.device.vnsp_version,
                output_dir=out,
                segment_duration=self.settings.recording.segment_duration,
                on_segment_closed=self._on_segment_closed,
                on_ticket_expired=self._on_ticket_expired,
                on_stats=self._on_stats,
            )
            self.worker.start()
        return {"ok": True, "status": self.status()}

    def stop_worker_only(self) -> None:
        if self.worker:
            try:
                self.worker.stop()
            except Exception:
                logger.exception("stop worker")
            self.worker = None

    async def stop(self) -> dict[str, Any]:
        self.wanted = False
        with self._lock:
            self.stop_worker_only()
        return {"ok": True, "status": self.status()}

    def status(self) -> dict[str, Any]:
        s = self.stats
        state = "stopped"
        if self.wanted and s.ticket_expired:
            state = "needs_ticket"
        elif self.wanted and s.running and s.connected:
            state = "running"
        elif self.wanted and s.running:
            state = "connecting"
        elif self.wanted:
            state = "reconnecting" if s.last_error else "starting"
        return {
            "state": state,
            "wanted": self.wanted,
            "connected": s.connected,
            "total_bytes": s.total_bytes,
            "frame_count": s.frame_count,
            "segment_index": s.segment_index,
            "segment_bytes": s.segment_bytes,
            "segment_frames": s.segment_frames,
            "current_mp4": s.current_mp4,
            "started_at": s.started_at,
            "last_error": s.last_error,
            "ticket_expired": s.ticket_expired,
            "uptime_sec": int(time.time() - s.started_at) if s.started_at else 0,
        }
