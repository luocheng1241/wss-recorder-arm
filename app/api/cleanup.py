from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.deps import require_auth

router = APIRouter(prefix="/api/cleanup", tags=["cleanup"])


class CleanupConfigBody(BaseModel):
    enabled: bool | None = None
    delete_after_sync: bool | None = None
    max_gb: float | None = Field(default=None, ge=0.5, le=2000)
    target_ratio: float | None = Field(default=None, ge=0.5, le=0.99)
    interval_sec: int | None = Field(default=None, ge=60, le=86400)


@router.get("/status")
async def cleanup_status(request: Request, _: bool = Depends(require_auth)):
    return request.app.state.cleanup_service.snapshot()


@router.put("/config")
async def put_cleanup_config(
    body: CleanupConfigBody, request: Request, _: bool = Depends(require_auth)
):
    cfg = request.app.state.settings.cleanup
    data = body.model_dump(exclude_none=True)
    for k, v in data.items():
        setattr(cfg, k, v)
    if "delete_after_sync" in data:
        request.app.state.settings.webdav.delete_local_after_sync = data["delete_after_sync"]
    request.app.state.scheduler.reload_cleanup_job()
    return request.app.state.cleanup_service.snapshot()


@router.post("/run-now")
async def run_cleanup_now(request: Request, _: bool = Depends(require_auth)):
    return await request.app.state.cleanup_service.run_all()
