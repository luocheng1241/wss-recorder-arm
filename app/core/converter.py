"""CFLV -> MP4 conversion (ported from recorder_v2.WSSRecorder._convert_cflv_to_mp4)."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def ffmpeg_available() -> bool:
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def convert_cflv_to_mp4(cflv_path: str, mp4_path: str) -> tuple[bool, str]:
    """Extract HEVC NALUs from CFLV and remux to MP4 via ffmpeg.

    Returns (ok, error_message).
    """
    cflv_path = str(cflv_path)
    mp4_path = str(mp4_path)

    try:
        with open(cflv_path, "rb") as f:
            data = f.read()
    except OSError as e:
        return False, f"read failed: {e}"

    if len(data) < 30:
        return False, "cflv too small"

    nalus: list[tuple[int, bytes]] = []
    i = 0
    while i < len(data) - 4:
        if data[i : i + 4] == b"\x00\x00\x00\x01":
            nalu_type = (data[i + 4] >> 1) & 0x3F
            j = i + 4
            while j < len(data) - 3:
                if data[j : j + 3] == b"\x00\x00\x01" or data[j : j + 4] == b"\x00\x00\x00\x01":
                    break
                j += 1
            nalus.append((nalu_type, data[i:j]))
            i = j
        else:
            i += 1

    if not nalus:
        return False, "no NALUs found"

    vps = sps = pps = None
    video_frames: list[bytes] = []
    for nalu_type, nalu_data in nalus:
        if nalu_type == 32:
            vps = nalu_data
        elif nalu_type == 33:
            sps = nalu_data
        elif nalu_type == 34:
            pps = nalu_data
        elif nalu_type in (1, 2, 3, 4, 5, 19, 20):
            video_frames.append(nalu_data)

    if not vps or not sps or not pps:
        return False, "missing VPS/SPS/PPS"
    if not video_frames:
        return False, "no video frames"

    hevc_path = cflv_path.replace(".cflv", ".hevc")
    flv_path = cflv_path.replace(".cflv", ".flv")
    audio_path = cflv_path.replace(".cflv", ".aac")

    try:
        with open(hevc_path, "wb") as out:
            out.write(vps)
            out.write(sps)
            out.write(pps)
            for frame in video_frames:
                out.write(frame)

        with open(flv_path, "wb") as out:
            out.write(data)

        has_audio = False
        try:
            r_audio = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", flv_path, "-vn", "-c:a", "aac", audio_path],
                capture_output=True,
                timeout=60,
            )
            has_audio = (
                r_audio.returncode == 0
                and os.path.exists(audio_path)
                and os.path.getsize(audio_path) > 0
            )
        except Exception:
            has_audio = False

        Path(mp4_path).parent.mkdir(parents=True, exist_ok=True)

        if has_audio:
            cmd = [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "hevc",
                "-i",
                hevc_path,
                "-i",
                audio_path,
                "-c:v",
                "copy",
                "-c:a",
                "copy",
                "-shortest",
                "-movflags",
                "+faststart",
                mp4_path,
            ]
            timeout = 120
        else:
            cmd = [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "hevc",
                "-i",
                hevc_path,
                "-c:v",
                "copy",
                "-movflags",
                "+faststart",
                mp4_path,
            ]
            timeout = 60

        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if r.returncode == 0 and os.path.exists(mp4_path) and os.path.getsize(mp4_path) > 0:
            return True, ""
        err = r.stderr.decode(errors="ignore")[:300]
        return False, err or "ffmpeg failed"
    except Exception as e:
        return False, str(e)
    finally:
        for p in (hevc_path, flv_path, audio_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
