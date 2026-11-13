"""Eligible but Not Registered (plan 7.5): people who can vote but are not on the roll.

"New voter" and "not registered" are one thing (client, 12 Nov); the paths keep the name new-voters.
A record belongs to a part (booth_id) or, with no part, to its Village Panchayat (ward_id), and is
seen through that area like a voter: outside the user's area (or workspace) it is 404.

Campaign data, not roll data: survey roles write it (not booth agents), and a new roll never deletes
it (the Matching Engine sets matched_voter_id later). Edits carry `version`; a stale one is 409 with
the server copy, like the survey. The same functions serve the push types new_voter / new_voter_update.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, status
from sqlalchemy import Connection, text

from ..deps import Db, Principal
from ..errors import ApiError
from ..paging import decode_cursor, encode_cursor, invalid_cursor
from ..schemas import Form6Status, NewVoter, NewVoterFields
from ..schemas_field import NewVoterIn, NewVoterPage, NewVoterPatch
from ..scope import Scope, UserScope, require_area
from ..stubs import Cursor, Limit, Surveyor
from .families import family_in_scope

router = APIRouter(tags=["field work"])

EDIT_COLS = list(NewVoterFields.model_fields)  # replaced on every edit
_CASTS = {"gender": "app.gender", "form6_status": "app.form6_status"}


def _mark(col: str) -> str:
    return f"CAST(:{col} AS {_CASTS[col]})" if col in _CASTS else f":{col}"
COLS = ", ".join(f"n.{c}" for c in NewVoter.model_fields)
# The record's area: its part, else its Village Panchayat.
AREA_JOIN = "JOIN app.geo_units g ON g.tenant_id = n.tenant_id AND g.id = coalesce(n.booth_id, n.ward_id)"


def _select(scope: Scope, where: str) -> tuple[str, dict]:
    cond, params = scope.filter("g.path")
    return f"SELECT {COLS} FROM app.new_voters n {AREA_JOIN} WHERE n.deleted_at IS NULL AND {cond} AND {where}", params


def new_voter_in_scope(conn: Connection, scope: Scope, new_voter_id: uuid.UUID) -> NewVoter:
    """The record, or 404 when it is deleted, in another workspace (RLS) or outside the user's area."""
    sql, params = _select(scope, "n.id = :id")
    row = conn.execute(text(sql), {**params, "id": new_voter_id}).mappings().first()
    if row is None:
        raise ApiError(404, "not_found", "Record not found.")
    return NewVoter(**row)


def read_new_voter(conn: Connection, new_voter_id: uuid.UUID) -> NewVoter | None:
    """The record as stored (no area check: for push results after the area was checked)."""
    row = conn.execute(text(f"SELECT {COLS} FROM app.new_voters n WHERE n.id = :id AND n.deleted_at IS NULL"),
                       {"id": new_voter_id}).mappings().first()
    return NewVoter(**row) if row else None


def check_place(conn: Connection, scope: Scope, body: NewVoterFields) -> None:
    """The part (or, with no part, the Village Panchayat) must be in the user's area (else 404); the part
    must be in that Village Panchayat and the Kutumb in that part (else 422)."""
    level = "booth" if body.booth_id else "ward"
    area = body.booth_id or body.ward_id
    require_area(conn, scope, area)
    row = conn.execute(text("SELECT level, parent_id FROM app.geo_units WHERE id = :id"), {"id": area}).first()
    if row is None or row.level != level:
        raise ApiError(404, "not_found", "Area not found.")
    if body.booth_id and row.parent_id != body.ward_id:
        raise ApiError(422, "validation_error", "ward_id: the part is in another Village Panchayat.")
    if body.family_id is not None:
        family = family_in_scope(conn, scope, body.family_id)
        if family.booth_id != body.booth_id:
            raise ApiError(422, "validation_error", "family_id: the Kutumb is in another part.")


def _values(body: NewVoterFields) -> dict[str, Any]:
    v = body.model_dump(include=set(EDIT_COLS))
    v["gender"] = body.gender.value if body.gender else None
    v["form6_status"] = body.form6_status.value
    return v


@router.get("/new-voters", response_model=NewVoterPage,
            summary="Eligible but Not Registered: people added by hand (not on the roll), newest first, with "
                    "Form 6 status. Survey roles.")
def list_new_voters(conn: Db, user: Surveyor, scope: UserScope, ward_id: uuid.UUID | None = None,
                    form6_status: Form6Status | None = None, limit: Limit = 50,
                    cursor: Cursor = None) -> NewVoterPage:
    where, params = "TRUE", {}
    if ward_id is not None:
        require_area(conn, scope, ward_id)
        where += " AND n.ward_id = :ward_id"
        params["ward_id"] = ward_id
    if form6_status is not None:
        where += " AND n.form6_status = CAST(:f6 AS app.form6_status)"
        params["f6"] = form6_status.value
    if cursor:
        at, nid = decode_cursor(cursor, 2)
        try:
            params.update(c_at=str(at), c_id=uuid.UUID(str(nid)))
        except (ValueError, TypeError):
            raise invalid_cursor() from None
        where += " AND (n.created_at, n.id) < (CAST(:c_at AS timestamptz), :c_id)"
    sql, sparams = _select(scope, where)
    rows = conn.execute(text(f"{sql} ORDER BY n.created_at DESC, n.id DESC LIMIT :n"),
                        {**sparams, **params, "n": limit + 1}).mappings().all()
    more = len(rows) > limit
    items = [NewVoter(**r) for r in rows[:limit]]
    next_cursor = encode_cursor([items[-1].created_at.isoformat(), str(items[-1].id)]) if more else None
    return NewVoterPage(items=items, next_cursor=next_cursor)


@router.post("/new-voters", response_model=NewVoter, status_code=status.HTTP_201_CREATED,
             summary="Add a person who is not on the roll (Eligible but Not Registered). A repeat id is stored "
                     "once. Survey roles.")
def add_new_voter(body: NewVoterIn, conn: Db, user: Surveyor, scope: UserScope) -> NewVoter:
    return write_new_voter(conn, user, scope, body)


def write_new_voter(conn: Connection, user: Principal, scope: Scope, body: NewVoterIn) -> NewVoter:
    """Insert, or return the stored record when this id was sent before (its first copy is kept)."""
    check_place(conn, scope, body)
    cols = ", ".join(EDIT_COLS)
    marks = ", ".join(_mark(c) for c in EDIT_COLS)
    conn.execute(text(f"""
        INSERT INTO app.new_voters (id, tenant_id, {cols}, created_by, device_id, client_mutation_id)
        VALUES (:id, app.current_tenant_id(), {marks}, :user, CAST(:device AS uuid), :id)
        ON CONFLICT DO NOTHING
    """), {**_values(body), "id": body.id, "user": user.user_id, "device": user.device_id})
    try:
        return new_voter_in_scope(conn, scope, body.id)
    except ApiError:
        # The id is taken by a record this user cannot see. Phone-made UUIDs do not collide in practice.
        raise ApiError(409, "id_in_use", "This id is already used by another record; make a new id.") from None


@router.patch("/new-voters/{new_voter_id}", response_model=NewVoter,
              summary="Edit an Eligible but Not Registered record or its Form 6 status (the whole record plus "
                      "`version`). Stale version: 409 with the server copy. Survey roles.")
def update_new_voter(new_voter_id: uuid.UUID, body: NewVoterPatch, conn: Db, user: Surveyor,
                     scope: UserScope) -> NewVoter:
    saved = write_new_voter_update(conn, scope, new_voter_id, body)
    if saved is None:
        current = new_voter_in_scope(conn, scope, new_voter_id)
        raise ApiError(409, "version_conflict",
                       "This record was changed by someone else. Check the server copy and save again.",
                       extra={"current": current.model_dump(mode="json")})
    return saved


def write_new_voter_update(conn: Connection, scope: Scope, new_voter_id: uuid.UUID,
                           body: NewVoterPatch) -> NewVoter | None:
    """Replace every field when `version` is the current one; None when it is stale. 404 outside the area
    (the record's area now, and the area it moves to)."""
    new_voter_in_scope(conn, scope, new_voter_id)
    check_place(conn, scope, body)
    sets = ", ".join(f"{c} = {_mark(c)}" for c in EDIT_COLS)
    row = conn.execute(text(f"""
        UPDATE app.new_voters SET {sets} WHERE id = :id AND version = :version AND deleted_at IS NULL
        RETURNING id
    """), {**_values(body), "id": new_voter_id, "version": body.version}).first()
    return read_new_voter(conn, new_voter_id) if row else None
