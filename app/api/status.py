from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from app.core.converter import ffmpeg_available
from app.deps import require_auth

router = APIRouter(prefix="/api", tags=["status"])


@router.get("/status")
async def status(request: Request, _: bool = Depends(require_auth)):
    app = request.app
    ticket = await app.state.ticket_service.snapshot()
    rec = app.state.recorder_service.status()
    convert = app.state.convert_queue.snapshot()
    settings = app.state.settings
    out = settings.resolve_path(settings.recording.output_dir)
    disk = 0
    if out.exists():
        for p in out.rglob("*"):
            if p.is_file():
                try:
                    disk += p.stat().st_size
                except OSError:
                    pass
    pending_sync = 0
    try:
        pending_sync = await app.state.webdav_service.pending_count()
    except Exception:
        pass
    cleanup = {}
    try:
        cleanup = app.state.cleanup_service.snapshot()
    except Exception:
        pass
    return {
        "recorder": rec,
        "ticket": ticket,
        "convert_queue": convert,
        "disk": {"recordings_bytes": disk},
        "ffmpeg": ffmpeg_available(),
        "webdav_pending": pending_sync,
        "cleanup": cleanup,
        "server_now": time.time(),
        "device_id": settings.device.device_id,
        "segment_duration": settings.recording.segment_duration,
    }


@router.get("/health")
async def health():
    return {"ok": True}
