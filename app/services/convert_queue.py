"""Convert queue service."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.converter import convert_cflv_to_mp4
from app.core.paths import to_rel_path
from app.db import engine as db_engine
from app.db.models import Segment

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)


class ConvertQueue:
    def __init__(self, settings: "Settings", cleanup_service=None):
        self.settings = settings
        self.cleanup_service = cleanup_service
        self.queue: asyncio.Queue[int] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []
        self.pending = 0
        self.failed = 0
        self.running = False

    def set_cleanup(self, cleanup_service) -> None:
        self.cleanup_service = cleanup_service

    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        n = max(1, self.settings.recording.convert_workers)
        for i in range(n):
            self._tasks.append(asyncio.create_task(self._worker(i), name=f"convert-{i}"))
        await self.recover()

    async def stop(self) -> None:
        self.running = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def enqueue(self, segment_id: int) -> None:
        self.pending += 1
        await self.queue.put(segment_id)

    def snapshot(self) -> dict:
        return {"pending": self.pending, "failed": self.failed, "qsize": self.queue.qsize()}

    def _abs(self, rel_or_abs: str | None) -> Path:
        if not rel_or_abs:
            return Path("")
        p = Path(rel_or_abs)
        if p.is_absolute():
            return p
        root = self.settings.resolve_path(self.settings.recording.output_dir)
        return (root / rel_or_abs).resolve()

    async def recover(self) -> None:
        assert db_engine.SessionLocal is not None
        async with db_engine.SessionLocal() as session:
            result = await session.execute(
                select(Segment).where(Segment.status.in_(("queued", "converting", "recording")))
            )
            rows = list(result.scalars().all())
            for row in rows:
                if row.status == "recording":
                    cflv_path = self._abs(row.rel_path_cflv)
                    if row.rel_path_cflv and cflv_path.exists() and cflv_path.stat().st_size > 0:
                        row.status = "queued"
                    else:
                        row.status = "failed"
                        row.error_msg = "incomplete recording"
                elif row.status == "converting":
                    row.status = "queued"
            await session.commit()
            result = await session.execute(select(Segment.id).where(Segment.status == "queued"))
            ids = [r[0] for r in result.all()]
        for sid in ids:
            await self.enqueue(sid)
        logger.info("convert recover: requeued %s", len(ids))

    async def _worker(self, worker_id: int) -> None:
        while self.running:
            try:
                segment_id = await self.queue.get()
            except asyncio.CancelledError:
                break
            try:
                await self._convert_one(segment_id)
            except Exception:
                logger.exception("convert worker %s failed on %s", worker_id, segment_id)
                self.failed += 1
            finally:
                self.pending = max(0, self.pending - 1)
                self.queue.task_done()

    async def _convert_one(self, segment_id: int) -> None:
        assert db_engine.SessionLocal is not None
        async with db_engine.SessionLocal() as session:
            seg = await session.get(Segment, segment_id)
            if not seg or seg.status not in ("queued", "converting"):
                return
            seg.status = "converting"
            await session.commit()
            cflv = self._abs(seg.rel_path_cflv)
            mp4 = self._abs(seg.rel_path_mp4)
            if not cflv.exists():
                seg.status = "failed"
                seg.error_msg = "cflv missing"
                await session.commit()
                self.failed += 1
                return

        ok, err = await asyncio.to_thread(convert_cflv_to_mp4, str(cflv), str(mp4))

        async with db_engine.SessionLocal() as session:
            seg = await session.get(Segment, segment_id)
            if not seg:
                return
            if ok:
                seg.status = "ready"
                seg.error_msg = None
                try:
                    seg.bytes_mp4 = mp4.stat().st_size
                except OSError:
                    pass
                if not self.settings.recording.keep_raw:
                    try:
                        if cflv.exists():
                            cflv.unlink()
                    except OSError:
                        pass
            else:
                seg.status = "failed"
                seg.error_msg = (err or "convert failed")[:500]
                self.failed += 1
            await session.commit()
        logger.info("segment %s convert ok=%s", segment_id, ok)
        if ok and self.cleanup_service:
            try:
                await self.cleanup_service.enforce_quota()
            except Exception:
                logger.exception("quota cleanup after convert failed")


async def create_segment_row(meta: dict, settings: "Settings") -> int:
    assert db_engine.SessionLocal is not None
    output_root = settings.resolve_path(settings.recording.output_dir)
    cflv = meta["cflv_path"]
    mp4 = meta["mp4_path"]
    rel_cflv = to_rel_path(cflv, output_root)
    rel_mp4 = to_rel_path(mp4, output_root)
    async with db_engine.SessionLocal() as session:
        seg = Segment(
            rel_path_cflv=rel_cflv,
            rel_path_mp4=rel_mp4,
            started_at=meta.get("started_at"),
            ended_at=meta.get("ended_at"),
            bytes_cflv=meta.get("bytes_cflv") or 0,
            frames=meta.get("frames") or 0,
            segment_index=meta.get("segment_index") or 0,
            status="queued",
        )
        session.add(seg)
        await session.commit()
        await session.refresh(seg)
        return seg.id
