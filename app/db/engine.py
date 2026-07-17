from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import Settings


class Base(DeclarativeBase):
    pass


engine = None
SessionLocal: async_sessionmaker[AsyncSession] | None = None


def init_engine(settings: Settings):
    global engine, SessionLocal
    db_path = settings.resolve_path(settings.db.path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    engine = create_async_engine(url, echo=False)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    return engine


async def get_session():
    assert SessionLocal is not None
    async with SessionLocal() as session:
        yield session
