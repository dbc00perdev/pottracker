"""Password hashing + JWT encode/decode.

Hashing: passlib `CryptContext` with bcrypt (Decision-I). JWT: python-jose,
HS256, symmetric `JWT_SECRET`. Standalone auth — no tracker integration
(Decision-7); tooling owns the payload schema in v1.

Payload carries a `ver` claim (R5 mitigation) so a future tracker consumer, or
a v2 payload change, can detect and reject incompatible tokens rather than
silently mis-parsing. Bump `JWT_PAYLOAD_VERSION` on any breaking claim change.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from apps.tooling.api.config import Settings

JWT_ALGORITHM = "HS256"
JWT_PAYLOAD_VERSION = 1

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd.verify(plain, hashed)
    except ValueError:
        # Malformed/unknown hash in the DB — treat as auth failure, not a 500.
        return False


def _encode(settings: Settings, claims: dict[str, Any], ttl_seconds: int, typ: str) -> str:
    now = datetime.now(UTC)
    payload = {
        **claims,
        "ver": JWT_PAYLOAD_VERSION,
        "typ": typ,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def create_access_token(settings: Settings, *, user_id: str, username: str, role: str) -> str:
    return _encode(
        settings,
        {"sub": user_id, "username": username, "role": role},
        settings.jwt_access_ttl,
        "access",
    )


def create_refresh_token(settings: Settings, *, user_id: str) -> str:
    return _encode(settings, {"sub": user_id}, settings.jwt_refresh_ttl, "refresh")


def decode_token(settings: Settings, token: str) -> dict[str, Any]:
    """Decode + verify signature/expiry. Raises `JWTError` on any problem."""
    payload: dict[str, Any] = jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
    if payload.get("ver") != JWT_PAYLOAD_VERSION:
        raise JWTError(f"unsupported token version {payload.get('ver')!r}")
    return payload
