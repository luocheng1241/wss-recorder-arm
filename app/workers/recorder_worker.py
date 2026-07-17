"""Threaded WSS recorder worker (adapted from recorder_v2.WSSRecorder)."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import websocket

from app.core import protocol
from app.core.paths import build_segment_paths

logger = logging.getLogger(__name__)


@dataclass
class RecorderStats:
    running: bool = False
    connected: bool = False
    total_bytes: int = 0
    frame_count: int = 0
    segment_index: int = 0
    segment_bytes: int = 0
    segment_frames: int = 0
    current_cflv: str | None = None
    current_mp4: str | None = None
    started_at: float | None = None
    last_error: str | None = None
    ticket_expired: bool = False


SegmentClosedCb = Callable[[dict[str, Any]], None]
TicketExpiredCb = Callable[[], None]
StatsCb = Callable[[RecorderStats], None]


class RecorderWorker:
    """Run websocket-client in a background thread; never convert on WS thread."""

    def __init__(
        self,
        ticket: str,
        *,
        device_id: str,
        relay_url: str,
        vnsp_version: str,
        output_dir: str,
        segment_duration: int = 300,
        on_segment_closed: SegmentClosedCb | None = None,
        on_ticket_expired: TicketExpiredCb | None = None,
        on_stats: StatsCb | None = None,
    ):
        self.ticket = ticket
        self.device_id = device_id
        self.relay_url = relay_url.rstrip("/")
        self.vnsp_version = vnsp_version
        self.output_dir = output_dir
        self.segment_duration = segment_duration
        self.on_segment_closed = on_segment_closed
        self.on_ticket_expired = on_ticket_expired
        self.on_stats = on_stats

        self.url = f"{self.relay_url}/?ticket={ticket}"
        self.ws: websocket.WebSocketApp | None = None
        self.thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.stats = RecorderStats()
        self._raw_file = None
        self._segment_start = 0.0
        self._ping_seq = 0
        self._ping_thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self._stop.clear()
        self.stats = RecorderStats(running=True, started_at=time.time())
        self.thread = threading.Thread(target=self._run, name="wss-recorder", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.stats.running = False
        ws = self.ws
        if ws:
            try:
                ws.send(protocol.play_live_stop(self.device_id))
            except Exception:
                pass
            try:
                ws.close()
            except Exception:
                pass
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        self._close_segment()
        self._emit_stats()

    def _run(self) -> None:
        self.ws = websocket.WebSocketApp(
            self.url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        try:
            self.ws.run_forever(sslopt={"cert_reqs": 0})
        except Exception as e:
            logger.exception("run_forever failed: %s", e)
            self.stats.last_error = str(e)
        finally:
            self.stats.running = False
            self.stats.connected = False
            self._close_segment()
            self._emit_stats()

    def _on_open(self, ws) -> None:
        logger.info("connected to relay")
        self.stats.connected = True
        self.stats.running = True
        try:
            ws.send(protocol.login_message(self.device_id, self.vnsp_version))
            time.sleep(0.5)
            ws.send(protocol.ping_message(self._ping_seq))
            self._ping_seq += 1
            ws.send(protocol.play_live_start(self.device_id))
            logger.info("login + playLiveStart sent")
        except Exception as e:
            self.stats.last_error = str(e)
            logger.error("on_open send failed: %s", e)
        self._ping_thread = threading.Thread(target=self._ping_loop, daemon=True)
        self._ping_thread.start()
        self._emit_stats()

    def _ping_loop(self) -> None:
        while not self._stop.is_set() and self.stats.running:
            time.sleep(15)
            try:
                if self.ws and self.stats.running and not self._stop.is_set():
                    self.ws.send(protocol.ping_message(self._ping_seq))
                    self._ping_seq += 1
            except Exception:
                break

    def _on_message(self, ws, message) -> None:
        if isinstance(message, bytes):
            with self._lock:
                if self._segment_start and (time.time() - self._segment_start) >= self.segment_duration:
                    self._close_segment()
                if self._raw_file is None:
                    self._open_segment()
                if self._raw_file:
                    self._raw_file.write(message)
                    self.stats.total_bytes += len(message)
                    self.stats.segment_bytes += len(message)
                    self.stats.frame_count += 1
                    self.stats.segment_frames += 1
            if self.stats.frame_count % 30 == 0:
                self._emit_stats()
            return

        try:
            data = json.loads(message)
        except Exception:
            return
        cmd = data.get("cmd", "")
        if cmd in ("mediaQualityMetrics", "pong"):
            return
        if protocol.is_ticket_expired_payload(data):
            logger.warning("ticket expired: %s", data.get("resultMsg"))
            self.stats.ticket_expired = True
            self.stats.running = False
            if self.on_ticket_expired:
                try:
                    self.on_ticket_expired()
                except Exception:
                    logger.exception("on_ticket_expired callback")
            try:
                ws.close()
            except Exception:
                pass
            return
        logger.info("server %s: %s", cmd, data.get("resultMsg", "")[:120])

    def _on_error(self, ws, error) -> None:
        self.stats.last_error = str(error)
        logger.error("ws error: %s", error)
        self._emit_stats()

    def _on_close(self, ws, close_code, close_msg) -> None:
        logger.info("ws closed code=%s", close_code)
        self.stats.connected = False
        self.stats.running = False
        self._close_segment()
        self._emit_stats()

    def _open_segment(self) -> None:
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        cflv, mp4 = build_segment_paths(self.output_dir, datetime.now(), self.stats.segment_index)
        self._raw_file = open(cflv, "wb")
        self._segment_start = time.time()
        self.stats.segment_bytes = 0
        self.stats.segment_frames = 0
        self.stats.segment_index += 1
        self.stats.current_cflv = cflv
        self.stats.current_mp4 = mp4
        logger.info("segment #%s -> %s", self.stats.segment_index, mp4)

    def _close_segment(self) -> None:
        if self._raw_file and not self._raw_file.closed:
            self._raw_file.close()
        self._raw_file = None
        cflv = self.stats.current_cflv
        mp4 = self.stats.current_mp4
        frames = self.stats.segment_frames
        nbytes = self.stats.segment_bytes
        started = self._segment_start
        self.stats.current_cflv = None
        self.stats.current_mp4 = None
        self._segment_start = 0.0
        if not cflv or frames <= 0 or not Path(cflv).exists():
            return
        meta = {
            "cflv_path": cflv,
            "mp4_path": mp4,
            "bytes_cflv": nbytes,
            "frames": frames,
            "segment_index": self.stats.segment_index,
            "started_at": datetime.fromtimestamp(started) if started else datetime.now(),
            "ended_at": datetime.now(),
        }
        if self.on_segment_closed:
            try:
                self.on_segment_closed(meta)
            except Exception:
                logger.exception("on_segment_closed")

    def _emit_stats(self) -> None:
        if self.on_stats:
            try:
                self.on_stats(self.stats)
            except Exception:
                pass
