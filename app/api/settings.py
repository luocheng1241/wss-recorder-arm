from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.deps import require_auth

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsBody(BaseModel):
    segment_duration: int | None = None
    keep_raw: bool | None = None
    device_id: str | None = None
    relay_url: str | None = None
    convert_workers: int | None = None
    cleanup_enabled: bool | None = None
    cleanup_max_gb: float | None = None
    delete_after_sync: bool | None = None


@router.get("")
async def get_settings(request: Request, _: bool = Depends(require_auth)):
    s = request.app.state.settings
    return {
        "segment_duration": s.recording.segment_duration,
        "keep_raw": s.recording.keep_raw,
        "device_id": s.device.device_id,
        "relay_url": s.device.relay_url,
        "convert_workers": s.recording.convert_workers,
        "output_dir": s.recording.output_dir,
        "ticket_ttl_sec": s.ticket.ttl_sec,
        "auto_refresh": s.ticket.auto_refresh,
        "auto_start": s.recording.auto_start,
        "cleanup_enabled": s.cleanup.enabled,
        "cleanup_max_gb": s.cleanup.max_gb,
        "delete_after_sync": s.cleanup.delete_after_sync,
        "cleanup_interval_sec": s.cleanup.interval_sec,
    }


@router.put("")
async def put_settings(body: SettingsBody, request: Request, _: bool = Depends(require_auth)):
    s = request.app.state.settings
    if body.segment_duration is not None:
        s.recording.segment_duration = body.segment_duration
    if body.keep_raw is not None:
        s.recording.keep_raw = body.keep_raw
    if body.device_id is not None:
        s.device.device_id = body.device_id
    if body.relay_url is not None:
        s.device.relay_url = body.relay_url
    if body.convert_workers is not None:
        s.recording.convert_workers = body.convert_workers
    if body.cleanup_enabled is not None:
        s.cleanup.enabled = body.cleanup_enabled
    if body.cleanup_max_gb is not None:
        s.cleanup.max_gb = body.cleanup_max_gb
    if body.delete_after_sync is not None:
        s.cleanup.delete_after_sync = body.delete_after_sync
        s.webdav.delete_local_after_sync = body.delete_after_sync
    if any(
        x is not None
        for x in (body.cleanup_enabled, body.cleanup_max_gb, body.delete_after_sync)
    ):
        request.app.state.scheduler.reload_cleanup_job()
    return await get_settings(request, True)
