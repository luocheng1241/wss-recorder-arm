"""Simple password session auth."""

from __future__ import annotations

import hmac
import time
from typing import TYPE_CHECKING

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

if TYPE_CHECKING:
    from app.config import Settings


class AuthService:
    def __init__(self, settings: "Settings"):
        self.settings = settings
        self.serializer = URLSafeTimedSerializer(
            settings.auth.session_secret, salt="wss-console-session"
        )

    def verify_password(self, password: str) -> bool:
        expected = self.settings.auth.password.encode("utf-8")
        got = (password or "").encode("utf-8")
        return hmac.compare_digest(expected, got)

    def create_session_token(self) -> str:
        return self.serializer.dumps({"auth": True, "ts": time.time()})

    def validate_session_token(self, token: str | None) -> bool:
        if not token:
            return False
        try:
            data = self.serializer.loads(token, max_age=self.settings.auth.session_max_age_sec)
            return bool(data.get("auth"))
        except (BadSignature, SignatureExpired):
            return False
