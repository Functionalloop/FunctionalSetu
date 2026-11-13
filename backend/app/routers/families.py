"""Kutumb Connect (plan 7.1): Kutumbs (app.families) made by hand, and their members.

Decided 12-13 Nov: a surveyor makes a Kutumb in one booth and types its name; there is no head
and nothing is grouped by house number. Members are in app.family_members (one row per voter,
family_id NULL = taken out), not in voter_surveys, so membership never touches the survey version.

A Kutumb is seen through its booth: outside the user's area (or in another workspace) it is 404.
A voter can only join a Kutumb of their own booth. GET /families (the walk list) is in field.py.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, status
from sqlalchemy import Connection, text

from ..deps import Db, Principal, ReadyUser
from ..errors import ApiError
from ..paging import decode_cursor, encode_cursor, invalid_cursor
from ..schemas_field import Family, FamilyChange, FamilyIn, FamilyPage, FamilyPatch, VoterFamily
from ..scope import Scope, UserScope, require_area
from ..stubs import Cursor, Limit, Surveyor
from .voters import voter_in_scope

router = APIRouter(tags=["field work"])

# Members the user may see (removed voters left out), in roll order.
_MEMBERS = """
    coalesce((SELECT array_agg(m.voter_id ORDER BY v.part_no, coalesce(v.booth_no, 0), v.serial_no, v.id)
                FROM app.family_members m
                JOIN app.voters v ON v.tenant_id = m.tenant_id AND v.id = m.voter_id
               WHERE m.family_id = f.id AND v.deleted_at IS NULL AND {voter_cond}), '{{}}') AS member_ids
"""


def _select(scope: Scope, where: str) -> tuple[str, dict]:
    """SELECT of families in the user's area (through the booth) with their member ids."""
    booth_cond, params = scope.filter("g.path")
    voter_cond, vparams = scope.filter("v.geo_path", "voter_paths")
    sql = f"""
        SELECT f.id, f.ward_id, f.booth_id, f.house_no, f.label, f.source, f.updated_at,
               lower(coalesce(f.label, '')) AS sort_name,
               {_MEMBERS.format(voter_cond=voter_cond)}
          FROM app.families f
          JOIN app.geo_units g ON g.tenant_id = f.tenant_id AND g.id = f.booth_id
         WHERE f.deleted_at IS NULL AND {booth_cond} AND {where}"""
    return sql, {**params, **vparams}


def family_in_scope(conn: Connection, scope: Scope, family_id: uuid.UUID) -> Family:
    """The Kutumb, or 404 when it is deleted, in another workspace (RLS) or outside the user's area."""
    sql, params = _select(scope, "f.id = :family_id")
    row = conn.execute(text(sql), {**params, "family_id": family_id}).mappings().first()
    if row is None:
        raise ApiError(404, "not_found", "Kutumb not found.")
    return Family(**row)


def _require_booth(conn: Connection, scope: Scope, booth_id: uuid.UUID) -> Any:
    """The booth's id and ward, or 404 when it is not a booth in the user's area."""
    require_area(conn, scope, booth_id)
    row = conn.execute(text("SELECT id, parent_id FROM app.geo_units WHERE id = :id AND level = 'booth'"),
                       {"id": booth_id}).first()
    if row is None:
        raise ApiError(404, "not_found", "Booth not found.")
    return row


@router.post("/families", response_model=Family, status_code=status.HTTP_201_CREATED,
             summary="Make a Kutumb by hand (free-text name) in a booth. A repeat id is stored once. Survey roles.")
def create_family(body: FamilyIn, conn: Db, user: Surveyor, scope: UserScope) -> Family:
    return write_new_family(conn, user, scope, body)


def write_new_family(conn: Connection, user: Principal, scope: Scope, body: FamilyIn) -> Family:
    """Insert the Kutumb, or return the stored one when this id was sent before. Used by POST (and push, 7.2)."""
    booth = _require_booth(conn, scope, body.booth_id)
    conn.execute(text("""
        INSERT INTO app.families (id, tenant_id, ward_id, booth_id, label, source, created_by)
        VALUES (:id, app.current_tenant_id(), :ward, :booth, :label, 'manual', :user)
        ON CONFLICT (id) DO NOTHING
    """), {"id": body.id, "ward": booth.parent_id, "booth": booth.id, "label": body.label, "user": user.user_id})
    try:
        return family_in_scope(conn, scope, body.id)
    except ApiError:
        # The id is taken by a record this user cannot see. Phone-made UUIDs do not collide in practice.
        raise ApiError(409, "id_in_use", "This id is already used by another record; make a new id.") from None


@router.patch("/families/{family_id}", response_model=Family, summary="Rename a Kutumb. Survey roles.")
def rename_family(family_id: uuid.UUID, body: FamilyPatch, conn: Db, user: Surveyor, scope: UserScope) -> Family:
    family_in_scope(conn, scope, family_id)
    conn.execute(text("UPDATE app.families SET label = :label WHERE id = :id AND label IS DISTINCT FROM :label"),
                 {"id": family_id, "label": body.label})
    return family_in_scope(conn, scope, family_id)


@router.get("/booths/{booth_id}/families", response_model=FamilyPage,
            summary="The Kutumbs made in a booth, by name. All roles.")
def booth_families(booth_id: uuid.UUID, conn: Db, user: ReadyUser, scope: UserScope, limit: Limit = 50,
                   cursor: Cursor = None) -> FamilyPage:
    _require_booth(conn, scope, booth_id)
    where, params = "f.booth_id = :booth_id", {"booth_id": booth_id}
    if cursor:
        name, fid = decode_cursor(cursor, 2)
        try:
            params.update(c_name=str(name), c_id=uuid.UUID(str(fid)))
        except (ValueError, TypeError):
            raise invalid_cursor() from None
        where += " AND (lower(coalesce(f.label, '')), f.id) > (:c_name, :c_id)"
    sql, sparams = _select(scope, where)
    rows = conn.execute(text(f"{sql} ORDER BY lower(coalesce(f.label, '')), f.id LIMIT :n"),
                        {**sparams, **params, "n": limit + 1}).mappings().all()
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = encode_cursor([rows[-1]["sort_name"], str(rows[-1]["id"])]) if more else None
    return FamilyPage(items=[Family(**r) for r in rows], next_cursor=next_cursor)


# --- one voter's Kutumb -------------------------------------------------------------------
def _voter_family(conn: Connection, scope: Scope, voter_id: uuid.UUID) -> VoterFamily:
    sql, params = _select(scope, """f.id = (SELECT m.family_id FROM app.family_members m
                                             WHERE m.voter_id = :voter_id)""")
    row = conn.execute(text(sql), {**params, "voter_id": voter_id}).mappings().first()
    return VoterFamily(family=Family(**row) if row else None)


@router.get("/voters/{voter_id}/family", response_model=VoterFamily,
            summary="The voter's Kutumb and its members (null when in none). All roles.")
def get_voter_family(voter_id: uuid.UUID, conn: Db, user: ReadyUser, scope: UserScope) -> VoterFamily:
    voter_in_scope(conn, scope, voter_id)
    return _voter_family(conn, scope, voter_id)


@router.put("/voters/{voter_id}/family", response_model=VoterFamily,
            summary="Put the voter in a Kutumb of their booth (moving them out of any other), or take them "
                    "out with leave_family. Survey roles.")
def set_voter_family(voter_id: uuid.UUID, body: FamilyChange, conn: Db, user: Surveyor,
                     scope: UserScope) -> VoterFamily:
    return write_voter_family(conn, user, scope, voter_id, body)


def write_voter_family(conn: Connection, user: Principal, scope: Scope, voter_id: uuid.UUID,
                       body: FamilyChange) -> VoterFamily:
    """Set or clear the voter's Kutumb. Used by PUT (and push, 7.2). Repeating it changes nothing."""
    voter = voter_in_scope(conn, scope, voter_id, cols="v.id, v.booth_id")
    if body.family_id is not None:
        family = family_in_scope(conn, scope, body.family_id)
        if family.booth_id != voter["booth_id"]:
            raise ApiError(422, "validation_error", "family_id: the Kutumb is in another part than the voter.")
    values = {"voter_id": voter_id, "family_id": body.family_id, "user": user.user_id, "device": user.device_id}
    # Only a real change is written, so a repeat leaves no audit row and no new sync_xid.
    conn.execute(text("""
        INSERT INTO app.family_members AS m (tenant_id, voter_id, family_id, updated_by, updated_device_id)
        SELECT app.current_tenant_id(), :voter_id, CAST(:family_id AS uuid), :user, CAST(:device AS uuid)
         WHERE CAST(:family_id AS uuid) IS NOT NULL
            OR EXISTS (SELECT 1 FROM app.family_members WHERE voter_id = :voter_id)
        ON CONFLICT (voter_id) DO UPDATE
           SET family_id = EXCLUDED.family_id, updated_by = EXCLUDED.updated_by,
               updated_device_id = EXCLUDED.updated_device_id
         WHERE m.family_id IS DISTINCT FROM EXCLUDED.family_id
    """), values)
    return _voter_family(conn, scope, voter_id)
