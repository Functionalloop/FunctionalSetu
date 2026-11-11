"""Polling day (plan 8.1): voted marks and turnout. Booth agent, supervisor, admin, super admin; not surveyor.

Contract only (4.10): every route answers 501 until 8.1 is built. See app/stubs.py.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from ..deps import Db
from ..schemas_field import TurnoutMarkIn, TurnoutMarkResult, TurnoutSummary
from ..stubs import BoothAgent, not_built

router = APIRouter(prefix="/turnout", tags=["polling day"])


@router.get("/summary", response_model=TurnoutSummary,
            summary="Voted count and percentage for the user's area, by booth. Polling-day roles.")
def turnout_summary(conn: Db, user: BoothAgent, ward_id: uuid.UUID | None = None,
                    booth_id: uuid.UUID | None = None) -> TurnoutSummary:
    not_built("8.1")


@router.post("/marks", response_model=TurnoutMarkResult,
             summary="Mark voters as voted, by id or by booth + serial numbers ('12, 15, 18-25'). Polling-day roles.")
def add_marks(body: TurnoutMarkIn, conn: Db, user: BoothAgent) -> TurnoutMarkResult:
    not_built("8.1")


@router.delete("/marks/{voter_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
               summary="Undo a wrong voted mark. Polling-day roles.")
def clear_mark(voter_id: uuid.UUID, conn: Db, user: BoothAgent) -> None:
    not_built("8.1")
