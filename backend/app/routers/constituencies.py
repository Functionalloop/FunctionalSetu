"""Constituencies (9.3): the top areas of a workspace (geo_units level local_body). Super admin only.

Limit: 5 active constituencies per workspace (tenants.max_local_bodies). The geo_units_path trigger checks
it on insert; switching one back on is checked here under the same advisory lock. Switching one off hides
it and everything below it from every role (app/scope.py), its users included; nothing is deleted.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from ..deps import Db
from ..errors import ApiError
from ..schemas_admin import Constituency, ConstituencyIn, ConstituencyPatch
from ..stubs import SuperAdmin

router = APIRouter(tags=["admin"])

_SELECT = """
    SELECT g.id, g.parent_id, g.level, g.code, g.number, g.name_mr, g.name_en, g.ac_no, g.is_active,
           (SELECT count(*) FROM app.voters v
             WHERE v.tenant_id = g.tenant_id AND v.local_body_id = g.id AND v.deleted_at IS NULL) AS voter_count,
           (SELECT count(*) FROM app.users u
             WHERE u.tenant_id = g.tenant_id AND u.local_body_id = g.id AND u.deleted_at IS NULL) AS user_count
      FROM app.geo_units g
     WHERE g.level = 'local_body'
"""


def _limit_error() -> ApiError:
    return ApiError(409, "constituency_limit", "The workspace already has its limit of active constituencies "
                                               "(switch one off first).")


def _load(conn: Connection, constituency_id: uuid.UUID) -> Constituency:
    row = conn.execute(text(f"{_SELECT} AND g.id = :id"), {"id": constituency_id}).mappings().first()
    if row is None:
        raise ApiError(404, "not_found", "Constituency not found.")
    return Constituency(**row)


def _lock_limit(conn: Connection, tenant: uuid.UUID) -> None:
    """Same lock as the geo_units_path trigger, so two calls cannot both pass the limit."""
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('geo_limit:' || :t, 0))"), {"t": str(tenant)})


@router.get("/constituencies", response_model=list[Constituency], summary="Constituencies in the workspace. Super admin.")
def list_constituencies(conn: Db, user: SuperAdmin) -> list[Constituency]:
    rows = conn.execute(text(f"{_SELECT} ORDER BY g.sort_order, g.ac_no NULLS LAST, g.code")).mappings().all()
    return [Constituency(**r) for r in rows]


@router.post("/constituencies", response_model=Constituency, status_code=status.HTTP_201_CREATED,
             summary="Add a constituency (limit 5 per workspace). Super admin.")
def create_constituency(body: ConstituencyIn, conn: Db, user: SuperAdmin) -> Constituency:
    code = body.code.strip()
    if not code:
        raise ApiError(422, "validation_error", "code cannot be empty.")
    try:
        new_id = conn.execute(text("""
            INSERT INTO app.geo_units (tenant_id, parent_id, level, code, name_mr, name_en, ac_no)
            VALUES (:tenant, NULL, 'local_body', :code, :name_mr, :name_en, :ac_no)
            RETURNING id
        """), {"tenant": user.tenant_id, "code": code, "name_mr": body.name_mr.strip(),
               "name_en": (body.name_en or "").strip() or None, "ac_no": body.ac_no}).scalar_one()
    except DBAPIError as exc:
        state = getattr(exc.orig, "sqlstate", None)
        if state == "23505":
            raise ApiError(409, "code_taken", "Another constituency already has this code.") from None
        if state == "P0001" and "tenant limit reached" in str(exc.orig):
            raise _limit_error() from None
        raise
    return _load(conn, new_id)


@router.patch("/constituencies/{constituency_id}", response_model=Constituency,
              summary="Rename or switch off a constituency. Super admin.")
def update_constituency(constituency_id: uuid.UUID, body: ConstituencyPatch, conn: Db,
                        user: SuperAdmin) -> Constituency:
    current = _load(conn, constituency_id)
    sent = body.model_fields_set
    sets: list[str] = []
    params: dict = {"id": constituency_id}
    if "name_mr" in sent:
        if body.name_mr is None or not body.name_mr.strip():
            raise ApiError(422, "validation_error", "name_mr cannot be empty.")
        sets.append("name_mr = :name_mr")
        params["name_mr"] = body.name_mr.strip()
    if "name_en" in sent:
        sets.append("name_en = :name_en")
        params["name_en"] = (body.name_en or "").strip() or None
    if "ac_no" in sent:
        sets.append("ac_no = :ac_no")
        params["ac_no"] = body.ac_no
    if "is_active" in sent and body.is_active is not None and body.is_active != current.is_active:
        if body.is_active:
            _lock_limit(conn, user.tenant_id)
            active = conn.execute(text("SELECT count(*) FROM app.geo_units WHERE level = 'local_body' AND is_active")
                                  ).scalar_one()
            n_max = conn.execute(text("SELECT max_local_bodies FROM app.tenants")).scalar_one()
            if active >= n_max:
                raise _limit_error()
        sets.append("is_active = :active")
        params["active"] = body.is_active
    if sets:
        conn.execute(text(f"UPDATE app.geo_units SET {', '.join(sets)} WHERE id = :id"), params)
    return _load(conn, constituency_id)
