"""Load config.yaml with WSS_* environment overrides."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parent.parent


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080


class AuthConfig(BaseModel):
    password: str = "changeme"
    session_secret: str = "change-me-to-a-long-random-string"
    session_max_age_sec: int = 604800


class DeviceConfig(BaseModel):
    device_id: str = "14eaa12a154e"
    relay_url: str = "wss://relay8-bj-ies.reservehemu.com:50374"
    vnsp_version: str = "1.0.30"
    app_id: str = "7ffe54b078ee92ed4f91c94b0eef16e6"
    player_app_id: str = "c9ozz47akmvfkriiejiacubru0grlsuw"
    player_api_url: str = "https://open.cmviot.cn/vnplayer-bff/player/api-biz"
    base_url: str = "https://qly.cmviot.cn"


class RecordingConfig(BaseModel):
    output_dir: str = "data/recordings"
    segment_duration: int = 300
    keep_raw: bool = False
    convert_workers: int = 1
    # Start recording automatically when service boots (if ticket available)
    auto_start: bool = True


class TicketConfig(BaseModel):
    ttl_sec: int = 86400
    warn_sec: int = 3600
    auto_refresh: bool = True
    token_cache_path: str = "data/token_cache.json"


class WebDAVConfig(BaseModel):
    enabled: bool = False
    url: str = ""
    username: str = ""
    password: str = ""
    remote_base: str = "wss-recorder"
    cron: str = "0 */6 * * *"
    verify_ssl: bool = True
    batch_size: int = 50
    delete_local_after_sync: bool = True
    # Library / Live always read from WebDAV (not local disk)
    play_from_webdav: bool = True


class CleanupConfig(BaseModel):
    """Local disk housekeeping."""

    enabled: bool = True
    # After successful WebDAV upload, delete local MP4 + DB row
    delete_after_sync: bool = True
    # When recordings total size exceeds max_gb, delete oldest until target_ratio
    max_gb: float = 20.0
    target_ratio: float = 0.85
    # Periodic cleanup interval (seconds)
    interval_sec: int = 300
    batch_size: int = 100


class DbConfig(BaseModel):
    path: str = "data/app.db"


class Settings(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    device: DeviceConfig = Field(default_factory=DeviceConfig)
    recording: RecordingConfig = Field(default_factory=RecordingConfig)
    ticket: TicketConfig = Field(default_factory=TicketConfig)
    webdav: WebDAVConfig = Field(default_factory=WebDAVConfig)
    cleanup: CleanupConfig = Field(default_factory=CleanupConfig)
    db: DbConfig = Field(default_factory=DbConfig)
    data_dir: str = "data"

    def resolve_path(self, path: str) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        return (ROOT / p).resolve()


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _env_overrides() -> dict[str, Any]:
    o: dict[str, Any] = {}
    if v := os.getenv("WSS_CONSOLE_PASSWORD"):
        o.setdefault("auth", {})["password"] = v
    if v := os.getenv("WSS_SESSION_SECRET"):
        o.setdefault("auth", {})["session_secret"] = v
    if v := os.getenv("WSS_DEVICE_ID"):
        o.setdefault("device", {})["device_id"] = v
    if v := os.getenv("WSS_OUTPUT_DIR"):
        o.setdefault("recording", {})["output_dir"] = v
    if v := os.getenv("WSS_SEGMENT_DURATION"):
        o.setdefault("recording", {})["segment_duration"] = int(v)
    if v := os.getenv("WSS_WEBDAV_PASSWORD"):
        o.setdefault("webdav", {})["password"] = v
    if v := os.getenv("WSS_WEBDAV_URL"):
        o.setdefault("webdav", {})["url"] = v
    if v := os.getenv("WSS_RELAY_URL"):
        o.setdefault("device", {})["relay_url"] = v
    if v := os.getenv("WSS_DB_PATH"):
        o.setdefault("db", {})["path"] = v
    if v := os.getenv("WSS_DATA_DIR"):
        o["data_dir"] = v
    if v := os.getenv("WSS_CLEANUP_MAX_GB"):
        o.setdefault("cleanup", {})["max_gb"] = float(v)
    if v := os.getenv("WSS_CLEANUP_ENABLED"):
        o.setdefault("cleanup", {})["enabled"] = v.lower() in ("1", "true", "yes")
    if v := os.getenv("WSS_DELETE_AFTER_SYNC"):
        val = v.lower() in ("1", "true", "yes")
        o.setdefault("cleanup", {})["delete_after_sync"] = val
        o.setdefault("webdav", {})["delete_local_after_sync"] = val
    if v := os.getenv("WSS_AUTO_START"):
        o.setdefault("recording", {})["auto_start"] = v.lower() in ("1", "true", "yes")
    return o


def load_settings(config_path: str | Path | None = None) -> Settings:
    path = Path(config_path or os.getenv("WSS_CONFIG") or (ROOT / "config.yaml"))
    raw: dict[str, Any] = {}
    if path.is_file():
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    else:
        example = ROOT / "config.example.yaml"
        if example.is_file():
            with open(example, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
    raw = _deep_merge(raw, _env_overrides())
    return Settings.model_validate(raw)


@lru_cache
def get_settings() -> Settings:
    return load_settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
