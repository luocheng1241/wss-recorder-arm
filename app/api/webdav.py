from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.deps import require_auth

router = APIRouter(prefix="/api/webdav", tags=["webdav"])


class WebDAVConfigBody(BaseModel):
    enabled: bool | None = None
    url: str | None = None
    username: str | None = None
    password: str | None = None
    remote_base: str | None = None
    cron: str | None = None
    verify_ssl: bool | None = None
    batch_size: int | None = None
    delete_local_after_sync: bool | None = None


@router.get("/config")
async def get_config(request: Request, _: bool = Depends(require_auth)):
    return request.app.state.webdav_service.config_public()


@router.put("/config")
async def put_config(
    body: WebDAVConfigBody, request: Request, _: bool = Depends(require_auth)
):
    cfg = request.app.state.webdav_service.update_config(body.model_dump(exclude_none=True))
    request.app.state.scheduler.reload_webdav_job()
    return cfg


@router.post("/sync-now")
async def sync_now(request: Request, _: bool = Depends(require_auth)):
    return await request.app.state.webdav_service.sync_now()


@router.get("/status")
async def status(request: Request, _: bool = Depends(require_auth)):
    st = request.app.state.webdav_service.status()
    st["pending"] = await request.app.state.webdav_service.pending_count()
    return st
