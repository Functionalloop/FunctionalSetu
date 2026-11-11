"""Passwords (Argon2id), access tokens (JWT, HS256) and refresh tokens (opaque)."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from .config import get_settings

_hasher = PasswordHasher()  # argon2-cffi defaults: Argon2id, 64 MiB, t=3
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-password")


# --- passwords ---------------------------------------------------------------
def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def burn_password_check(password: str) -> None:
    """Same work as a real check, so 'no such user' takes as long as 'wrong password'."""
    verify_password(_DUMMY_HASH, password)


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return False


# --- access tokens -------------------------------------------------------------
ALGORITHM = "HS256"


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    session_id: uuid.UUID
    device_id: uuid.UUID | None


def make_access_token(c: AccessClaims) -> tuple[str, int]:
    s = get_settings()
    now = datetime.now(timezone.utc)
    ttl = s.access_token_minutes * 60
    payload = {
        "typ": "access",
        "sub": str(c.user_id),
        "tid": str(c.tenant_id),
        "sid": str(c.session_id),
        "did": str(c.device_id) if c.device_id else None,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
    }
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm=ALGORITHM), ttl


class TokenExpired(Exception):
    pass


class TokenInvalid(Exception):
    pass


def read_access_token(token: str) -> AccessClaims:
    try:
        p = jwt.decode(token, get_settings().jwt_secret.get_secret_value(), algorithms=[ALGORITHM],
                       options={"require": ["exp", "iat", "sub", "tid", "sid", "typ"]}, leeway=10)
    except jwt.ExpiredSignatureError as e:
        raise TokenExpired from e
    except jwt.PyJWTError as e:
        raise TokenInvalid from e
    if p.get("typ") != "access":
        raise TokenInvalid
    try:
        return AccessClaims(uuid.UUID(p["sub"]), uuid.UUID(p["tid"]), uuid.UUID(p["sid"]),
                            uuid.UUID(p["did"]) if p.get("did") else None)
    except (ValueError, TypeError) as e:
        raise TokenInvalid from e


# --- refresh tokens --------------------------------------------------------------
# Format "<tenant uuid>.<random>". The tenant part lets /auth/refresh set the RLS
# context before looking the session up; only the SHA-256 of the whole token is stored.
def new_refresh_token(tenant_id: uuid.UUID) -> tuple[str, str]:
    token = f"{tenant_id}.{secrets.token_urlsafe(32)}"
    return token, sha256_hex(token)


def refresh_token_tenant(token: str) -> uuid.UUID | None:
    tenant, sep, rest = token.partition(".")
    if not sep or len(rest) < 32:
        return None
    try:
        return uuid.UUID(tenant)
    except ValueError:
        return None


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
