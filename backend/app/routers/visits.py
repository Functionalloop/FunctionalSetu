"""Visits (plan 7.3): POST /voters/{id}/visits, also used by the push type `visit`.

A visit is stored under the phone-made id, so the same visit sent again (REST retry, push retry,
or a rebuilt outbox) is stored once. booth_id and house_no are copied from the voter, so the walk
list can mark a whole house ("not home") through any voter in it; family_id is the voter's Kutumb
at that moment. Visits do not touch voter_surveys (its last_visit_* columns stay unused): writing
there would raise the survey version and give false 409s on survey saves.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import Connection, text

from ..deps import Db, Principal
from ..errors import ApiError
from ..schemas import Visit
from ..schemas_field import VisitIn
from ..scope import Scope, UserScope
from ..stubs import Surveyor
from .voters import voter_in_scope

router = APIRouter(tags=["field work"])

_COLS = ", ".join(Visit.model_fields)


def read_visit(conn: Connection, visit_id: uuid.UUID | str) -> Visit | None:
    try:
        visit_id = uuid.UUID(str(visit_id))
    except ValueError:
        return None
    row = conn.execute(text(f"SELECT {_COLS} FROM app.visits WHERE id = :id AND deleted_at IS NULL"),
                       {"id": visit_id}).mappings().first()
    return Visit(**row) if row else None


@router.post("/voters/{voter_id}/visits", response_model=Visit, status_code=status.HTTP_201_CREATED,
             summary="Record a visit (met, not home, revisit, shifted). A repeat id is stored once. Survey roles.")
def add_visit(voter_id: uuid.UUID, body: VisitIn, conn: Db, user: Surveyor, scope: UserScope) -> Visit:
    return write_visit(conn, user, scope, voter_id, body)


def write_visit(conn: Connection, user: Principal, scope: Scope, voter_id: uuid.UUID, body: VisitIn) -> Visit:
    """Store the visit, or return the stored one when this id was sent before. The caller checked the role."""
    voter_in_scope(conn, scope, voter_id)
    loc = body.location
    conn.execute(text("""
        INSERT INTO app.visits (id, tenant_id, booth_id, house_no, family_id, voter_id, outcome, revisit_at, note,
                                lat, lng, accuracy_m, visited_by, device_id, visited_at, client_mutation_id)
        SELECT :id, v.tenant_id, v.booth_id, v.house_no,
               (SELECT m.family_id FROM app.family_members m WHERE m.voter_id = v.id),
               v.id, CAST(:outcome AS app.visit_outcome), :revisit_at, :note, :lat, :lng, :acc,
               :user, CAST(:device AS uuid), :visited_at, :id
          FROM app.voters v WHERE v.id = :voter
        ON CONFLICT DO NOTHING
    """), {"id": body.id, "voter": voter_id, "outcome": body.outcome.value, "revisit_at": body.revisit_at,
           "note": body.note, "lat": loc.lat if loc else None, "lng": loc.lng if loc else None,
           "acc": loc.accuracy_m if loc else None, "user": user.user_id, "device": user.device_id,
           "visited_at": body.visited_at})
    stored = read_visit(conn, body.id)
    if stored is None or stored.voter_id != voter_id:
        # The id is taken by a visit this user cannot see, or by a visit of another voter.
        raise ApiError(409, "id_in_use", "This id is already used by another record; make a new id.")
    return stored
