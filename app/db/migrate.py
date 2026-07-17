from __future__ import annotations

import app.db.engine as engine_mod
from app.db.engine import Base


async def init_db() -> None:
    eng = engine_mod.engine
    assert eng is not None, "call init_engine() first"
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
