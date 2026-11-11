"""Request dependencies: token -> transaction with RLS context -> checked user.

Three levels of "logged in", strictest last:
  CurrentUser  valid session (any device state, password may need changing)
  ActiveUser   + the phone is not blocked / wiped
  ReadyUser    + password changed + phone approved. Every data endpoint uses this
               (or require_role, which builds on it).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Connection, text

from .db import transaction
from .errors import ApiError
from .schemas import Role
from .security import AccessClaims, TokenExpired, TokenInvalid, read_access_token

ROLE_RANK = {Role.booth_agent: 1, Role.surveyor: 1, Role.supervisor: 2, Role.admin: 3, Role.super_admin: 4}
LAST_SEEN_EVERY = timedelta(seconds=60)

_bearer = HTTPBearer(auto_error=False, description="Access token from /auth/login or /auth/refresh")


def _unauthorized(code: str, message: str) -> ApiError:
    return ApiError(401, code, message, headers={"WWW-Authenticate": "Bearer"})


def get_claims(cred: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> AccessClaims:
    if cred is None:
        raise _unauthorized("not_authenticated", "Log in first.")
    try:
        return read_access_token(cred.credentials)
    except TokenExpired:
        raise _unauthorized("token_expired", "Access token expired; call /auth/refresh.") from None
    except TokenInvalid:
        raise _unauthorized("invalid_token", "Access token is not valid.") from None


Claims = Annotated[AccessClaims, Depends(get_claims)]


def get_db(claims: Claims) -> Iterator[Connection]:
    """One transaction per request, RLS context set from the token. Commits before the response is sent."""
    with transaction(claims.tenant_id, claims.user_id, claims.device_id) as conn:
        yield conn


Db = Annotated[Connection, Depends(get_db, scope="function")]


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    session_id: uuid.UUID
    device_id: uuid.UUID | None
    role: Role
    username: str
    local_body_id: uuid.UUID | None
    must_change_password: bool
    device_status: str | None

    def at_least(self, role: Role) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[role]


_PRINCIPAL_SQL = text("""
    SELECT u.id, u.username, u.role, u.local_body_id, u.must_change_password, u.is_active,
           u.deleted_at, s.revoked_at, s.last_seen_at, s.device_id, d.status AS device_status,
           t.status AS tenant_status
      FROM app.auth_sessions s
      JOIN app.users   u ON u.tenant_id = s.tenant_id AND u.id = s.user_id
      JOIN app.tenants t ON t.id = s.tenant_id
      LEFT JOIN app.devices d ON d.tenant_id = s.tenant_id AND d.id = s.device_id
     WHERE s.id = :sid AND s.user_id = :uid
""")


def get_principal(conn: Db, claims: Claims) -> Principal:
    # RLS limits this to the token's workspace, so a token can never reach another one.
    row = conn.execute(_PRINCIPAL_SQL, {"sid": claims.session_id, "uid": claims.user_id}).mappings().first()
    if row is None or row["revoked_at"] is not None:
        raise _unauthorized("session_ended", "This login has ended. Log in again.")
    if not row["is_active"] or row["deleted_at"] is not None:
        raise ApiError(403, "account_disabled", "This account is disabled.")
    if row["tenant_status"] != "active":
        raise ApiError(403, "workspace_suspended", "This workspace is not active.")
    if row["device_id"] != claims.device_id:
        raise _unauthorized("invalid_token", "Access token is not valid.")

    # "Online now" counter; written at most once a minute per session.
    if datetime.now(timezone.utc) - row["last_seen_at"] > LAST_SEEN_EVERY:
        conn.execute(text("UPDATE app.auth_sessions SET last_seen_at = now() WHERE id = :sid"),
                     {"sid": claims.session_id})

    return Principal(
        user_id=row["id"], tenant_id=claims.tenant_id, session_id=claims.session_id,
        device_id=row["device_id"], role=Role(row["role"]), username=row["username"],
        local_body_id=row["local_body_id"], must_change_password=row["must_change_password"],
        device_status=row["device_status"],
    )


CurrentUser = Annotated[Principal, Depends(get_principal)]


def get_active_principal(p: CurrentUser) -> Principal:
    if p.device_status in ("blocked", "wiped"):
        raise ApiError(403, "device_blocked", "This phone has been blocked. Contact your admin.")
    return p


ActiveUser = Annotated[Principal, Depends(get_active_principal)]


def get_ready_principal(p: ActiveUser) -> Principal:
    if p.must_change_password:
        raise ApiError(403, "password_change_required", "Set a new password first.")
    if p.device_status == "pending":
        raise ApiError(403, "device_pending", "This phone is waiting for admin approval.")
    return p


ReadyUser = Annotated[Principal, Depends(get_ready_principal)]


def require_role(minimum: Role):
    """Dependency: ready user with at least this role. Area checks are per endpoint."""
    def check(p: ReadyUser) -> Principal:
        if not p.at_least(minimum):
            raise ApiError(403, "forbidden_role", f"Needs role {minimum.value} or higher.")
        return p
    return check


# Surveyor and booth agent have the same rank but different work (SRS roles table),
# so work-specific endpoints check a list of roles instead of a minimum rank.
SURVEY_ROLES = frozenset({Role.super_admin, Role.admin, Role.supervisor, Role.surveyor})
POLLING_ROLES = frozenset({Role.super_admin, Role.admin, Role.supervisor, Role.booth_agent})


def check_roles(p: Principal, roles: frozenset[Role] | set[Role]) -> None:
    """403 forbidden_role unless the user's role is in the list. Also for per-item checks (sync push)."""
    if p.role not in roles:
        raise ApiError(403, "forbidden_role", "Your role cannot do this.")


def require_roles(*roles: Role | frozenset[Role] | set[Role]):
    """Dependency: ready user whose role is one of the listed roles (no rank order).

        require_roles(SURVEY_ROLES)            require_roles(Role.admin, Role.super_admin)
    """
    allowed: set[Role] = set()
    for r in roles:
        allowed |= {r} if isinstance(r, Role) else set(r)
    if not allowed:
        raise ValueError("require_roles needs at least one role")
    frozen = frozenset(allowed)

    def check(p: ReadyUser) -> Principal:
        check_roles(p, frozen)
        return p
    return check
