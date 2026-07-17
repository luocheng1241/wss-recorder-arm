from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request

from app.config import Settings, get_settings
from app.services.auth_service import AuthService

SESSION_COOKIE = "wss_session"


def settings_dep() -> Settings:
    return get_settings()


def get_app_state(request: Request):
    return request.app.state


def auth_service(settings: Annotated[Settings, Depends(settings_dep)]) -> AuthService:
    return AuthService(settings)


async def require_auth(
    request: Request,
    settings: Annotated[Settings, Depends(settings_dep)],
    wss_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
):
    svc = AuthService(settings)
    token = wss_session
    if not token:
        # also allow Authorization: Bearer
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not svc.validate_session_token(token):
        raise HTTPException(status_code=401, detail="unauthorized")
    return True
