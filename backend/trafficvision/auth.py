"""Single-administrator, Argon2 password verification and signed session cookies."""

import secrets
import threading
import time
from collections import defaultdict, deque

import jwt
from fastapi import HTTPException, Request
from pwdlib import PasswordHash

COOKIE_NAME = "trafficvision_session"
PASSWORD_HASH = PasswordHash.recommended()


def authenticate(username: str, password: str, settings) -> bool:
    try:
        valid_password = PASSWORD_HASH.verify(password, settings.admin_password_hash)
    except (ValueError, TypeError):
        return False
    return (
        secrets.compare_digest(username.encode(), settings.admin_username.encode())
        and valid_password
    )


def session_token(settings) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": settings.admin_username,
            "iat": now,
            "exp": now + settings.session_seconds,
            "jti": secrets.token_hex(16),
            "iss": "trafficvision",
            "aud": "trafficvision",
        },
        settings.secret_key,
        algorithm="HS256",
    )


def require_user(request: Request) -> str:
    token = request.cookies.get(COOKIE_NAME)
    settings = request.app.state.settings
    try:
        claims = jwt.decode(
            token or "",
            settings.secret_key,
            algorithms=["HS256"],
            issuer="trafficvision",
            audience="trafficvision",
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
        if claims["sub"] != settings.admin_username:
            raise ValueError("Invalid account")
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(status_code=401, detail="Sign in to continue.") from None
    return claims["sub"]


class LoginLimiter:
    """Bounded local limiter for this single-instance MVP; proxy-level limits recommended."""

    def __init__(self):
        self.attempts = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, address: str):
        now = time.monotonic()
        with self.lock:
            for key in list(self.attempts):
                while self.attempts[key] and self.attempts[key][0] <= now - 60:
                    self.attempts[key].popleft()
                if not self.attempts[key]:
                    del self.attempts[key]
            attempts = self.attempts[address]
            if len(attempts) >= 10 or len(self.attempts) > 10000:
                raise HTTPException(
                    429,
                    "Too many sign-in attempts. Try again in one minute.",
                    headers={"Retry-After": "60"},
                )
            attempts.append(now)
