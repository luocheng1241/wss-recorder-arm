"""Library & playback — primarily from WebDAV remote files."""

from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.deps import require_auth

router = APIRouter(prefix="/api/recordings", tags=["recordings"])


def _item_dict(f: dict) -> dict:
    return {
        "id": f.get("id") or f.get("rel_path"),
        "rel_path_mp4": f.get("rel_path"),
        "rel_path": f.get("rel_path"),
        "name": f.get("name"),
        "bytes_mp4": f.get("bytes_mp4") or f.get("size") or 0,
        "size": f.get("size") or 0,
        "status": f.get("status") or "ready",
        "synced": True,
        "source": "webdav",
        "modified": f.get("modified"),
    }


@router.get("")
async def list_recordings(
    request: Request,
    _: bool = Depends(require_auth),
    date: str | None = None,
    hour: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    refresh: bool = False,
):
    wd = request.app.state.webdav_service
    if not request.app.state.settings.webdav.url:
        return {
            "items": [],
            "source": "webdav",
            "error": "webdav_not_configured",
            "limit": limit,
            "offset": offset,
        }
    prefix = date
    if date and hour:
        prefix = f"{date}/{hour}"
    try:
        files = await wd.list_remote_files(date=prefix, refresh=refresh)
    except Exception as e:
        raise HTTPException(502, f"webdav list failed: {e}") from e
    page = files[offset : offset + limit]
    return {
        "items": [_item_dict(f) for f in page],
        "total": len(files),
        "limit": limit,
        "offset": offset,
        "source": "webdav",
    }


@router.get("/days")
async def list_days(request: Request, _: bool = Depends(require_auth)):
    wd = request.app.state.webdav_service
    if not request.app.state.settings.webdav.url:
        return {"days": [], "source": "webdav", "error": "webdav_not_configured"}
    try:
        days = await wd.list_days()
    except Exception as e:
        raise HTTPException(502, f"webdav list failed: {e}") from e
    return {"days": days, "source": "webdav"}


@router.get("/file")
async def stream_by_path(
    request: Request,
    path: str = Query(..., description="relative path under remote_base, e.g. 2026-07-12/15/stream.mp4"),
    _: bool = Depends(require_auth),
):
    return await _stream_path(request, path)


@router.get("/{file_id:path}/file")
async def stream_by_id(
    file_id: str,
    request: Request,
    _: bool = Depends(require_auth),
):
    # file_id is rel_path (may contain slashes)
    return await _stream_path(request, file_id)


@router.get("/{file_id:path}")
async def get_meta(
    file_id: str,
    request: Request,
    _: bool = Depends(require_auth),
):
    if file_id in ("days", "file"):
        raise HTTPException(404, "not found")
    wd = request.app.state.webdav_service
    meta = await wd.get_file_meta(file_id)
    if not meta:
        raise HTTPException(404, "not found on webdav")
    return _item_dict(meta)


async def _stream_path(request: Request, path: str):
    wd = request.app.state.webdav_service
    if not request.app.state.settings.webdav.url:
        raise HTTPException(400, "webdav not configured")
    path = unquote(path).lstrip("/")
    range_header = request.headers.get("range")
    try:
        resp, client = await wd.stream_remote(path, range_header)
    except Exception as e:
        raise HTTPException(502, f"webdav open failed: {e}") from e

    if resp.status_code >= 400:
        await resp.aclose()
        await client.aclose()
        raise HTTPException(resp.status_code, f"webdav error {resp.status_code}")

    async def body():
        try:
            async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": resp.headers.get("content-type", "video/mp4"),
    }
    if "content-length" in resp.headers:
        headers["Content-Length"] = resp.headers["content-length"]
    if "content-range" in resp.headers:
        headers["Content-Range"] = resp.headers["content-range"]
    filename = path.split("/")[-1]
    headers["Content-Disposition"] = f'inline; filename="{filename}"'

    return StreamingResponse(
        body(),
        status_code=resp.status_code,
        headers=headers,
        media_type=headers["Content-Type"],
    )
