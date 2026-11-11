"""POST /auth/login, /auth/refresh, /auth/logout, /auth/change-password.

Login and refresh manage their own transaction (not the per-request one),
because some failures must still be saved: a wrong password bumps the failure
counter, and refreshing from a blocked phone revokes its session.
"""

from __future__ import annotations

import ipaddress
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import Connection, text

from ..config import get_settings
from ..db import set_context, transaction
from ..deps import ROLE_RANK, ActiveUser, CurrentUser, Db
from ..errors import ApiError
from ..schemas import (AuthTokens, ChangePasswordRequest, DeviceInfo, DeviceSummary, LoginRequest,
                       RefreshRequest, Role, UserSummary, WorkspaceSummary)
from ..security import (AccessClaims, burn_password_check, hash_password, make_access_token,
                        needs_rehash, new_refresh_token, refresh_token_tenant, sha256_hex, verify_password)

router = APIRouter(prefix="/auth", tags=["auth"])

BLOCKED = ("blocked", "wiped")
WEB_LOGIN_MIN_ROLE = Role.supervisor  # surveyors and booth agents must use an approved phone


def _invalid_credentials() -> ApiError:
    return ApiError(401, "invalid_credentials", "Wrong workspace code, user ID or password.")


def _device_blocked() -> ApiError:
    return ApiError(403, "device_blocked", "This phone has been blocked. Contact your admin.")


def _client_ip(request: Request) -> str | None:
    host = request.client.host if request.client else None
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:
        return None


def _upsert_device(conn: Connection, tenant: uuid.UUID, user: uuid.UUID, d: DeviceInfo) -> tuple[uuid.UUID, str]:
    """A phone seen for the first time is saved as 'pending' until an admin approves it."""
    row = conn.execute(text("""
        INSERT INTO app.devices (tenant_id, user_id, device_uid_hash, model, os_version, app_version_code,
                                 last_seen_at)
        VALUES (:t, :u, :h, :model, :os, :ver, now())
        ON CONFLICT (tenant_id, user_id, device_uid_hash) DO UPDATE
           SET model = EXCLUDED.model, os_version = EXCLUDED.os_version,
               app_version_code = EXCLUDED.app_version_code, last_seen_at = now()
        RETURNING id, status
    """), {"t": tenant, "u": user, "h": sha256_hex(d.device_uid), "model": d.model,
           "os": d.os_version, "ver": d.app_version_code}).one()
    return row.id, row.status


def _issue_tokens(conn: Connection, *, tenant: uuid.UUID, user: uuid.UUID, session: uuid.UUID,
                  device: uuid.UUID | None, refresh_token: str) -> AuthTokens:
    u = conn.execute(text("""
        SELECT id, username, full_name_en, full_name_mr, role, must_change_password
          FROM app.users WHERE id = :u
    """), {"u": user}).mappings().one()
    t = conn.execute(text("SELECT id, code, name_en, name_mr FROM app.tenants WHERE id = :t"),
                     {"t": tenant}).mappings().one()
    dev = None
    if device is not None:
        d = conn.execute(text("SELECT id, status FROM app.devices WHERE id = :d"), {"d": device}).mappings().one()
        dev = DeviceSummary(id=d["id"], status=d["status"])
    access, ttl = make_access_token(AccessClaims(user, tenant, session, device))
    return AuthTokens(
        access_token=access, refresh_token=refresh_token, expires_in=ttl,
        must_change_password=u["must_change_password"],
        user=UserSummary(**{k: u[k] for k in ("id", "username", "full_name_en", "full_name_mr", "role")}),
        workspace=WorkspaceSummary(**t), device=dev,
    )


@router.post("/login", response_model=AuthTokens, summary="Log in with workspace code, user ID and password")
def login(body: LoginRequest, request: Request) -> AuthTokens:
    s = get_settings()
    error: ApiError | None = None
    result: AuthTokens | None = None

    with transaction() as conn:
        # SECURITY DEFINER lookup: the only query that runs before a workspace is known.
        acc = conn.execute(text("SELECT * FROM app.login_lookup(:code, :username)"),
                           {"code": body.workspace_code.strip().lower(), "username": body.username.strip()}
                           ).mappings().first()
        if acc is None:
            burn_password_check(body.password)
            error = _invalid_credentials()
        else:
            tenant, user = acc["tenant_id"], acc["user_id"]
            set_context(conn, tenant, user, None)
            if acc["locked_until"] and acc["locked_until"] > datetime.now(timezone.utc):
                error = ApiError(403, "account_locked", "Too many wrong passwords. Try again later.")
            elif not verify_password(acc["password_hash"], body.password):
                locked = conn.execute(text("""
                    UPDATE app.users
                       SET failed_login_count = CASE WHEN failed_login_count + 1 >= :max THEN 0
                                                     ELSE failed_login_count + 1 END,
                           locked_until = CASE WHEN failed_login_count + 1 >= :max
                                               THEN now() + make_interval(mins => :mins) ELSE locked_until END
                     WHERE id = :u
                 RETURNING locked_until > now() AS locked
                """), {"u": user, "max": s.login_max_failures, "mins": s.login_lock_minutes}).scalar()
                error = (ApiError(403, "account_locked", "Too many wrong passwords. Try again later.")
                         if locked else _invalid_credentials())
            elif not acc["is_active"]:
                error = ApiError(403, "account_disabled", "This account is disabled.")
            elif acc["tenant_status"] != "active":
                error = ApiError(403, "workspace_suspended", "This workspace is not active.")
            elif body.device is None and ROLE_RANK[Role(acc["role"])] < ROLE_RANK[WEB_LOGIN_MIN_ROLE]:
                error = ApiError(403, "device_required", "Log in from the JANSETU app on your phone.")
            else:
                conn.execute(text("""
                    UPDATE app.users SET failed_login_count = 0, locked_until = NULL, last_login_at = now()
                     WHERE id = :u
                """), {"u": user})
                if needs_rehash(acc["password_hash"]):
                    conn.execute(text("UPDATE app.users SET password_hash = :h WHERE id = :u"),
                                 {"h": hash_password(body.password), "u": user})

                device_id, device_status = (None, None)
                if body.device is not None:
                    device_id, device_status = _upsert_device(conn, tenant, user, body.device)
                    set_context(conn, tenant, user, device_id)

                if device_status in BLOCKED:
                    error = _device_blocked()
                else:
                    refresh, refresh_hash = new_refresh_token(tenant)
                    session = conn.execute(text("""
                        INSERT INTO app.auth_sessions (tenant_id, user_id, device_id, refresh_token_hash,
                                                       expires_at, ip, user_agent)
                        VALUES (:t, :u, :d, :h, now() + make_interval(days => :days), :ip, :ua)
                        RETURNING id
                    """), {"t": tenant, "u": user, "d": device_id, "h": refresh_hash,
                           "days": s.refresh_token_days, "ip": _client_ip(request),
                           "ua": (request.headers.get("user-agent") or "")[:300] or None}).scalar_one()
                    result = _issue_tokens(conn, tenant=tenant, user=user, session=session,
                                           device=device_id, refresh_token=refresh)

    if error is not None:  # raised after COMMIT so the failure counter is kept
        raise error
    assert result is not None
    return result


@router.post("/refresh", response_model=AuthTokens, summary="New access token from a refresh token")
def refresh(body: RefreshRequest) -> AuthTokens:
    s = get_settings()
    bad = ApiError(401, "invalid_refresh_token", "Login has expired. Log in again.")
    tenant = refresh_token_tenant(body.refresh_token)
    if tenant is None:
        raise bad

    error: ApiError | None = None
    result: AuthTokens | None = None
    with transaction(tenant) as conn:
        row = conn.execute(text("""
            SELECT s.id, s.user_id, s.device_id, s.revoked_at, s.expires_at > now() AS live,
                   u.is_active, u.deleted_at, d.status AS device_status, t.status AS tenant_status
              FROM app.auth_sessions s
              JOIN app.users   u ON u.tenant_id = s.tenant_id AND u.id = s.user_id
              JOIN app.tenants t ON t.id = s.tenant_id
              LEFT JOIN app.devices d ON d.tenant_id = s.tenant_id AND d.id = s.device_id
             WHERE s.refresh_token_hash = :h
               FOR UPDATE OF s
        """), {"h": sha256_hex(body.refresh_token)}).mappings().first()

        def revoke(reason: str) -> None:
            conn.execute(text("UPDATE app.auth_sessions SET revoked_at = now(), revoke_reason = :r WHERE id = :id"),
                         {"r": reason, "id": row["id"]})

        if row is None or row["revoked_at"] is not None or not row["live"]:
            error = bad
        else:
            set_context(conn, tenant, row["user_id"], row["device_id"])
            if not row["is_active"] or row["deleted_at"] is not None:
                revoke("account_disabled")
                error = ApiError(403, "account_disabled", "This account is disabled.")
            elif row["tenant_status"] != "active":
                error = ApiError(403, "workspace_suspended", "This workspace is not active.")
            elif row["device_status"] in BLOCKED:
                revoke("device_blocked")
                error = _device_blocked()
            else:
                # Rotate: the old refresh token stops working; the session lives on (sliding expiry).
                token, token_hash = new_refresh_token(tenant)
                conn.execute(text("""
                    UPDATE app.auth_sessions
                       SET refresh_token_hash = :h, last_seen_at = now(),
                           expires_at = now() + make_interval(days => :days)
                     WHERE id = :id
                """), {"h": token_hash, "days": s.refresh_token_days, "id": row["id"]})
                result = _issue_tokens(conn, tenant=tenant, user=row["user_id"], session=row["id"],
                                       device=row["device_id"], refresh_token=token)

    if error is not None:
        raise error
    assert result is not None
    return result


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
             summary="End this login (the refresh token stops working)")
def logout(conn: Db, user: CurrentUser) -> None:
    conn.execute(text("""
        UPDATE app.auth_sessions SET revoked_at = now(), revoke_reason = 'logout'
         WHERE id = :sid AND revoked_at IS NULL
    """), {"sid": user.session_id})


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
             summary="Change password (also the first-login change). Ends the user's other logins.")
def change_password(body: ChangePasswordRequest, conn: Db, user: ActiveUser) -> None:
    current: Any = conn.execute(text("SELECT password_hash FROM app.users WHERE id = :u"),
                                {"u": user.user_id}).scalar_one()
    if not verify_password(current, body.current_password):
        raise ApiError(400, "wrong_current_password", "Current password is wrong.")
    if body.new_password == body.current_password:
        raise ApiError(422, "weak_password", "New password must be different from the current one.")
    if body.new_password.lower() == user.username.lower():
        raise ApiError(422, "weak_password", "Password must not be the same as the user ID.")

    conn.execute(text("""
        UPDATE app.users SET password_hash = :h, must_change_password = false,
                             failed_login_count = 0, locked_until = NULL
         WHERE id = :u
    """), {"h": hash_password(body.new_password), "u": user.user_id})
    conn.execute(text("""
        UPDATE app.auth_sessions SET revoked_at = now(), revoke_reason = 'password_changed'
         WHERE user_id = :u AND id <> :sid AND revoked_at IS NULL
    """), {"u": user.user_id, "sid": user.session_id})
