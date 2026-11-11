"""Reports and exports (plan step 11). Supervisor and above, for their own area.

Contract only (4.10): every route answers 501 until its task is built. See app/stubs.py.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from ..deps import Db
from ..schemas_roll import ColorTagReport, Demographics, Export, ExportIn, SurveyProgress, TurnoutReport
from ..stubs import Supervisor, not_built

router = APIRouter(tags=["reports"])


@router.get("/reports/survey-progress", response_model=SurveyProgress,
            summary="Surveyed vs total by ward and booth. Supervisor.")
def survey_progress(conn: Db, user: Supervisor, ward_id: uuid.UUID | None = None) -> SurveyProgress:
    not_built("11.1")


@router.get("/reports/colour-tags", response_model=ColorTagReport, summary="Counts by colour tag. Supervisor.")
def colour_tags(conn: Db, user: Supervisor, ward_id: uuid.UUID | None = None) -> ColorTagReport:
    not_built("11.1")


@router.get("/reports/demographics", response_model=Demographics, summary="Age and gender. Supervisor.")
def demographics(conn: Db, user: Supervisor, ward_id: uuid.UUID | None = None,
                 booth_id: uuid.UUID | None = None) -> Demographics:
    not_built("11.1")


@router.get("/reports/turnout", response_model=TurnoutReport,
            summary="Polling-day turnout by area and hour. Supervisor.")
def turnout_report(conn: Db, user: Supervisor, ward_id: uuid.UUID | None = None) -> TurnoutReport:
    not_built("11.1")


@router.post("/exports", response_model=Export, status_code=status.HTTP_202_ACCEPTED,
             summary="Start a PDF or Excel export of a list (filters and columns); poll it. Supervisor.")
def start_export(body: ExportIn, conn: Db, user: Supervisor) -> Export:
    not_built("11.2")


@router.get("/exports/{export_id}", response_model=Export, summary="An export's status. Supervisor.")
def get_export(export_id: uuid.UUID, conn: Db, user: Supervisor) -> Export:
    not_built("11.2")


@router.get("/exports/{export_id}/download", response_class=Response,
            responses={200: {"content": {"application/pdf": {}, "application/vnd.openxmlformats-officedocument."
                                                                  "spreadsheetml.sheet": {}},
                             "description": "The finished file"}},
            summary="Download a finished export. Supervisor.")
def download_export(export_id: uuid.UUID, conn: Db, user: Supervisor) -> Response:
    not_built("11.2")
