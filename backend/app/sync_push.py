"""POST /sync/push: apply a phone's outbox items, each on its own.

Per item, inside a SAVEPOINT:
  1. Seen before (sync_mutations has this device + id)?  -> the stored result, nothing applied again.
  2. Role, input, the voter's area, list references      -> rejected (with a code) on failure.
  3. Write with the base version (same code as PUT /voters/{id}/survey):
       ok    -> applied
       stale -> conflict: one sync_conflicts row per field that differs; nothing written to the survey.
  4. Record the result in sync_mutations (INSERT ... ON CONFLICT DO NOTHING). If another request
     recorded the same id first (a retry racing the original), undo this item's savepoint and
     return that stored result instead, so the change is applied exactly once.
A bad item never fails the batch: the phone's outbox must not get stuck behind it.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Connection, text

from .deps import SURVEY_ROLES, Principal, check_roles
from .errors import ApiError
from .routers.voters import check_survey_references, read_survey, voter_in_scope, write_survey
from .schemas import PushError, PushItem, PushResult, PushStatus, Survey, SurveyFields, SurveyIn
from .scope import Scope

ENTITY = {"survey": "voter_survey"}  # PushType -> sync_mutations / sync_conflicts entity_type


class _Rejected(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def push(conn: Connection, user: Principal, scope: Scope, items: list[PushItem]) -> list[PushResult]:
    if user.device_id is None:
        raise ApiError(403, "device_required", "Changes are sent from the JANSETU app on an approved phone.")
    return [_one(conn, user, scope, item) for item in items]


def _stored(conn: Connection, user: Principal, item: PushItem) -> Any:
    return conn.execute(text("""
        SELECT status, error FROM app.sync_mutations WHERE device_id = :d AND client_mutation_id = :id
    """), {"d": user.device_id, "id": item.id}).mappings().first()


def _replay(conn: Connection, item: PushItem, prev: Any) -> PushResult:
    status = PushStatus(prev["status"])
    error = None
    if status == PushStatus.rejected:
        code, _, message = (prev["error"] or "rejected: ").partition(": ")
        error = PushError(code=code, message=message)
    survey = read_survey(conn, item.entity_id) if status != PushStatus.rejected else None
    return PushResult(id=item.id, status=status, duplicate=True, error=error, survey=survey)


def _one(conn: Connection, user: Principal, scope: Scope, item: PushItem) -> PushResult:
    prev = _stored(conn, user, item)
    if prev is not None:
        return _replay(conn, item, prev)

    savepoint = conn.begin_nested()
    try:
        try:
            result = _apply_survey(conn, user, scope, item)
        except _Rejected as r:
            result = PushResult(id=item.id, status=PushStatus.rejected, duplicate=False,
                                error=PushError(code=r.code, message=r.message))
        recorded = conn.execute(text("""
            INSERT INTO app.sync_mutations (tenant_id, device_id, client_mutation_id, entity_type, entity_id,
                                            operation, base_version, status, error)
            VALUES (app.current_tenant_id(), :d, :id, :entity, :entity_id, :op, :base, :status, :error)
            ON CONFLICT DO NOTHING
            RETURNING 1
        """), {"d": user.device_id, "id": item.id, "entity": ENTITY[item.type.value], "entity_id": item.entity_id,
               "op": "insert" if item.base_version == 0 else "update", "base": item.base_version,
               "status": result.status.value,
               "error": f"{result.error.code}: {result.error.message}" if result.error else None}).first()
        if recorded is None:  # the same id was recorded by a request running at the same time
            savepoint.rollback()
            return _replay(conn, item, _stored(conn, user, item))
        savepoint.commit()
        return result
    except BaseException:
        if savepoint.is_active:
            savepoint.rollback()
        raise


def _apply_survey(conn: Connection, user: Principal, scope: Scope, item: PushItem) -> PushResult:
    try:
        check_roles(user, SURVEY_ROLES)
    except ApiError as e:
        raise _Rejected(e.code, e.message) from None
    try:
        body = SurveyIn(**{k: v for k, v in item.data.items() if k != "version"}, version=item.base_version)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ())) or "data"
        raise _Rejected("validation_error", f"{where}: {first.get('msg', 'invalid')}") from None
    try:
        voter_in_scope(conn, scope, item.entity_id)
        check_survey_references(conn, body)
    except ApiError as e:
        raise _Rejected(e.code, e.message) from None

    saved = write_survey(conn, user, item.entity_id, body)
    if saved is not None:
        return PushResult(id=item.id, status=PushStatus.applied, duplicate=False, survey=saved)

    server = read_survey(conn, item.entity_id)
    differs = _differing_fields(body, server)
    if not differs:  # the server already holds exactly this: nothing to review
        return PushResult(id=item.id, status=PushStatus.applied, duplicate=False, survey=server)
    for name, (client_value, server_value) in differs.items():
        conn.execute(text("""
            INSERT INTO app.sync_conflicts (tenant_id, entity_type, entity_id, field_name, client_value, server_value,
                                            client_user_id, client_device_id, client_changed_at,
                                            server_user_id, server_changed_at)
            VALUES (app.current_tenant_id(), 'voter_survey', :voter, :field, CAST(:cv AS jsonb), CAST(:sv AS jsonb),
                    :user, :device, :changed_at, :server_user, :server_at)
        """), {"voter": item.entity_id, "field": name, "cv": json.dumps(client_value),
               "sv": json.dumps(server_value), "user": user.user_id, "device": user.device_id,
               "changed_at": item.changed_at, "server_user": server.updated_by if server else None,
               "server_at": server.updated_at if server else None})
    return PushResult(id=item.id, status=PushStatus.conflict, duplicate=False, survey=server,
                      conflict_fields=list(differs))


def _differing_fields(body: SurveyIn, server: Survey | None) -> dict[str, tuple[Any, Any]]:
    """{field: (phone value, server value)} for every survey field that differs (JSON values)."""
    client = body.model_dump(mode="json")
    current = server.model_dump(mode="json") if server else {}
    out = {f: (client[f], current.get(f)) for f in SurveyFields.model_fields if client[f] != current.get(f)}
    if body.location is not None:
        here = {"lat": body.location.lat, "lng": body.location.lng}
        there = {"lat": current.get("lat"), "lng": current.get("lng")}
        if here != there:
            out["location"] = (client["location"], {**there, "accuracy_m": current.get("location_accuracy_m")})
    return out
