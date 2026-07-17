"""Ticket lifecycle state machine."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.core.ticket_api import (
    get_ticket_from_token,
    load_token_cache,
    mask_ticket,
    save_token_cache,
)
import app.db.engine as db_engine
from app.db.models import TicketMeta

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)

STATES = ("EMPTY", "VALID", "EXPIRING", "EXPIRED", "NEEDS_INPUT")


class TicketService:
    def __init__(self, settings: "Settings"):
        self.settings = settings
        self._meta: TicketMeta | None = None

    async def ensure_row(self) -> TicketMeta:
        assert db_engine.SessionLocal is not None
        async with db_engine.SessionLocal() as session:
            result = await session.execute(select(TicketMeta).limit(1))
            row = result.scalar_one_or_none()
            if not row:
                row = TicketMeta(state="EMPTY", ttl_sec=self.settings.ticket.ttl_sec)
                session.add(row)
                await session.commit()
                await session.refresh(row)
            self._meta = row
            return row

    def _compute_state(self, row: TicketMeta, now: float | None = None) -> str:
        now = now or time.time()
        if not row.ticket_value:
            return "EMPTY" if row.state != "NEEDS_INPUT" else "NEEDS_INPUT"
        obtained = row.obtained_at or 0
        ttl = row.ttl_sec or self.settings.ticket.ttl_sec
        remaining = obtained + ttl - now
        if remaining <= 0:
            return "EXPIRED"
        if remaining < self.settings.ticket.warn_sec:
            return "EXPIRING"
        return "VALID"

    async def snapshot(self) -> dict[str, Any]:
        row = await self.ensure_row()
        now = time.time()
        state = self._compute_state(row, now)
        if state != row.state:
            await self._set_state(state)
            row.state = state
        obtained = row.obtained_at or 0
        ttl = row.ttl_sec or self.settings.ticket.ttl_sec
        expires_at = obtained + ttl if row.ticket_value else None
        remaining = max(0, int(expires_at - now)) if expires_at else 0
        return {
            "state": state,
            "preview": mask_ticket(row.ticket_value),
            "source": row.source,
            "obtained_at": obtained or None,
            "expires_at": expires_at,
            "remaining_sec": remaining,
            "ttl_sec": ttl,
            "has_token_cache": self._has_token_cache(),
        }

    def _has_token_cache(self) -> bool:
        path = str(self.settings.resolve_path(self.settings.ticket.token_cache_path))
        data = load_token_cache(path)
        return bool(data.get("token") or data.get("cookies"))

    async def _set_state(self, state: str) -> None:
        assert db_engine.SessionLocal is not None
        async with db_engine.SessionLocal() as session:
            result = await session.execute(select(TicketMeta).limit(1))
            row = result.scalar_one_or_none()
            if row:
                row.state = state
                await session.commit()

    async def get_ticket_value(self) -> str | None:
        row = await self.ensure_row()
        state = self._compute_state(row)
        if state in ("EMPTY", "EXPIRED", "NEEDS_INPUT") and not row.ticket_value:
            return None
        if state == "EXPIRED":
            return None
        return row.ticket_value

    async def set_ticket(self, ticket: str, source: str = "manual") -> dict[str, Any]:
        ticket = (ticket or "").strip()
        if not ticket:
            raise ValueError("empty ticket")
        assert db_engine.SessionLocal is not None
        async with db_engine.SessionLocal() as session:
            result = await session.execute(select(TicketMeta).limit(1))
            row = result.scalar_one_or_none()
            if not row:
                row = TicketMeta()
                session.add(row)
            row.ticket_value = ticket
            row.obtained_at = time.time()
            row.ttl_sec = self.settings.ticket.ttl_sec
            row.source = source
            row.state = "VALID"
            await session.commit()
        # also mirror into token_cache for compatibility
        path = str(self.settings.resolve_path(self.settings.ticket.token_cache_path))
        save_token_cache(path, {"ticket": ticket, "ticket_time": time.time()})
        return await self.snapshot()

    async def clear(self) -> dict[str, Any]:
        assert db_engine.SessionLocal is not None
        async with db_engine.SessionLocal() as session:
            result = await session.execute(select(TicketMeta).limit(1))
            row = result.scalar_one_or_none()
            if row:
                row.ticket_value = None
                row.obtained_at = None
                row.state = "EMPTY"
                row.source = "manual"
                await session.commit()
        return await self.snapshot()

    async def mark_needs_input(self) -> dict[str, Any]:
        assert db_engine.SessionLocal is not None
        async with db_engine.SessionLocal() as session:
            result = await session.execute(select(TicketMeta).limit(1))
            row = result.scalar_one_or_none()
            if row:
                row.state = "NEEDS_INPUT"
                await session.commit()
        return await self.snapshot()

    async def mark_expired(self) -> dict[str, Any]:
        assert db_engine.SessionLocal is not None
        async with db_engine.SessionLocal() as session:
            result = await session.execute(select(TicketMeta).limit(1))
            row = result.scalar_one_or_none()
            if row:
                row.state = "EXPIRED"
                await session.commit()
        return await self.snapshot()

    async def import_token_cache(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = str(self.settings.resolve_path(self.settings.ticket.token_cache_path))
        data = load_token_cache(path)
        data.update(payload)
        if "timestamp" not in data:
            data["timestamp"] = time.time()
        save_token_cache(path, data)
        # if ticket present, set it
        if payload.get("ticket"):
            await self.set_ticket(payload["ticket"], source="import")
        return {
            "ok": True,
            "has_token": bool(data.get("token")),
            "has_cookies": bool(data.get("cookies")),
            "ticket": await self.snapshot(),
        }

    async def auto_refresh(self) -> dict[str, Any]:
        if not self.settings.ticket.auto_refresh:
            return {"ok": False, "error": "auto_refresh disabled", "ticket": await self.snapshot()}
        path = str(self.settings.resolve_path(self.settings.ticket.token_cache_path))
        cache = load_token_cache(path)
        token = cache.get("token") or ""
        yy = cache.get("yyToken") or ""
        cookies = cache.get("cookies") or {}
        if not token and not cookies:
            await self.mark_needs_input()
            return {"ok": False, "error": "no token_cache", "ticket": await self.snapshot()}

        d = self.settings.device
        ticket = await asyncio.to_thread(
            get_ticket_from_token,
            token,
            yy,
            cookies,
            device_id=d.device_id,
            base_url=d.base_url,
            app_id=d.app_id,
            player_app_id=d.player_app_id,
            player_api_url=d.player_api_url,
        )
        if ticket:
            snap = await self.set_ticket(ticket, source="auto")
            return {"ok": True, "ticket": snap}
        await self.mark_needs_input()
        return {"ok": False, "error": "refresh failed", "ticket": await self.snapshot()}

    async def on_ws_expired(self) -> dict[str, Any]:
        await self.mark_expired()
        if self.settings.ticket.auto_refresh:
            result = await self.auto_refresh()
            if result.get("ok"):
                return result
        await self.mark_needs_input()
        return {"ok": False, "ticket": await self.snapshot()}
