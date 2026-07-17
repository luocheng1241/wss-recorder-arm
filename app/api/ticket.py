from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.deps import require_auth

router = APIRouter(prefix="/api/ticket", tags=["ticket"])


class TicketBody(BaseModel):
    ticket: str


class TokenCacheBody(BaseModel):
    token: str | None = None
    yyToken: str | None = None
    cookies: dict[str, str] | None = None
    ticket: str | None = None
    storage: dict[str, Any] | None = None


@router.get("")
async def get_ticket(request: Request, _: bool = Depends(require_auth)):
    return await request.app.state.ticket_service.snapshot()


@router.post("")
async def set_ticket(body: TicketBody, request: Request, _: bool = Depends(require_auth)):
    try:
        snap = await request.app.state.ticket_service.set_ticket(body.ticket, source="manual")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # if recorder wanted, restart
    rec = request.app.state.recorder_service
    if rec.wanted:
        await rec.start()
    return {"ok": True, "ticket": snap}


@router.delete("")
async def clear_ticket(request: Request, _: bool = Depends(require_auth)):
    await request.app.state.recorder_service.stop()
    snap = await request.app.state.ticket_service.clear()
    return {"ok": True, "ticket": snap}


@router.post("/refresh")
async def refresh_ticket(request: Request, _: bool = Depends(require_auth)):
    result = await request.app.state.ticket_service.auto_refresh()
    if result.get("ok") and request.app.state.recorder_service.wanted:
        await request.app.state.recorder_service.start()
    return result


@router.post("/token-cache")
async def import_token_cache(
    body: TokenCacheBody, request: Request, _: bool = Depends(require_auth)
):
    payload = body.model_dump(exclude_none=True)
    if "yyToken" in payload:
        payload["yyToken"] = payload.pop("yyToken")
    return await request.app.state.ticket_service.import_token_cache(payload)
