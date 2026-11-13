"""Field work (plan step 7): walk list, part notes, visits, new voters, history, slips, birthdays.

Contract only (4.10): every route answers 501 until its task is built. See app/stubs.py.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from ..deps import Db, ReadyUser
from ..schemas_field import (BirthdayPage, HistoryPage, NewVoter, NewVoterIn, NewVoterPage, NewVoterPatch, PartNote,
                             PartNoteIn, SlipEventIn, Visit, VisitIn, VisitOutcome, WalkListPage)
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


# --- visits (7.3) -----------------------------------------------------------------------------
@router.post("/voters/{voter_id}/visits", response_model=Visit, status_code=status.HTTP_201_CREATED,
             summary="Record a visit (met, not home, revisit, shifted). A repeat id is stored once. Survey roles.")
def add_visit(voter_id: uuid.UUID, body: VisitIn, conn: Db, user: Surveyor) -> Visit:
    not_built("7.3")


# --- new voters (7.5) -------------------------------------------------------------------------
@router.get("/new-voters", response_model=NewVoterPage,
            summary="People added by hand (not on the roll), with Form 6 status. Survey roles.")
def list_new_voters(conn: Db, user: Surveyor, ward_id: uuid.UUID | None = None,
                    form6_status: str | None = None, limit: Limit = 50, cursor: Cursor = None) -> NewVoterPage:
    not_built("7.5")


@router.post("/new-voters", response_model=NewVoter, status_code=status.HTTP_201_CREATED,
             summary="Add a person who is not on the roll. A repeat id is stored once. Survey roles.")
def add_new_voter(body: NewVoterIn, conn: Db, user: Surveyor) -> NewVoter:
    not_built("7.5")


@router.patch("/new-voters/{new_voter_id}", response_model=NewVoter,
              summary="Edit a new voter or its Form 6 status. Stale version: 409 with the server copy. Survey roles.")
def update_new_voter(new_voter_id: uuid.UUID, body: NewVoterPatch, conn: Db, user: Surveyor) -> NewVoter:
    not_built("7.5")


# --- history (7.6) ----------------------------------------------------------------------------
@router.get("/voters/{voter_id}/history", response_model=HistoryPage,
            summary="Every change to the voter, newest first: survey, visits, voted, roll edits. All roles.")
def voter_history(voter_id: uuid.UUID, conn: Db, user: ReadyUser, limit: Limit = 50,
                  cursor: Cursor = None) -> HistoryPage:
    not_built("7.6")


# --- slips (7.7, 12.2) ------------------------------------------------------------------------
@router.post("/voters/{voter_id}/slip-events", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
             summary="Log that a slip was shared or printed. A repeat id is stored once. All roles.")
def add_slip_event(voter_id: uuid.UUID, body: SlipEventIn, conn: Db, user: ReadyUser) -> None:
    not_built("7.7")


@router.get("/voters/{voter_id}/slip", response_class=Response,
            responses={200: {"content": {"image/png": {}, "application/pdf": {}},
                             "description": "The slip as a PNG image or a PDF"}},
            summary="The voter slip drawn by the server (for the portal). All roles.")
def voter_slip(voter_id: uuid.UUID, conn: Db, user: ReadyUser,
               format: Annotated[str, Query(pattern="^(png|pdf)$")] = "png",
               lang: Annotated[str, Query(pattern="^(mr|en)$")] = "mr") -> Response:
    not_built("12.2")


# --- birthdays (7.8) --------------------------------------------------------------------------
@router.get("/birthdays", response_model=BirthdayPage,
            summary="Voters in the user's area with a birthday between two dates (day and month). All roles.")
def birthdays(conn: Db, user: ReadyUser, date_from: date, date_to: date | None = None,
              booth_id: uuid.UUID | None = None, limit: Limit = 50, cursor: Cursor = None) -> BirthdayPage:
    not_built("7.8")
