"""Users (9.1) and their assigned areas (9.2). Admin and super admin.

Scope: RLS keeps every other workspace out. A super admin manages every user of the workspace; an
admin sees the users of their own constituency (users.local_body_id) and changes only supervisors,
surveyors and booth agents there (an admin or super admin: 403). Anything outside scope is 404.

Nobody changes their own role, switches off their own account or resets their own password here
(403 own_account; Change password is /auth/change-password), so a workspace always keeps the super
admin who is using it. A role change to or from super admin is refused (422): a super admin has no
constituency, so that is a new user.

Limit: 200 active users per workspace (tenants.max_users), enforced by the users_limit trigger; a
switched-off user does not count, so switching one back on can hit the limit too (409 user_limit).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from ..deps import Db, Principal
from ..errors import ApiError
from ..paging import decode_cursor, encode_cursor, invalid_cursor
from ..schemas import Area, Role
from ..schemas_admin import (Assignments, AssignmentsOut, TemporaryPassword, User, UserIn, UserPage,
                             UserPatch)
from ..security import hash_password, temporary_password
from ..stubs import Admin, Cursor, Limit

router = APIRouter(tags=["admin"])

# Roles an admin may give; everything above is a super admin's.
ADMIN_GIVES = frozenset({Role.supervisor, Role.surveyor, Role.booth_agent})

_SELECT = """
    SELECT u.id, u.username, u.full_name_en, u.full_name_mr, u.role, u.mobile, u.local_body_id, u.is_active,
           u.must_change_password, u.preferred_language, u.last_login_at, u.locked_until, u.created_at,
           (SELECT count(*) FROM app.devices d WHERE d.tenant_id = u.tenant_id AND d.user_id = u.id) AS device_count,
           EXISTS (SELECT 1 FROM app.devices d WHERE d.tenant_id = u.tenant_id AND d.user_id = u.id
                     AND d.status = 'pending') AS pending_device
      FROM app.users u
"""
# Users the caller may see: super admin all, admin their constituency. Removed users never.
_SEE = "u.deleted_at IS NULL AND (:is_super OR u.local_body_id = :lb)"


def _scope(admin: Principal) -> dict:
    return {"is_super": admin.role == Role.super_admin, "lb": admin.local_body_id}


def load_user(conn: Connection, admin: Principal, user_id: uuid.UUID) -> User:
    """The user if the caller may see them, else 404. Also used by assignments (9.2)."""
    row = conn.execute(text(f"{_SELECT} WHERE u.id = :id AND {_SEE}"),
                       {"id": user_id, **_scope(admin)}).mappings().first()
    if row is None:
        raise ApiError(404, "not_found", "User not found.")
    return User(**row)


def check_may_change(admin: Principal, target: User) -> None:
    """An admin changes only the roles below admin (403 otherwise)."""
    if admin.role != Role.super_admin and target.role not in ADMIN_GIVES:
        raise ApiError(403, "forbidden_role", "Only a super admin can change an admin or a super admin.")


def _own_account(message: str) -> ApiError:
    return ApiError(403, "own_account", message)


def _write_error(exc: DBAPIError) -> ApiError | None:
    """Unique user ID / mobile and the user limit, from the database's own checks."""
    orig = exc.orig
    state = getattr(orig, "sqlstate", None)
    diag = getattr(orig, "diag", None)
    constraint = getattr(diag, "constraint_name", None) or ""
    if state == "23505" and constraint == "users_username_uq":
        return ApiError(409, "username_taken", "This user ID is already used in the workspace.")
    if state == "23505" and constraint == "users_mobile_uq":
        return ApiError(409, "mobile_taken", "Another user already has this mobile number.")
    if state == "P0001" and "tenant limit reached" in str(orig):
        return ApiError(409, "user_limit", "The workspace already has its limit of active users "
                                           "(switch one off first).")
    return None


def _execute(conn: Connection, sql: str, params: dict):
    try:
        return conn.execute(text(sql), params)
    except DBAPIError as exc:
        err = _write_error(exc)
        if err is None:
            raise
        raise err from None


def _end_sessions(conn: Connection, user_id: uuid.UUID, reason: str) -> None:
    conn.execute(text("""UPDATE app.auth_sessions SET revoked_at = now(), revoke_reason = :r
                          WHERE user_id = :u AND revoked_at IS NULL"""), {"u": user_id, "r": reason})


def _constituency(conn: Connection, admin: Principal, body: UserIn) -> uuid.UUID | None:
    if body.role == Role.super_admin:
        if body.local_body_id is not None:
            raise ApiError(422, "validation_error", "A super admin has no constituency: leave local_body_id out.")
        return None
    lb = body.local_body_id
    if admin.role != Role.super_admin:
        lb = lb or admin.local_body_id  # an admin's users are in the admin's constituency
        if lb != admin.local_body_id:
            raise ApiError(404, "not_found", "Constituency not found.")
        return lb
    if lb is None:
        raise ApiError(422, "validation_error", "local_body_id is required except for a super admin.")
    found = conn.execute(text("""SELECT 1 FROM app.geo_units
                                  WHERE id = :id AND level = 'local_body' AND is_active"""), {"id": lb}).first()
    if found is None:
        raise ApiError(404, "not_found", "Constituency not found.")
    return lb


# --- routes -----------------------------------------------------------------------------------
@router.get("/users", response_model=UserPage,
            summary="Users in the admin's constituency (super admin: all). Admin.")
def list_users(conn: Db, user: Admin, role: Role | None = None, is_active: bool | None = None,
               q: Annotated[str | None, Query(max_length=100, description="name, user ID or mobile")] = None,
               limit: Limit = 50, cursor: Cursor = None) -> UserPage:
    where = [_SEE]
    params: dict = {**_scope(user), "limit": limit + 1}
    if role is not None:
        where.append("u.role = CAST(:role AS app.user_role)")
        params["role"] = role.value
    if is_active is not None:
        where.append("u.is_active = :active")
        params["active"] = is_active
    if q and q.strip():
        esc = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("""(u.username::text ILIKE :q OR u.full_name_en ILIKE :q OR coalesce(u.full_name_mr, '') ILIKE :q
                         OR coalesce(u.mobile::text, '') LIKE :q)""")
        params["q"] = f"%{esc}%"
    if cursor:
        name, last_id = decode_cursor(cursor, 2)
        try:
            params.update(c_name=str(name), c_id=uuid.UUID(str(last_id)))
        except (TypeError, ValueError):
            raise invalid_cursor() from None
        where.append("(lower(u.full_name_en), u.id) > (:c_name, :c_id)")

    rows = conn.execute(text(f"""{_SELECT} WHERE {' AND '.join(where)}
                                 ORDER BY lower(u.full_name_en), u.id LIMIT :limit"""), params).mappings().all()
    more = len(rows) > limit
    rows = rows[:limit]
    nxt = encode_cursor([rows[-1]["full_name_en"].lower(), str(rows[-1]["id"])]) if more else None
    return UserPage(items=[User(**r) for r in rows], next_cursor=nxt)


@router.post("/users", response_model=TemporaryPassword, status_code=status.HTTP_201_CREATED,
             summary="Create a user with a temporary password (limit 200 per workspace). Admin.")
def create_user(body: UserIn, conn: Db, user: Admin) -> TemporaryPassword:
    if user.role != Role.super_admin and body.role not in ADMIN_GIVES:
        raise ApiError(403, "forbidden_role", "Only a super admin can create an admin or a super admin.")
    lb = _constituency(conn, user, body)
    password = temporary_password()
    new_id = _execute(conn, """
        INSERT INTO app.users (tenant_id, username, full_name_en, full_name_mr, mobile, role, local_body_id,
                               password_hash, must_change_password, preferred_language, created_by)
        VALUES (:tenant, :username, :name_en, :name_mr, :mobile, CAST(:role AS app.user_role), :lb,
                :hash, true, CAST(:lang AS app.lang), :by)
        RETURNING id
    """, {"tenant": user.tenant_id, "username": body.username, "name_en": body.full_name_en.strip(),
          "name_mr": (body.full_name_mr or "").strip() or None, "mobile": body.mobile, "role": body.role.value,
          "lb": lb, "hash": hash_password(password), "lang": body.preferred_language.value,
          "by": user.user_id}).scalar_one()
    return TemporaryPassword(user=load_user(conn, user, new_id), temporary_password=password)


@router.get("/users/{user_id}", response_model=User, summary="One user. Admin.")
def get_user(user_id: uuid.UUID, conn: Db, user: Admin) -> User:
    return load_user(conn, user, user_id)


@router.patch("/users/{user_id}", response_model=User, summary="Edit, disable or enable a user. Admin.")
def update_user(user_id: uuid.UUID, body: UserPatch, conn: Db, user: Admin) -> User:
    target = load_user(conn, user, user_id)
    sent = body.model_fields_set
    is_self = target.id == user.user_id
    if is_self and (("role" in sent and body.role != target.role)
                    or ("is_active" in sent and body.is_active is False)):
        raise _own_account("You cannot change your own role or switch off your own account.")
    if not is_self:
        check_may_change(user, target)

    sets: list[str] = []
    params: dict = {"id": user_id}
    if "full_name_en" in sent:
        if body.full_name_en is None or not body.full_name_en.strip():
            raise ApiError(422, "validation_error", "full_name_en cannot be empty.")
        sets.append("full_name_en = :name_en")
        params["name_en"] = body.full_name_en.strip()
    if "full_name_mr" in sent:
        sets.append("full_name_mr = :name_mr")
        params["name_mr"] = (body.full_name_mr or "").strip() or None
    if "mobile" in sent:
        sets.append("mobile = :mobile")
        params["mobile"] = body.mobile
    if "preferred_language" in sent and body.preferred_language is not None:
        sets.append("preferred_language = CAST(:lang AS app.lang)")
        params["lang"] = body.preferred_language.value
    if "role" in sent and body.role is not None and body.role != target.role:
        if Role.super_admin in (body.role, target.role):
            raise ApiError(422, "validation_error", "A super admin has no constituency: make a new user instead.")
        if user.role != Role.super_admin and body.role not in ADMIN_GIVES:
            raise ApiError(403, "forbidden_role", "Only a super admin can make a user an admin.")
        sets.append("role = CAST(:role AS app.user_role)")
        params["role"] = body.role.value
    if "is_active" in sent and body.is_active is not None and body.is_active != target.is_active:
        sets.append("is_active = :active")
        params["active"] = body.is_active

    if sets:
        _execute(conn, f"UPDATE app.users SET {', '.join(sets)} WHERE id = :id", params)
        if params.get("active") is False:
            _end_sessions(conn, user_id, "disabled")
    return load_user(conn, user, user_id)


@router.post("/users/{user_id}/reset-password", response_model=TemporaryPassword,
             summary="New temporary password; the user's sessions end. Admin.")
def reset_password(user_id: uuid.UUID, conn: Db, user: Admin) -> TemporaryPassword:
    target = load_user(conn, user, user_id)
    if target.id == user.user_id:
        raise _own_account("Use Change password for your own account.")
    check_may_change(user, target)
    password = temporary_password()
    conn.execute(text("""UPDATE app.users SET password_hash = :hash, must_change_password = true,
                                failed_login_count = 0, locked_until = NULL
                          WHERE id = :id"""), {"hash": hash_password(password), "id": user_id})
    _end_sessions(conn, user_id, "password_reset")
    return TemporaryPassword(user=load_user(conn, user, user_id), temporary_password=password)


# --- assignments (9.2) ------------------------------------------------------------------------
# A supervisor, surveyor or booth agent works in the wards and booths assigned to them, inside their own
# constituency (app/scope.py); an admin works in the whole constituency and a super admin everywhere, so
# they have none. The phone learns the change from the next pull: `area_ids` is always the full current
# list, so it drops an area that is gone and downloads one that is new (context/sync.md).
ASSIGNABLE_LEVELS = ("ward", "booth")
MAX_AREAS = 500


def _assigned_areas(conn: Connection, user_id: uuid.UUID) -> AssignmentsOut:
    rows = conn.execute(text("""
        SELECT g.id, g.parent_id, g.level, g.code, g.number, g.name_mr, g.name_en
          FROM app.user_area_assignments a
          JOIN app.geo_units g ON g.tenant_id = a.tenant_id AND g.id = a.geo_unit_id
         WHERE a.user_id = :u
         ORDER BY g.path
    """), {"u": user_id}).mappings().all()
    return AssignmentsOut(areas=[Area(**r) for r in rows])


@router.get("/users/{user_id}/assignments", response_model=AssignmentsOut,
            summary="Wards and booths the user works in. Admin.")
def get_assignments(user_id: uuid.UUID, conn: Db, user: Admin) -> AssignmentsOut:
    load_user(conn, user, user_id)
    return _assigned_areas(conn, user_id)


@router.put("/users/{user_id}/assignments", response_model=AssignmentsOut,
            summary="Replace the user's wards and booths; their next pull drops what was removed. Admin.")
def set_assignments(user_id: uuid.UUID, body: Assignments, conn: Db, user: Admin) -> AssignmentsOut:
    target = load_user(conn, user, user_id)
    check_may_change(user, target)
    if target.role in (Role.admin, Role.super_admin):
        raise ApiError(422, "validation_error", "An admin works in the whole constituency and a super admin "
                                                "everywhere: they have no assigned areas.")
    wanted = list(dict.fromkeys(body.area_ids))
    if len(wanted) > MAX_AREAS:
        raise ApiError(422, "validation_error", f"At most {MAX_AREAS} areas.")
    # Each area must lie in the user's own constituency: anything else reads as unknown (404), so an
    # admin cannot learn which ids exist in another constituency.
    found = conn.execute(text("""
        SELECT g.id, g.level::text AS level
          FROM app.geo_units g
          JOIN app.geo_units lb ON lb.tenant_id = g.tenant_id AND lb.id = :lb
         WHERE g.id = ANY(:ids) AND g.path <@ lb.path
    """), {"ids": wanted, "lb": target.local_body_id}).mappings().all()
    levels = {r["id"]: r["level"] for r in found}
    if missing := [i for i in wanted if i not in levels]:
        raise ApiError(404, "not_found", f"Area not found: {missing[0]}.")
    if wrong := [i for i in wanted if levels[i] not in ASSIGNABLE_LEVELS]:
        raise ApiError(422, "validation_error", f"Only wards and booths can be assigned: {wrong[0]}.")

    conn.execute(text("""DELETE FROM app.user_area_assignments
                          WHERE user_id = :u AND NOT (geo_unit_id = ANY(:ids))"""), {"u": user_id, "ids": wanted})
    if wanted:
        conn.execute(text("""
            INSERT INTO app.user_area_assignments (tenant_id, user_id, geo_unit_id, assigned_by)
            SELECT :tenant, :u, unnest(CAST(:ids AS uuid[])), :by
            ON CONFLICT DO NOTHING
        """), {"tenant": user.tenant_id, "u": user_id, "ids": wanted, "by": user.user_id})
    return _assigned_areas(conn, user_id)
