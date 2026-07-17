"""WSS JSON protocol helpers for CMIOT media relay."""

from __future__ import annotations

import json
import os
import time


def client_mac(device_id: str) -> str:
    return f"web_vnsp_{device_id}_{int(time.time() * 1000)}_{os.urandom(2).hex().upper()}"


def login_message(device_id: str, vnsp_version: str = "1.0.30") -> str:
    return json.dumps(
        {
            "cmd": "login",
            "vnspType": "media",
            "clientMac": client_mac(device_id),
            "playerType": 2,
            "deviceId": device_id,
            "vnspVersion": vnsp_version,
        }
    )


def ping_message(sequence_num: int) -> str:
    return json.dumps({"cmd": "ping", "sequenceNum": sequence_num})


def play_live_start(device_id: str) -> str:
    return json.dumps({"cmd": "playLiveStart", "deviceId": device_id})


def play_live_stop(device_id: str) -> str:
    return json.dumps({"cmd": "playLiveStop", "deviceId": device_id})


def is_ticket_expired_payload(data: dict) -> bool:
    code = str(data.get("resultCode", ""))
    msg = str(data.get("resultMsg", ""))
    return code == "100002" or "失效" in msg
