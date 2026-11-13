"""Voter slips (plan 7.7): POST /voters/{id}/slip-events, also used by the push type `slip_event`.

The slip itself is drawn on the phone from its own data and the election settings (pull); the
server only logs that it was shared. The event is stored under the phone-made id
(slip_events.client_mutation_id), so the same share sent again is stored once. created_at is the
phone's time of sharing, never later than the server's clock. GET /voters/{id}/slip (the server's
own image, for the portal) is task 12.2 and still a stub in field.py.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status
from sqlalchemy import Connection, text

from ..deps import Db, Principal, ReadyUser
from ..errors import ApiError
from ..schemas_field import SlipEventIn
from ..scope import Scope, UserScope
from .voters import voter_in_scope

router = APIRouter(tags=["field work"])


@router.post("/voters/{voter_id}/slip-events", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
             summary="Log that a slip was shared or printed. A repeat id is stored once. All roles.")
def add_slip_event(voter_id: uuid.UUID, body: SlipEventIn, conn: Db, user: ReadyUser, scope: UserScope) -> Response:
    write_slip_event(conn, user, scope, voter_id, body)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def write_slip_event(conn: Connection, user: Principal, scope: Scope, voter_id: uuid.UUID, body: SlipEventIn) -> None:
    """Store the event once. 404 outside the area; 409 when the id was used for another voter."""
    voter_in_scope(conn, scope, voter_id)
    conn.execute(text("""
        INSERT INTO app.slip_events (tenant_id, voter_id, channel, created_by, device_id, created_at, client_mutation_id)
        VALUES (app.current_tenant_id(), :voter, CAST(:channel AS app.slip_channel), :user, CAST(:device AS uuid),
                least(:at, now()), :id)
        ON CONFLICT DO NOTHING
    """), {"voter": voter_id, "channel": body.channel.value, "user": user.user_id, "device": user.device_id,
           "at": body.at, "id": body.id})
    stored = conn.execute(text("SELECT voter_id FROM app.slip_events WHERE client_mutation_id = :id"),
                          {"id": body.id}).scalar()
    if stored != voter_id:
        raise ApiError(409, "id_in_use", "This id is already used by another record; make a new id.")
