"""Part notes (7.11): one shared note per roll part (its booth), up to 2,000 characters.

Everyone whose area holds the part reads it (also booth agents); survey roles write it. It has a
version like the survey: a save names the version it was based on (0 = no note yet); a stale one is
409 with the server copy (push type `part_note`: a conflict with the server copy, nothing written).
No sync_conflicts row: that table takes surveys, new voters and Kutumbs only, and the phone keeps its
text until the worker picks a copy. The pull sends notes in phase `part_notes`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import Connection, text

from ..deps import Db, Principal, ReadyUser
from ..errors import ApiError
from ..schemas_field import PartNote, PartNoteIn
from ..scope import Scope, UserScope
from ..stubs import Surveyor
from .families import _require_booth

router = APIRouter(tags=["field work"])

PART_NOTE_COLS = "p.booth_id, p.note, p.version, p.updated_at, p.updated_by"


def read_part_note(conn: Connection, booth_id: uuid.UUID) -> PartNote:
    """The stored note, or version 0 and empty text when the part has none yet."""
    row = conn.execute(text(f"SELECT {PART_NOTE_COLS} FROM app.part_notes p WHERE p.booth_id = :b"),
                       {"b": booth_id}).mappings().first()
    return PartNote(**row) if row else PartNote(booth_id=booth_id, note="", version=0, updated_at=None, updated_by=None)


def write_part_note(conn: Connection, user: Principal, scope: Scope, booth_id: uuid.UUID,
                    body: PartNoteIn) -> PartNote | None:
    """Save on top of `body.version`; None when it is stale. 404 when the booth is outside the area.
    The caller has checked the role."""
    _require_booth(conn, scope, booth_id)
    params = {"b": booth_id, "note": body.note, "v": body.version, "u": user.user_id, "d": user.device_id}
    if body.version == 0:
        row = conn.execute(text("""
            INSERT INTO app.part_notes (tenant_id, booth_id, note, updated_by, updated_device_id)
            VALUES (app.current_tenant_id(), :b, :note, :u, :d)
            ON CONFLICT (tenant_id, booth_id) DO NOTHING
            RETURNING id
        """), params).first()
    else:
        row = conn.execute(text("""
            UPDATE app.part_notes SET note = :note, updated_by = :u, updated_device_id = :d
             WHERE booth_id = :b AND version = :v
            RETURNING id
        """), params).first()
    return read_part_note(conn, booth_id) if row else None


@router.get("/booths/{booth_id}/note", response_model=PartNote,
            summary="The shared note of a part (its booth); version 0 and empty text if none yet. All roles.")
def get_part_note(booth_id: uuid.UUID, conn: Db, user: ReadyUser, scope: UserScope) -> PartNote:
    _require_booth(conn, scope, booth_id)
    return read_part_note(conn, booth_id)


@router.put("/booths/{booth_id}/note", response_model=PartNote,
            summary="Save the part's shared note. Stale version: 409 with the server copy. Survey roles.")
def save_part_note(booth_id: uuid.UUID, body: PartNoteIn, conn: Db, user: Surveyor, scope: UserScope) -> PartNote:
    saved = write_part_note(conn, user, scope, booth_id, body)
    if saved is None:
        current = read_part_note(conn, booth_id)
        raise ApiError(409, "version_conflict",
                       "Someone else changed this part's note. Check the server copy and save again.",
                       extra={"current": current.model_dump(mode="json")})
    return saved
