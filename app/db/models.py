from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.engine import Base


class Segment(Base):
    __tablename__ = "segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rel_path_cflv: Mapped[str | None] = mapped_column(String(512), nullable=True)
    rel_path_mp4: Mapped[str | None] = mapped_column(String(512), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    bytes_cflv: Mapped[int] = mapped_column(Integer, default=0)
    bytes_mp4: Mapped[int] = mapped_column(Integer, default=0)
    frames: Mapped[int] = mapped_column(Integer, default=0)
    segment_index: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="recording", index=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TicketMeta(Base):
    __tablename__ = "ticket_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    obtained_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    ttl_sec: Mapped[int] = mapped_column(Integer, default=86400)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    state: Mapped[str] = mapped_column(String(32), default="EMPTY")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ok_count: Mapped[int] = mapped_column(Integer, default=0)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
