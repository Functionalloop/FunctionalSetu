"""Field work (plan step 7): walk list, part notes, the server-drawn slip.

Contract only (4.10): every route answers 501 until its task is built. See app/stubs.py.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response

from ..deps import Db, ReadyUser
from ..schemas_field import PartNote, PartNoteIn, VisitOutcome, WalkListPage
from ..stubs import Cursor, Limit, Surveyor, not_built

router = APIRouter(tags=["field work"])


# --- walk list (7.2) ----------------------------------------------------------------------
# The Kutumb Connect routes (7.1) are in families.py.
@router.get("/families", response_model=WalkListPage,
            summary="Walk list: houses of a booth in house-number order, with the last visit. All roles.")
def walk_list(conn: Db, user: ReadyUser, booth_id: uuid.UUID,
              outcome: Annotated[VisitOutcome | None, Query(description="only houses whose last visit was this")] = None,
              not_visited: bool = False, limit: Limit = 50, cursor: Cursor = None) -> WalkListPage:
    not_built("7.2")


# --- part notes (7.11) ------------------------------------------------------------------------
@router.get("/booths/{booth_id}/note", response_model=PartNote,
            summary="The shared note of a part (its booth); version 0 and empty text if none yet. All roles.")
def get_part_note(booth_id: uuid.UUID, conn: Db, user: ReadyUser) -> PartNote:
    not_built("7.11")


@router.put("/booths/{booth_id}/note", response_model=PartNote,
            summary="Save the part's shared note. Stale version: 409 with the server copy. Survey roles.")
def save_part_note(booth_id: uuid.UUID, body: PartNoteIn, conn: Db, user: Surveyor) -> PartNote:
    not_built("7.11")


# History (7.6, Information Updation) is in voters.py.
# --- slips (7.7, 12.2) ------------------------------------------------------------------------
# POST /voters/{id}/slip-events (7.7) is in slips.py.
@router.get("/voters/{voter_id}/slip", response_class=Response,
            responses={200: {"content": {"image/png": {}, "application/pdf": {}},
                             "description": "The slip as a PNG image or a PDF"}},
            summary="The voter slip drawn by the server (for the portal). All roles.")
def voter_slip(voter_id: uuid.UUID, conn: Db, user: ReadyUser,
               format: Annotated[str, Query(pattern="^(png|pdf)$")] = "png",
               lang: Annotated[str, Query(pattern="^(mr|en)$")] = "mr") -> Response:
    not_built("12.2")


# GET /birthdays (7.8) is in birthdays.py.
