"""One-voter corrections (plan 10.4): POST /voters, PATCH /voters/{id}/roll, .../remove, .../restore,
GET /voters/{id}/roll-edits.

Official roll data is changed by the super admin only (client, 12 Nov); an admin reads the roll edits.
Every change needs a reason (and may carry a reference: list number or date) and writes one
`voter_roll_edits` row with the old and new values. The voters trigger adds the audit row (History:
"roll_edit") and a new sync_xid, so phones pull the change.

  add      a new voter in a part (booth); ward, constituency and part number come from the booth.
  correct  only the fields sent change (merged with the record, then checked as a whole); fields that
           already have that value are dropped, and nothing left = no edit row (a retry is harmless).
           A removed voter must be restored first (404).
  remove   hides the voter (deleted_at): gone from search, lists and phones; survey work is kept and
           nothing is erased. roll_status is not touched. Removing again changes nothing.
  restore  brings a removed voter back with everything it had. Restoring a live voter changes nothing.
Clashes with a live voter (EPIC; part and serial among active voters): 409 epic_in_use / serial_in_use
with `error.voter_id`.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import Connection, text

from ..deps import Db, Principal
from ..errors import ApiError
from ..paging import decode_cursor, encode_cursor, invalid_cursor
from ..schemas import UserSummary, VoterDetail
from ..schemas_roll import RemoveRestore, RollEdit, RollEditPage, RollFields, RollPatch, VoterAdd
from ..scope import Scope, UserScope, require_area
from ..stubs import Admin, Cursor, Limit, SuperAdmin
from .voters import voter_detail, voter_in_scope

router = APIRouter(tags=["roll and data quality"])

ROLL_KEYS = tuple(RollFields.model_fields)
TEXT_KEYS = ("epic_no", "first_name_mr", "middle_name_mr", "last_name_mr", "first_name_en", "middle_name_en",
             "last_name_en", "relative_name_mr", "relative_name_en", "house_no", "address_mr", "address_en")
NAME_KEYS = ("first_name_mr", "last_name_mr", "first_name_en", "last_name_en")
PLACE_KEYS = ("local_body_id", "ward_id", "part_no", "booth_no")   # follow booth_id
_CASTS = {"gender": "app.gender", "relation_type": "app.relation_type", "list_type": "app.list_type"}


def _param(key: str) -> str:
    return f"CAST(:{key} AS {_CASTS[key]})" if key in _CASTS else f":{key}"


def _clean(values: dict[str, Any]) -> dict[str, Any]:
    """Enums as their values, text trimmed, blank text = null."""
    out = {}
    for k, v in values.items():
        v = getattr(v, "value", v)
        if k in TEXT_KEYS and isinstance(v, str):
            v = v.strip() or None
        out[k] = v
    return out


def _reference(ref: str | None) -> str | None:
    return (ref or "").strip() or None


def _need_name(values: dict[str, Any]) -> None:
    if not any(values.get(k) for k in NAME_KEYS):
        raise ApiError(422, "validation_error", "Give the voter a first or last name.")


def _place(conn: Connection, scope: Scope, booth_id: uuid.UUID, section_id: uuid.UUID | None) -> dict[str, Any]:
    """Constituency, Village Panchayat, part number and booth number of a part (booth) in the caller's area."""
    require_area(conn, scope, booth_id)
    p = conn.execute(text("""
        SELECT b.level::text AS level, b.number AS booth_no, w.id AS ward_id, w.number AS part_no,
               lb.id AS local_body_id
          FROM app.geo_units b
          LEFT JOIN app.geo_units w ON w.tenant_id = b.tenant_id AND w.level = 'ward' AND w.path @> b.path
          LEFT JOIN app.geo_units lb ON lb.tenant_id = b.tenant_id AND lb.level = 'local_body' AND lb.path @> b.path
         WHERE b.id = :id"""), {"id": booth_id}).mappings().one()
    if p["level"] != "booth" or p["ward_id"] is None or p["local_body_id"] is None:
        raise ApiError(422, "validation_error", "booth_id: choose a part (booth).")
    if p["part_no"] is None:
        raise ApiError(422, "validation_error", "This part's Village Panchayat has no part number.")
    if section_id is not None and not conn.execute(text("""
            SELECT EXISTS (SELECT 1 FROM app.geo_units WHERE id = :s AND level = 'section' AND parent_id = :b
                                                      AND is_active)"""), {"s": section_id, "b": booth_id}).scalar():
        raise ApiError(422, "validation_error", "section_id: not a section of this part.")
    return {k: p[k] for k in PLACE_KEYS}


def _check_clashes(conn: Connection, voter_id: uuid.UUID, values: dict[str, Any], active: bool) -> None:
    """409 when a live voter already has the EPIC, or (for an active voter) the part and serial."""
    if values.get("epic_no"):
        other = conn.execute(text("""SELECT id FROM app.voters WHERE epic_no = :e AND deleted_at IS NULL
                                       AND id <> :id"""), {"e": values["epic_no"], "id": voter_id}).scalar()
        if other:
            raise ApiError(409, "epic_in_use", "Another voter has this EPIC number.", extra={"voter_id": str(other)})
    if active:
        other = conn.execute(text("""
            SELECT id FROM app.voters WHERE booth_id = :b AND serial_no = :s AND roll_status = 'active'
                                        AND deleted_at IS NULL AND id <> :id"""),
                             {"b": values["booth_id"], "s": values["serial_no"], "id": voter_id}).scalar()
        if other:
            raise ApiError(409, "serial_in_use", "Another voter has this serial number in this part.",
                           extra={"voter_id": str(other)})


def _record(conn: Connection, user: Principal, voter_id: uuid.UUID, action: str, reason: str,
            reference: str | None, old: dict[str, Any] | None, new: dict[str, Any] | None) -> None:
    conn.execute(text("""
        INSERT INTO app.voter_roll_edits (tenant_id, voter_id, action, reason, reference, old_values, new_values,
                                          edited_by, device_id)
        VALUES (app.current_tenant_id(), :v, CAST(:action AS app.roll_edit_action), :reason, :ref,
                CAST(:old AS jsonb), CAST(:new AS jsonb), :by, :device)"""),
                 {"v": voter_id, "action": action, "reason": reason, "ref": _reference(reference),
                  "old": None if old is None else json.dumps(old, default=str),
                  "new": None if new is None else json.dumps(new, default=str),
                  "by": user.user_id, "device": user.device_id})


@router.post("/voters", response_model=VoterDetail, status_code=status.HTTP_201_CREATED,
             summary="Add one voter to the roll by hand, with reason and reference. Super admin.")
def add_voter(body: VoterAdd, conn: Db, user: SuperAdmin, scope: UserScope) -> VoterDetail:
    values = _clean(body.model_dump(include=set(ROLL_KEYS)))
    _need_name(values)
    values.update(_place(conn, scope, values["booth_id"], values["section_id"]))
    vid = uuid.uuid4()
    _check_clashes(conn, vid, values, active=True)
    cols = [*ROLL_KEYS, *PLACE_KEYS]
    conn.execute(text(f"""INSERT INTO app.voters (id, tenant_id, {', '.join(cols)})
                          VALUES (:id, app.current_tenant_id(), {', '.join(_param(c) for c in cols)})"""),
                 {**values, "id": vid})
    _record(conn, user, vid, "add", body.reason.value, body.reference, None, values)
    return voter_detail(conn, scope, vid)


@router.patch("/voters/{voter_id}/roll", response_model=VoterDetail,
              summary="Correct one roll record, with reason and reference. Super admin.")
def correct_voter(voter_id: uuid.UUID, body: RollPatch, conn: Db, user: SuperAdmin, scope: UserScope) -> VoterDetail:
    unknown = sorted(set(body.fields) - set(ROLL_KEYS))
    if unknown:
        raise ApiError(422, "validation_error", f"fields: not a roll field: {', '.join(unknown)}.")
    if not body.fields:
        raise ApiError(422, "validation_error", "fields: give at least one field to correct.")
    row = voter_in_scope(conn, scope, voter_id, ", ".join(f"v.{k}" for k in ROLL_KEYS) + ", v.roll_status::text AS st")
    current = {k: row[k] for k in ROLL_KEYS}
    try:
        merged = RollFields(**{**current, **body.fields})
    except ValidationError as e:
        raise RequestValidationError([{**err, "loc": ("body", "fields", *err["loc"])} for err in e.errors()]) from None
    new = _clean(merged.model_dump())
    old = _clean(current)
    keys = [k for k in ROLL_KEYS if new[k] != old[k]]
    if not keys:
        return voter_detail(conn, scope, voter_id)
    _need_name(new)
    sets = {k: new[k] for k in keys}
    if "booth_id" in sets or "section_id" in sets:
        sets.update(_place(conn, scope, new["booth_id"], new["section_id"]))
    _check_clashes(conn, voter_id, new, active=row["st"] == "active")
    conn.execute(text(f"UPDATE app.voters SET {', '.join(f'{k} = {_param(k)}' for k in sets)} WHERE id = :id"),
                 {**sets, "id": voter_id})
    _record(conn, user, voter_id, "correct", body.reason.value, body.reference,
            {k: old[k] for k in keys}, {k: new[k] for k in keys})
    return voter_detail(conn, scope, voter_id)


@router.post("/voters/{voter_id}/remove", response_model=VoterDetail,
             summary="Hide one voter (survey work is kept), with reason. Super admin.")
def remove_voter(voter_id: uuid.UUID, body: RemoveRestore, conn: Db, user: SuperAdmin, scope: UserScope) -> VoterDetail:
    voter_in_scope(conn, scope, voter_id, include_removed=True)
    at = conn.execute(text("""UPDATE app.voters SET deleted_at = now() WHERE id = :id AND deleted_at IS NULL
                              RETURNING deleted_at"""), {"id": voter_id}).scalar()
    if at is not None:
        _record(conn, user, voter_id, "remove", body.reason.value, body.reference,
                {"deleted_at": None}, {"deleted_at": at.isoformat()})
    return voter_detail(conn, scope, voter_id, include_removed=True)


@router.post("/voters/{voter_id}/restore", response_model=VoterDetail, summary="Bring back a hidden voter. Super admin.")
def restore_voter(voter_id: uuid.UUID, body: RemoveRestore, conn: Db, user: SuperAdmin, scope: UserScope) -> VoterDetail:
    row = voter_in_scope(conn, scope, voter_id, "v.deleted_at, v.epic_no, v.booth_id, v.serial_no, "
                                                "v.roll_status::text AS st", include_removed=True)
    if row["deleted_at"] is not None:
        _check_clashes(conn, voter_id, dict(row), active=row["st"] == "active")
        conn.execute(text("UPDATE app.voters SET deleted_at = NULL WHERE id = :id"), {"id": voter_id})
        _record(conn, user, voter_id, "restore", body.reason.value, body.reference,
                {"deleted_at": row["deleted_at"].isoformat()}, {"deleted_at": None})
    return voter_detail(conn, scope, voter_id)


@router.get("/voters/{voter_id}/roll-edits", response_model=RollEditPage,
            summary="Roll corrections made to this voter, newest first. Admin.")
def voter_roll_edits(voter_id: uuid.UUID, conn: Db, user: Admin, scope: UserScope, limit: Limit = 50,
                     cursor: Cursor = None) -> RollEditPage:
    voter_in_scope(conn, scope, voter_id, include_removed=True)
    where, params = ["e.voter_id = :v"], {"v": voter_id, "n": limit + 1}
    if cursor:
        (after,) = decode_cursor(cursor, 1)
        if not isinstance(after, int):
            raise invalid_cursor()
        where.append("e.id < :after")
        params["after"] = after
    rows = conn.execute(text(f"""
        SELECT e.id, e.voter_id, e.action::text AS action, e.reason, e.reference, e.old_values, e.new_values,
               e.edited_at, u.id AS u_id, u.username, u.full_name_en, u.full_name_mr, u.role::text AS u_role
          FROM app.voter_roll_edits e
          JOIN app.users u ON u.tenant_id = e.tenant_id AND u.id = e.edited_by
         WHERE {' AND '.join(where)}
         ORDER BY e.id DESC LIMIT :n"""), params).mappings().all()
    items = [RollEdit(id=r["id"], voter_id=r["voter_id"], action=r["action"], reason=r["reason"],
                      reference=r["reference"], old_values=r["old_values"], new_values=r["new_values"],
                      edited_by=UserSummary(id=r["u_id"], username=r["username"], full_name_en=r["full_name_en"],
                                            full_name_mr=r["full_name_mr"], role=r["u_role"]),
                      edited_at=r["edited_at"]) for r in rows[:limit]]
    return RollEditPage(items=items, next_cursor=encode_cursor([items[-1].id]) if len(rows) > limit else None)
