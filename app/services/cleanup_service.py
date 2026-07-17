"""Auto cleanup: delete after WebDAV upload + enforce disk quota (oldest first)."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

import app.db.engine as db_engine
from app.db.models import Segment

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)


class CleanupService:
    def __init__(self, settings: "Settings"):
        self.settings = settings
        self.last_run: dict[str, Any] | None = None

    def _cfg(self):
        return self.settings.cleanup

    def _output_root(self) -> Path:
        return self.settings.resolve_path(self.settings.recording.output_dir)

    def _abs(self, rel: str | None) -> Path | None:
        if not rel:
            return None
        p = Path(rel)
        if p.is_absolute():
            return p
        return (self._output_root() / rel).resolve()

    def disk_usage_bytes(self) -> int:
        root = self._output_root()
        if not root.exists():
            return 0
        total = 0
        for p in root.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
        return total

    async def delete_segment_files_and_row(self, segment_id: int, *, reason: str) -> bool:
        assert db_engine.SessionLocal is not None
        async with db_engine.SessionLocal() as session:
            seg = await session.get(Segment, segment_id)
            if not seg:
                return False
            for rel in (seg.rel_path_mp4, seg.rel_path_cflv):
                path = self._abs(rel)
                if path and path.exists():
                    try:
                        path.unlink()
                        logger.info("cleanup deleted file %s (%s)", path, reason)
                    except OSError as e:
                        logger.warning("cleanup unlink failed %s: %s", path, e)
            await session.delete(seg)
            await session.commit()
        self._prune_empty_dirs()
        return True

    def _prune_empty_dirs(self) -> None:
        root = self._output_root()
        if not root.exists():
            return
        # bottom-up remove empty date/hour dirs
        for path in sorted(root.rglob("*"), reverse=True):
            if path.is_dir():
                try:
                    next(path.iterdir())
                except StopIteration:
                    try:
                        path.rmdir()
                    except OSError:
                        pass
                except OSError:
                    pass

    async def cleanup_synced(self) -> dict[str, Any]:
        """Delete local files (and DB rows) for segments already uploaded to WebDAV."""
        cfg = self._cfg()
        if not cfg.delete_after_sync:
            return {"deleted": 0, "skipped": True, "reason": "delete_after_sync disabled"}

        assert db_engine.SessionLocal is not None
        deleted = 0
        async with db_engine.SessionLocal() as session:
            result = await session.execute(
                select(Segment)
                .where(Segment.synced.is_(True), Segment.status == "ready")
                .order_by(Segment.id.asc())
                .limit(max(1, cfg.batch_size))
            )
            segs = list(result.scalars().all())
            ids = [s.id for s in segs]

        for sid in ids:
            if await self.delete_segment_files_and_row(sid, reason="after_webdav_sync"):
                deleted += 1
        return {"deleted": deleted, "ids": ids}

    async def enforce_quota(self) -> dict[str, Any]:
        """While total size > max, delete oldest ready segments (prefer already-synced)."""
        cfg = self._cfg()
        if not cfg.enabled:
            return {"deleted": 0, "skipped": True, "reason": "cleanup disabled"}

        max_bytes = int(cfg.max_gb * 1024 * 1024 * 1024)
        if max_bytes <= 0:
            return {"deleted": 0, "skipped": True, "reason": "max_gb <= 0"}

        target = int(max_bytes * max(0.1, min(0.99, cfg.target_ratio)))
        usage = self.disk_usage_bytes()
        if usage <= max_bytes:
            return {
                "deleted": 0,
                "usage_bytes": usage,
                "max_bytes": max_bytes,
                "under_quota": True,
            }

        assert db_engine.SessionLocal is not None
        deleted = 0
        freed = 0
        # Prefer synced first, then oldest by id/ended_at
        async with db_engine.SessionLocal() as session:
            result = await session.execute(
                select(Segment)
                .where(Segment.status.in_(("ready", "failed")))
                .order_by(Segment.synced.desc(), Segment.id.asc())
                .limit(500)
            )
            candidates = list(result.scalars().all())
            plan: list[tuple[int, int]] = []
            for seg in candidates:
                size = seg.bytes_mp4 or seg.bytes_cflv or 0
                if size <= 0:
                    path = self._abs(seg.rel_path_mp4) or self._abs(seg.rel_path_cflv)
                    if path and path.exists():
                        try:
                            size = path.stat().st_size
                        except OSError:
                            size = 0
                plan.append((seg.id, size))

        for sid, size in plan:
            if usage - freed <= target:
                break
            if await self.delete_segment_files_and_row(sid, reason="disk_quota"):
                deleted += 1
                freed += size

        usage_after = self.disk_usage_bytes()
        return {
            "deleted": deleted,
            "freed_bytes": freed,
            "usage_bytes_before": usage,
            "usage_bytes_after": usage_after,
            "max_bytes": max_bytes,
            "target_bytes": target,
        }

    async def run_all(self) -> dict[str, Any]:
        synced = await self.cleanup_synced()
        quota = await self.enforce_quota()
        result = {
            "synced_cleanup": synced,
            "quota": quota,
            "usage_bytes": self.disk_usage_bytes(),
            "finished_at": datetime.now().isoformat(),
        }
        self.last_run = result
        logger.info(
            "cleanup done synced_del=%s quota_del=%s usage=%.2fMB",
            synced.get("deleted"),
            quota.get("deleted"),
            result["usage_bytes"] / 1024 / 1024,
        )
        return result

    def snapshot(self) -> dict[str, Any]:
        cfg = self._cfg()
        usage = self.disk_usage_bytes()
        max_bytes = int(cfg.max_gb * 1024 * 1024 * 1024)
        return {
            "enabled": cfg.enabled,
            "delete_after_sync": cfg.delete_after_sync,
            "max_gb": cfg.max_gb,
            "target_ratio": cfg.target_ratio,
            "interval_sec": cfg.interval_sec,
            "usage_bytes": usage,
            "usage_mb": round(usage / 1024 / 1024, 2),
            "max_bytes": max_bytes,
            "usage_ratio": (usage / max_bytes) if max_bytes > 0 else 0,
            "last_run": self.last_run,
        }
