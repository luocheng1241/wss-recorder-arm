"""Import existing MP4 files under recordings into SQLite."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import load_settings
from app.core.paths import to_rel_path
import app.db.engine as db_engine
from app.db.engine import init_engine
from app.db.migrate import init_db
from app.db.models import Segment


async def main():
    settings = load_settings()
    init_engine(settings)
    await init_db()
    root = settings.resolve_path(settings.recording.output_dir)
    if not root.exists():
        print("no output dir", root)
        return
    count = 0
    assert db_engine.SessionLocal is not None
    async with db_engine.SessionLocal() as session:
        for mp4 in root.rglob("*.mp4"):
            rel = to_rel_path(mp4, root)
            existing = await session.execute(
                __import__("sqlalchemy").select(Segment).where(Segment.rel_path_mp4 == rel)
            )
            if existing.scalar_one_or_none():
                continue
            seg = Segment(
                rel_path_mp4=rel,
                bytes_mp4=mp4.stat().st_size,
                status="ready",
                started_at=datetime.fromtimestamp(mp4.stat().st_mtime),
                ended_at=datetime.fromtimestamp(mp4.stat().st_mtime),
                synced=False,
            )
            session.add(seg)
            count += 1
        await session.commit()
    print("imported", count)


if __name__ == "__main__":
    asyncio.run(main())
