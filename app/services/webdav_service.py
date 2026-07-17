"""WebDAV batch sync + remote library browse/stream."""

from __future__ import annotations

import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx
from sqlalchemy import select

import app.db.engine as db_engine
from app.db.models import Segment, SyncLog

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)

DAV_NS = {"d": "DAV:"}


class WebDAVService:
    def __init__(self, settings: "Settings", cleanup_service=None):
        self.settings = settings
        self.cleanup_service = cleanup_service
        self._lock = asyncio.Lock()
        self.last_run: dict[str, Any] | None = None
        self.running = False
        self._list_cache: list[dict[str, Any]] | None = None
        self._list_cache_at: float = 0

    def set_cleanup(self, cleanup_service) -> None:
        self.cleanup_service = cleanup_service

    def config_public(self) -> dict[str, Any]:
        w = self.settings.webdav
        return {
            "enabled": w.enabled,
            "url": w.url,
            "username": w.username,
            "password_set": bool(w.password),
            "remote_base": w.remote_base,
            "cron": w.cron,
            "verify_ssl": w.verify_ssl,
            "batch_size": w.batch_size,
            "delete_local_after_sync": w.delete_local_after_sync,
            "play_from_webdav": getattr(w, "play_from_webdav", True),
            "configured": bool(w.url),
        }

    def update_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        w = self.settings.webdav
        for key in (
            "enabled",
            "url",
            "username",
            "password",
            "remote_base",
            "cron",
            "verify_ssl",
            "batch_size",
            "delete_local_after_sync",
            "play_from_webdav",
        ):
            if key in payload and payload[key] is not None:
                if key == "password" and payload[key] == "":
                    continue
                if hasattr(w, key):
                    setattr(w, key, payload[key])
        self.invalidate_list_cache()
        return self.config_public()

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "last_run": self.last_run,
            "config": self.config_public(),
        }

    def invalidate_list_cache(self) -> None:
        self._list_cache = None
        self._list_cache_at = 0

    def _client_kwargs(self) -> dict[str, Any]:
        w = self.settings.webdav
        auth = (w.username, w.password) if w.username else None
        return {
            "auth": auth,
            "verify": w.verify_ssl,
            "timeout": 120.0,
            "follow_redirects": True,
        }

    def _base_url(self) -> str:
        w = self.settings.webdav
        return w.url if w.url.endswith("/") else w.url + "/"

    def remote_rel_for_local(self, rel_path_mp4: str) -> str:
        base = self.settings.webdav.remote_base.strip("/")
        rel = (rel_path_mp4 or "").replace("\\", "/").lstrip("/")
        return f"{base}/{rel}" if base else rel

    def remote_url_for_rel(self, remote_rel: str) -> str:
        parts = remote_rel.strip("/").split("/")
        enc = "/".join(quote(p, safe="") for p in parts if p)
        if remote_rel.endswith("/"):
            enc += "/"
        return urljoin(self._base_url(), enc)

    async def pending_count(self) -> int:
        assert db_engine.SessionLocal is not None
        async with db_engine.SessionLocal() as session:
            result = await session.execute(
                select(Segment).where(Segment.status == "ready", Segment.synced.is_(False))
            )
            return len(list(result.scalars().all()))

    def _abs(self, rel: str | None) -> Path:
        root = self.settings.resolve_path(self.settings.recording.output_dir)
        if not rel:
            return Path("")
        p = Path(rel)
        return p if p.is_absolute() else (root / rel).resolve()

    async def sync_now(self) -> dict[str, Any]:
        if self._lock.locked():
            return {"ok": False, "error": "sync already running"}
        async with self._lock:
            result = await self._sync_batch()
            self.invalidate_list_cache()
            return result

    async def _sync_batch(self) -> dict[str, Any]:
        w = self.settings.webdav
        if not w.url:
            return {"ok": False, "error": "webdav url not configured"}

        self.running = True
        ok_count = 0
        fail_count = 0
        messages: list[str] = []
        assert db_engine.SessionLocal is not None

        async with db_engine.SessionLocal() as session:
            log = SyncLog()
            session.add(log)
            await session.commit()
            await session.refresh(log)
            log_id = log.id

            result = await session.execute(
                select(Segment)
                .where(Segment.status == "ready", Segment.synced.is_(False))
                .order_by(Segment.ended_at.asc())
                .limit(w.batch_size)
            )
            segs = list(result.scalars().all())

        base = self._base_url()

        async with httpx.AsyncClient(**self._client_kwargs()) as client:
            for seg in segs:
                local = self._abs(seg.rel_path_mp4)
                if not local.exists():
                    fail_count += 1
                    messages.append(f"missing {seg.rel_path_mp4}")
                    continue
                remote_rel = self.remote_rel_for_local(seg.rel_path_mp4 or "")
                try:
                    await self._ensure_dirs(client, base, remote_rel)
                    remote_url = self.remote_url_for_rel(remote_rel)
                    data = await asyncio.to_thread(local.read_bytes)
                    resp = await client.put(remote_url, content=data)
                    if 200 <= resp.status_code < 300:
                        ok_count += 1
                        async with db_engine.SessionLocal() as session:
                            s = await session.get(Segment, seg.id)
                            if s:
                                s.synced = True
                                s.synced_at = datetime.now()
                                await session.commit()
                        if w.delete_local_after_sync and not self.cleanup_service:
                            try:
                                local.unlink()
                            except OSError:
                                pass
                    else:
                        fail_count += 1
                        messages.append(f"{remote_rel}: HTTP {resp.status_code}")
                except Exception as e:
                    fail_count += 1
                    messages.append(f"{remote_rel}: {e}")
                    logger.warning("webdav put failed: %s", e)

        summary = {
            "ok": fail_count == 0,
            "ok_count": ok_count,
            "fail_count": fail_count,
            "message": "; ".join(messages[:5]),
        }
        self.last_run = {**summary, "finished_at": datetime.now().isoformat()}
        async with db_engine.SessionLocal() as session:
            log = await session.get(SyncLog, log_id)
            if log:
                log.finished_at = datetime.now()
                log.ok_count = ok_count
                log.fail_count = fail_count
                log.message = summary["message"]
                await session.commit()
        self.running = False

        if self.cleanup_service and self.settings.cleanup.delete_after_sync and ok_count > 0:
            try:
                cleaned = await self.cleanup_service.cleanup_synced()
                summary["cleanup"] = cleaned
            except Exception as e:
                logger.warning("post-sync cleanup failed: %s", e)

        return summary

    async def _ensure_dirs(self, client: httpx.AsyncClient, base: str, remote_rel: str) -> None:
        parts = remote_rel.strip("/").split("/")[:-1]
        cur = ""
        for part in parts:
            cur = f"{cur}/{part}" if cur else part
            url = urljoin(base, quote(cur, safe="/") + "/")
            try:
                r = await client.request("MKCOL", url)
                if r.status_code not in (201, 405, 409, 301, 302):
                    logger.debug("MKCOL %s -> %s", url, r.status_code)
            except Exception:
                pass

    def _href_to_rel(self, href: str) -> str:
        if href.startswith("http://") or href.startswith("https://"):
            path = urlparse(href).path
        else:
            path = href
        path = unquote(path)
        base_path = urlparse(self._base_url()).path.rstrip("/")
        if base_path and path.startswith(base_path):
            path = path[len(base_path) :]
        path = path.lstrip("/")
        remote_base = self.settings.webdav.remote_base.strip("/")
        if remote_base and path.startswith(remote_base + "/"):
            path = path[len(remote_base) + 1 :]
        elif remote_base and path == remote_base:
            path = ""
        return path

    async def list_remote_files(
        self, *, date: str | None = None, refresh: bool = False
    ) -> list[dict[str, Any]]:
        w = self.settings.webdav
        if not w.url:
            return []

        now = time.time()
        if not refresh and self._list_cache is not None and (now - self._list_cache_at) < 30:
            items = self._list_cache
        else:
            items = await self._propfind_all_mp4()
            self._list_cache = items
            self._list_cache_at = now

        if date:
            items = [i for i in items if i["rel_path"].startswith(date)]
        return items

    async def _propfind_all_mp4(self) -> list[dict[str, Any]]:
        w = self.settings.webdav
        root_rel = w.remote_base.strip("/")
        root_url = self.remote_url_for_rel(root_rel + "/") if root_rel else self._base_url()

        body = """<?xml version="1.0" encoding="utf-8" ?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:getcontentlength/>
    <d:getlastmodified/>
    <d:resourcetype/>
    <d:displayname/>
  </d:prop>
</d:propfind>"""

        items: list[dict[str, Any]] = []
        async with httpx.AsyncClient(**self._client_kwargs()) as client:
            for depth in ("infinity", "1"):
                try:
                    resp = await client.request(
                        "PROPFIND",
                        root_url,
                        content=body,
                        headers={"Depth": depth, "Content-Type": "application/xml"},
                    )
                    if resp.status_code in (207, 200):
                        if depth == "infinity":
                            items = self._parse_propfind(resp.text)
                            if items or resp.status_code == 207:
                                break
                        else:
                            items = await self._walk_depth1(client, body, root_url)
                            break
                except Exception as e:
                    logger.warning("PROPFIND depth=%s failed: %s", depth, e)

        items = [i for i in items if i["rel_path"].lower().endswith(".mp4")]
        items.sort(key=lambda x: x["rel_path"], reverse=True)
        return items

    async def _walk_depth1(
        self, client: httpx.AsyncClient, body: str, root_url: str
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        resp = await client.request(
            "PROPFIND",
            root_url,
            content=body,
            headers={"Depth": "1", "Content-Type": "application/xml"},
        )
        if resp.status_code not in (207, 200):
            return items
        base = self.settings.webdav.remote_base.strip("/")
        level1 = self._parse_propfind(resp.text, include_dirs=True)
        for entry in level1:
            if entry.get("is_dir") and entry["rel_path"]:
                day_url = self.remote_url_for_rel(f"{base}/{entry['rel_path']}/" if base else entry["rel_path"] + "/")
                r2 = await client.request(
                    "PROPFIND",
                    day_url,
                    content=body,
                    headers={"Depth": "1", "Content-Type": "application/xml"},
                )
                if r2.status_code not in (207, 200):
                    continue
                for hour_entry in self._parse_propfind(r2.text, include_dirs=True):
                    if hour_entry.get("is_dir") and hour_entry["rel_path"]:
                        hour_url = self.remote_url_for_rel(
                            f"{base}/{hour_entry['rel_path']}/" if base else hour_entry["rel_path"] + "/"
                        )
                        r3 = await client.request(
                            "PROPFIND",
                            hour_url,
                            content=body,
                            headers={"Depth": "1", "Content-Type": "application/xml"},
                        )
                        if r3.status_code in (207, 200):
                            items.extend(self._parse_propfind(r3.text))
                    elif not hour_entry.get("is_dir"):
                        items.append(hour_entry)
            elif not entry.get("is_dir"):
                items.append(entry)
        return items

    def _parse_propfind(
        self, xml_text: str, include_dirs: bool = False
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return items
        for resp in root.findall("d:response", DAV_NS):
            href_el = resp.find("d:href", DAV_NS)
            if href_el is None or not href_el.text:
                continue
            href = href_el.text
            rel = self._href_to_rel(href)
            propstat = resp.find("d:propstat", DAV_NS)
            if propstat is None:
                continue
            prop = propstat.find("d:prop", DAV_NS)
            if prop is None:
                continue
            rtype = prop.find("d:resourcetype", DAV_NS)
            is_dir = rtype is not None and rtype.find("d:collection", DAV_NS) is not None
            if is_dir:
                if include_dirs and rel:
                    items.append(
                        {
                            "id": rel.rstrip("/"),
                            "rel_path": rel.rstrip("/"),
                            "name": rel.rstrip("/").split("/")[-1],
                            "size": 0,
                            "is_dir": True,
                            "modified": None,
                        }
                    )
                continue
            if not rel or rel.endswith("/"):
                continue
            length_el = prop.find("d:getcontentlength", DAV_NS)
            mod_el = prop.find("d:getlastmodified", DAV_NS)
            size = int(length_el.text) if length_el is not None and length_el.text else 0
            items.append(
                {
                    "id": rel,
                    "rel_path": rel,
                    "name": rel.split("/")[-1],
                    "size": size,
                    "bytes_mp4": size,
                    "is_dir": False,
                    "modified": mod_el.text if mod_el is not None else None,
                    "status": "ready",
                    "synced": True,
                    "source": "webdav",
                }
            )
        return items

    async def list_days(self) -> list[dict[str, Any]]:
        files = await self.list_remote_files()
        days: dict[str, int] = {}
        for f in files:
            parts = f["rel_path"].split("/")
            day = parts[0] if parts else ""
            if re.match(r"\d{4}-\d{2}-\d{2}", day):
                days[day] = days.get(day, 0) + 1
        return [{"date": k, "count": v} for k, v in sorted(days.items(), reverse=True)]

    async def get_file_meta(self, rel_path: str) -> dict[str, Any] | None:
        rel_path = unquote(rel_path).replace("\\", "/").lstrip("/")
        files = await self.list_remote_files()
        for f in files:
            if f["rel_path"] == rel_path:
                return f
        if not self.settings.webdav.url:
            return None
        remote_rel = self.remote_rel_for_local(rel_path)
        url = self.remote_url_for_rel(remote_rel)
        try:
            async with httpx.AsyncClient(**self._client_kwargs()) as client:
                r = await client.head(url)
                if r.status_code >= 400:
                    r = await client.request("GET", url, headers={"Range": "bytes=0-0"})
                if r.status_code in (200, 206):
                    size = int(r.headers.get("content-length") or 0)
                    if r.status_code == 206:
                        cr = r.headers.get("content-range", "")
                        m = re.search(r"/(\d+)$", cr)
                        if m:
                            size = int(m.group(1))
                    return {
                        "id": rel_path,
                        "rel_path": rel_path,
                        "name": rel_path.split("/")[-1],
                        "size": size,
                        "bytes_mp4": size,
                        "status": "ready",
                        "synced": True,
                        "source": "webdav",
                    }
        except Exception as e:
            logger.warning("webdav head failed %s: %s", rel_path, e)
        return None

    async def stream_remote(
        self, rel_path: str, range_header: str | None = None
    ) -> tuple[httpx.Response, httpx.AsyncClient]:
        remote_rel = self.remote_rel_for_local(rel_path.replace("\\", "/").lstrip("/"))
        url = self.remote_url_for_rel(remote_rel)
        headers = {}
        if range_header:
            headers["Range"] = range_header
        client = httpx.AsyncClient(**self._client_kwargs(), timeout=None)
        req = client.build_request("GET", url, headers=headers)
        resp = await client.send(req, stream=True)
        return resp, client
