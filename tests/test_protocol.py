from app.core.protocol import is_ticket_expired_payload, login_message, play_live_start
import json


def test_login_message():
    msg = json.loads(login_message("14eaa12a154e"))
    assert msg["cmd"] == "login"
    assert msg["deviceId"] == "14eaa12a154e"


def test_play():
    msg = json.loads(play_live_start("abc"))
    assert msg["cmd"] == "playLiveStart"


def test_expired():
    assert is_ticket_expired_payload({"resultCode": "100002", "resultMsg": "x"})
    assert is_ticket_expired_payload({"resultCode": "0", "resultMsg": "ticket失效"})
    assert not is_ticket_expired_payload({"resultCode": "000000", "resultMsg": "ok"})
