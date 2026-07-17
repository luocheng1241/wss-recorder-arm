"""Live-ish preview from latest WebDAV remote segment."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.api.recordings import _item_dict
from app.deps import require_auth

router = APIRouter(prefix="/api/preview", tags=["preview"])


@router.get("/latest")
async def latest(request: Request, _: bool = Depends(require_auth)):
    wd = request.app.state.webdav_service
    if not request.app.state.settings.webdav.url:
        return {"item": None, "source": "webdav", "error": "webdav_not_configured"}
    files = await wd.list_remote_files(refresh=False)
    if not files:
        return {"item": None, "source": "webdav"}
    return {"item": _item_dict(files[0]), "source": "webdav"}


@router.get("/recent")
async def recent(
    request: Request,
    _: bool = Depends(require_auth),
    n: int = Query(5, ge=1, le=20),
):
    wd = request.app.state.webdav_service
    if not request.app.state.settings.webdav.url:
        return {"items": [], "source": "webdav", "error": "webdav_not_configured"}
    files = await wd.list_remote_files(refresh=False)
    return {"items": [_item_dict(f) for f in files[:n]], "source": "webdav"}
