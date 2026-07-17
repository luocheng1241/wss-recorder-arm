from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.deps import require_auth

router = APIRouter(prefix="/api/recorder", tags=["recorder"])


@router.post("/start")
async def start(request: Request, _: bool = Depends(require_auth)):
    return await request.app.state.recorder_service.start()


@router.post("/stop")
async def stop(request: Request, _: bool = Depends(require_auth)):
    return await request.app.state.recorder_service.stop()


@router.get("/stats")
async def stats(request: Request, _: bool = Depends(require_auth)):
    return request.app.state.recorder_service.status()
