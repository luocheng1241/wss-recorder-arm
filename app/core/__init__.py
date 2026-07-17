"""Segment path helpers (ported from recorder_v2.build_segment_paths)."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


def build_segment_paths(
    output_dir: str | Path,
    now: datetime | None = None,
    segment_index: int = 0,
) -> tuple[str, str]:
    """Return (cflv_path, mp4_path) under YYYY-MM-DD/HH/."""
    now = now or datetime.now()
    segment_dir = Path(output_dir) / now.strftime("%Y-%m-%d") / now.strftime("%H")
    segment_dir.mkdir(parents=True, exist_ok=True)

    timestamp = now.strftime("%Y%m%d_%H%M%S")
    base_name = f"stream_{timestamp}_p{segment_index:03d}"
    cflv = str(segment_dir / f"{base_name}.cflv")
    mp4 = str(segment_dir / f"{base_name}.mp4")
    return cflv, mp4


def to_rel_path(path: str | Path, root: str | Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def abs_from_rel(rel: str, root: str | Path) -> Path:
    return (Path(root) / rel).resolve()
