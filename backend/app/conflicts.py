"""Conflict review (7.10): GET /sync/conflicts and POST /sync/conflicts/{id}/resolve.

A stale push leaves one sync_conflicts row per differing field (sync_push.py). Who sees a row:
the record must be in the user's area (voter for a survey, the record's part for a new voter,
the Kutumb's part); a surveyor sees only the rows of their own pushes, supervisor and above
every row in their area (change log, 12 Nov). Anyone else gets 404.

Resolving: kept_server writes nothing. kept_client puts the phone's value of that one field on
the record as it is now and saves it through the normal save path (checks, references, audit,
a new version). A record that would break a rule (e.g. an influencer type without "influencer")
is 422; resolve the other field first. A row already decided is 409 conflict_resolved.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Connection, text

from .deps import Principal
from .errors import ApiError
from .paging import decode_cursor, encode_cursor, invalid_cursor
from .routers.new_voters import new_voter_in_scope, write_new_voter_update
from .routers.voters import check_survey_references, read_survey, voter_in_scope, write_survey
from .schemas import NewVoterFields, Role, SurveyFields, SurveyIn, UserSummary
from .schemas_field import Conflict, ConflictPage, ConflictStatus, NewVoterPatch
from .scope import Scope

# Each row with the path of the record it is about (null if the record is gone).
_ROWS = """
    WITH c AS (
        SELECT c.*, coalesce(v.geo_path, ng.path, fg.path) AS area_path,
               u.username, u.full_name_en, u.full_name_mr, u.role AS u_role
          FROM app.sync_conflicts c
          JOIN app.users u ON u.id = c.client_user_id
          LEFT JOIN app.voters v ON c.entity_type = 'voter_survey' AND v.id = c.entity_id
          LEFT JOIN app.new_voters n ON c.entity_type = 'new_voter' AND n.id = c.entity_id
          LEFT JOIN app.geo_units ng ON ng.id = coalesce(n.booth_id, n.ward_id)
          LEFT JOIN app.families f ON c.entity_type = 'family' AND f.id = c.entity_id
          LEFT JOIN app.geo_units fg ON fg.id = f.booth_id
    )
    SELECT * FROM c
"""


def _visible(user: Principal, scope: Scope) -> tuple[str, dict[str, Any]]:
    cond, params = scope.filter("c.area_path")
    cond = f"c.area_path IS NOT NULL AND {cond}"
    if not user.at_least(Role.supervisor):  # a surveyor: own pushes only
        cond += " AND c.client_user_id = :me"
        params["me"] = user.user_id
    return cond, params


def _conflict(r: Any) -> Conflict:
    return Conflict(
        id=r["id"], entity_type=r["entity_type"], entity_id=r["entity_id"], field_name=r["field_name"],
        client_value=r["client_value"], server_value=r["server_value"],
        client_user=UserSummary(id=r["client_user_id"], username=r["username"], full_name_en=r["full_name_en"],
                                full_name_mr=r["full_name_mr"], role=r["u_role"]),
        client_changed_at=r["client_changed_at"], server_user_id=r["server_user_id"],
        server_changed_at=r["server_changed_at"], status=r["status"], created_at=r["created_at"])


def list_conflicts(conn: Connection, user: Principal, scope: Scope, status: ConflictStatus,
                   entity_id: uuid.UUID | None, limit: int, cursor: str | None) -> ConflictPage:
    cond, params = _visible(user, scope)
    cond += " AND c.status = CAST(:status AS app.conflict_status)"
    params["status"] = status.value
    if entity_id is not None:
        cond += " AND c.entity_id = :entity_id"
        params["entity_id"] = entity_id
    if cursor:
        at, i = decode_cursor(cursor, 2)
        try:
            params.update(c_at=datetime.fromisoformat(str(at)), c_id=uuid.UUID(str(i)))
        except ValueError:
            raise invalid_cursor() from None
        cond += " AND (c.created_at, c.id) < (:c_at, :c_id)"
    rows = conn.execute(text(f"{_ROWS} WHERE {cond} ORDER BY c.created_at DESC, c.id DESC LIMIT :n"),
                        {**params, "n": limit + 1}).mappings().all()
    last = rows[limit - 1] if len(rows) > limit else None
    return ConflictPage(items=[_conflict(r) for r in rows[:limit]],
                        next_cursor=encode_cursor([last["created_at"].isoformat(), str(last["id"])]) if last else None)


def _one(conn: Connection, user: Principal, scope: Scope, conflict_id: uuid.UUID) -> Any:
    cond, params = _visible(user, scope)
    row = conn.execute(text(f"{_ROWS} WHERE c.id = :id AND {cond}"), {**params, "id": conflict_id}).mappings().first()
    if row is None:
        raise ApiError(404, "not_found", "Conflict not found.")
    return row


def resolve_conflict(conn: Connection, user: Principal, scope: Scope, conflict_id: uuid.UUID,
                     keep: ConflictStatus) -> Conflict:
    _one(conn, user, scope, conflict_id)  # 404 before anything is locked
    status = conn.execute(text("SELECT status FROM app.sync_conflicts WHERE id = :id FOR UPDATE"),
                          {"id": conflict_id}).scalar()  # a second resolve of the same row waits here
    if status != ConflictStatus.open.value:
        raise ApiError(409, "conflict_resolved", "This conflict has already been decided.")
    row = _one(conn, user, scope, conflict_id)
    if keep == ConflictStatus.kept_client:
        _write_client_value(conn, user, scope, row)
    conn.execute(text("""
        UPDATE app.sync_conflicts SET status = CAST(:s AS app.conflict_status), resolved_by = :u, resolved_at = now()
         WHERE id = :id
    """), {"s": keep.value, "u": user.user_id, "id": conflict_id})
    return _conflict(_one(conn, user, scope, conflict_id))


def _invalid(e: ValidationError) -> ApiError:
    first = e.errors()[0]
    where = ".".join(str(p) for p in first.get("loc", ())) or "value"
    return ApiError(422, "validation_error", f"{where}: {first.get('msg', 'invalid')}")


def _write_client_value(conn: Connection, user: Principal, scope: Scope, row: Any) -> None:
    field, value, entity_id = row["field_name"], row["client_value"], row["entity_id"]
    if row["entity_type"] == "voter_survey":
        if field != "location" and field not in SurveyFields.model_fields:
            raise ApiError(422, "validation_error", f"{field}: no longer part of the survey; keep the server's value.")
        voter_in_scope(conn, scope, entity_id)
        server = read_survey(conn, entity_id)
        data = {f: v for f, v in (server.model_dump(mode="json") if server else {}).items() if f in SurveyFields.model_fields}
        data[field] = value
        try:
            body = SurveyIn(**data, version=server.version if server else 0)
        except ValidationError as e:
            raise _invalid(e) from None
        check_survey_references(conn, body)
        if write_survey(conn, user, entity_id, body) is None:
            raise ApiError(409, "version_conflict", "The survey changed just now. Try again.")
    elif row["entity_type"] == "new_voter":
        if field not in NewVoterFields.model_fields:
            raise ApiError(422, "validation_error", f"{field}: no longer part of the record; keep the server's value.")
        server = new_voter_in_scope(conn, scope, entity_id)
        data = {f: v for f, v in server.model_dump(mode="json").items() if f in NewVoterFields.model_fields}
        data[field] = value
        try:
            body = NewVoterPatch(**data, version=server.version)
        except ValidationError as e:
            raise _invalid(e) from None
        if write_new_voter_update(conn, scope, entity_id, body) is None:
            raise ApiError(409, "version_conflict", "The record changed just now. Try again.")
    else:  # Kutumbs have no versions; the push never makes these rows
        raise ApiError(422, "validation_error", "A Kutumb change cannot be kept from here; change the Kutumb instead.")
