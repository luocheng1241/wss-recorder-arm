from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from app.config import Settings
from app.deps import SESSION_COOKIE, require_auth, settings_dep
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    password: str


@router.post("/login")
async def login(body: LoginBody, response: Response, settings: Settings = Depends(settings_dep)):
    svc = AuthService(settings)
    if not svc.verify_password(body.password):
        raise HTTPException(status_code=401, detail="invalid password")
    token = svc.create_session_token()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=settings.auth.session_max_age_sec,
        path="/",
    )
    return {"ok": True, "authenticated": True}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
async def me(_: bool = Depends(require_auth)):
    return {"authenticated": True}
