"""Smoke-test CFLV -> MP4 conversion."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.converter import convert_cflv_to_mp4, ffmpeg_available


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/smoke_convert.py <file.cflv> [out.mp4]")
        sys.exit(1)
    cflv = sys.argv[1]
    mp4 = sys.argv[2] if len(sys.argv) > 2 else cflv.replace(".cflv", ".mp4")
    print("ffmpeg:", ffmpeg_available())
    ok, err = convert_cflv_to_mp4(cflv, mp4)
    print("ok:", ok, "err:", err, "out:", mp4)


if __name__ == "__main__":
    main()
