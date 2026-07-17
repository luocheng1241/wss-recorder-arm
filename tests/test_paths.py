from datetime import datetime
from pathlib import Path

from app.core.paths import build_segment_paths


def test_build_segment_paths(tmp_path: Path):
    now = datetime(2026, 7, 12, 15, 30, 45)
    cflv, mp4 = build_segment_paths(tmp_path, now, 3)
    assert "2026-07-12" in cflv
    assert f"{Path(cflv).parts[-2]}" == "15" or "\\15\\" in cflv or "/15/" in cflv
    assert cflv.endswith("stream_20260712_153045_p003.cflv")
    assert mp4.endswith("stream_20260712_153045_p003.mp4")
