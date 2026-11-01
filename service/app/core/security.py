import logging
import json
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash

from app.core.config import Settings, get_settings

logger = logging.getLogger("shaha.security")
password_hash = PasswordHash.recommended()
# A dummy hash makes unknown-user and missing-configuration checks perform the
# same expensive password operation as a configured account.
_dummy_password_hash = password_hash.hash(secrets.token_urlsafe(32))
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)
_algorithm = "HS256"
_token_minutes = 30


def audit_event(event: str, outcome: str, **details: str | int | bool) -> None:
    """Emit allowlisted structured events; callers must never pass PII/secrets."""
    record: dict[str, str | int | bool] = {"event": event, "outcome": outcome}
    record.update({key: value for key, value in details.items() if key in {"imported", "duplicates", "rejected", "total", "action"}})
    logger.info(json.dumps(record, separators=(",", ":")))


class SlidingWindowLimiter:
    """Thread-safe per-process limiter; replace with shared storage in multi-worker deployments."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_seconds: int) -> int | None:
        now = time.monotonic()
        with self._lock:
            timestamps = self._events[key]
            while timestamps and timestamps[0] <= now - window_seconds:
                timestamps.popleft()
            if len(timestamps) >= limit:
                return max(1, int(window_seconds - (now - timestamps[0])))
            timestamps.append(now)
        return None

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


limiter = SlidingWindowLimiter()


def _configured(settings: Settings) -> bool:
    return bool(settings.admin_username and settings.admin_password_hash and len(settings.jwt_secret) >= 32)


def login(username: str, password: str, settings: Settings) -> str:
    configured = _configured(settings)
    expected_username = settings.admin_username if configured else "__unconfigured__"
    expected_hash = settings.admin_password_hash if configured else _dummy_password_hash
    try:
        password_valid = password_hash.verify(password, expected_hash)
    except Exception:
        password_valid = False
    valid = secrets.compare_digest(username.encode(), expected_username.encode()) and password_valid and configured
    if not valid:
        return ""
    expiry = datetime.now(timezone.utc) + timedelta(minutes=_token_minutes)
    return jwt.encode({"sub": expected_username, "role": "admin", "exp": expiry}, settings.jwt_secret, algorithm=_algorithm)


def decode_admin_token(token: str, settings: Settings) -> dict | None:
    if not _configured(settings):
        return None
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[_algorithm])
    except jwt.PyJWTError:
        return None
    return claims


def require_configured_auth(settings: Settings = Depends(get_settings)) -> None:
    if not _configured(settings):
        raise HTTPException(status_code=503, detail="Authentication is not configured.")


def require_admin(
    token: str | None = Depends(oauth2_scheme),
    settings: Settings = Depends(get_settings),
) -> str:
    if not token:
        audit_event("authentication", "missing_credentials")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.", headers={"WWW-Authenticate": "Bearer"})
    claims = decode_admin_token(token, settings)
    if claims is None:
        audit_event("authentication", "invalid_token")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired credentials.", headers={"WWW-Authenticate": "Bearer"})
    if claims.get("role") != "admin" or claims.get("sub") != settings.admin_username:
        audit_event("authorization", "denied")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
    return claims["sub"]


def limit_request(request: Request, bucket: str, limit: int) -> None:
    client_ip = request.client.host if request.client else "unknown"
    retry_after = limiter.check(f"{bucket}:{client_ip}", limit, get_settings().security_rate_window_seconds)
    if retry_after is not None:
        audit_event(f"{bucket}_rate_limited", "denied")
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.", headers={"Retry-After": str(retry_after)})
