"""Ticket REST API (ported from recorder_v2.get_ticket_from_token, no Playwright)."""

from __future__ import annotations

import hashlib
import http.cookiejar
import json
import logging
import os
import time
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


def generate_client_id() -> str:
    return hashlib.md5(os.urandom(16)).hexdigest().upper()


def generate_imei() -> str:
    return f"fake-{hashlib.md5(os.urandom(16)).hexdigest().upper()}"


def generate_session_id() -> str:
    return f"fake-{hashlib.md5(os.urandom(16)).hexdigest().upper()}"


def load_token_cache(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_token_cache(path: str, data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    existing = load_token_cache(path)
    existing.update(data)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def mask_ticket(ticket: str | None) -> str:
    if not ticket:
        return ""
    if len(ticket) <= 12:
        return ticket[:4] + "..."
    return f"{ticket[:8]}...{ticket[-4:]}"


def get_ticket_from_token(
    token: str,
    yy_token: str,
    cookies: dict[str, str],
    *,
    device_id: str,
    base_url: str,
    app_id: str,
    player_app_id: str,
    player_api_url: str,
) -> str | None:
    """Use session cookies + token to obtain a WSS ticket."""
    cookie_jar = http.cookiejar.CookieJar()
    for name, value in cookies.items():
        cookie = http.cookiejar.Cookie(
            version=0,
            name=name,
            value=value,
            port=None,
            port_specified=False,
            domain="qly.cmviot.cn",
            domain_specified=True,
            domain_initial_dot=False,
            path="/",
            path_specified=True,
            secure=True,
            expires=int(time.time()) + 86400,
            discard=False,
            comment=None,
            comment_url=None,
            rest={},
            rfc2109=False,
        )
        cookie_jar.set_cookie(cookie)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

    timestamp = str(int(time.time() * 1000))
    headers = {
        "accept": "application/json",
        "content-type": "application/json;charset=utf-8",
        "appid": app_id,
        "clientid": generate_client_id(),
        "imei": generate_imei(),
        "sessionid": generate_session_id(),
        "timestamp": timestamp,
        "token": token or "FROM_SESSION",
        "origin": base_url,
        "referer": f"{base_url}/normal/hubs/home",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
        ),
    }

    device_token = None
    resolved_device_id = device_id

    try:
        body = json.dumps(
            {
                "storeId": "",
                "region": "",
                "type": 0,
                "isOrderInfos": 1,
                "isThumbnailUrl": 1,
                "page": 1,
                "pageSize": 50,
                "isStared": 1,
                "isOwnerDomain": 1,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/frvm-fe-bff/api/device/device-list",
            data=body,
            headers=headers,
            method="POST",
        )
        with opener.open(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            logger.info("device-list resultCode=%s", data.get("resultCode"))
            if data.get("resultCode") == "000000":
                devices = data.get("data", [])
                if isinstance(devices, dict):
                    devices = devices.get("list", [])
                if devices:
                    device = devices[0]
                    device_token = device.get("deviceToken", "")
                    resolved_device_id = device.get("deviceId", device_id) or device_id
    except Exception as e:
        logger.warning("device-list failed: %s", e)

    if not device_token:
        logger.error("no deviceToken")
        return None

    player_headers = {
        "accept": "*/*",
        "content-type": "application/json",
        "origin": "https://open.cmviot.cn",
        "referer": (
            "https://open.cmviot.cn/websdk/2.57.0/main.html"
            "?uuid=parent-webcomponents-single&version=2.57.0"
        ),
        "sdkversion": "2.57.0",
        "sessionid": "sessionId",
        "timestamp": str(int(time.time() * 1000)),
        "version": "v6.35.0",
        "user-agent": headers["user-agent"],
    }

    try:
        body = json.dumps(
            {
                "parameters": {
                    "deviceSn": resolved_device_id,
                    "type": "1",
                    "effectiveTime": 86400,
                },
                "path": "/cmiot/v2/api/device/wss/address",
                "method": "GET",
                "token": device_token,
                "type": "0",
                "appid": player_app_id,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            player_api_url, data=body, headers=player_headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            logger.info("wss API resultCode=%s", data.get("resultCode"))
            if data.get("resultCode") == "000000":
                wss_address = data.get("data", {}).get("wssAddress", "")
                if wss_address and "ticket=" in wss_address:
                    ticket = wss_address.split("ticket=")[1].split("&")[0]
                    logger.info("got ticket %s", mask_ticket(ticket))
                    return ticket
    except Exception as e:
        logger.warning("wss address failed: %s", e)

    try:
        body = json.dumps(
            {
                "parameters": {
                    "urlType": 6,
                    "effectiveTime": 3600,
                    "deviceSn": resolved_device_id,
                },
                "path": "/cmiot/v2/api/device/live/url",
                "method": "GET",
                "token": device_token,
                "type": "0",
                "appid": player_app_id,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            player_api_url, data=body, headers=player_headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            if data.get("resultCode") == "000000":
                live_url = data.get("data", {}).get("url", "") or data.get("data", {}).get(
                    "liveUrl", ""
                )
                if live_url and "ticket=" in live_url:
                    ticket = live_url.split("ticket=")[1].split("&")[0]
                    logger.info("got ticket via live %s", mask_ticket(ticket))
                    return ticket
    except Exception as e:
        logger.warning("live url failed: %s", e)

    return None
