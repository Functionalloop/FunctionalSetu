"""Admin (plan step 9): team and logs (9.5).

Contract only (4.10): every route answers 501 until its task is built. See app/stubs.py.
Built elsewhere: users and assignments (users.py), constituencies (constituencies.py), election settings
(settings.py), lists and labels (masters.py), files (files.py).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from ..deps import Db
from ..schemas_admin import AnnouncementIn, AuditPage, ProblemReportPage, WorkerActivity, WorkerLocationPage
from ..schemas_field import Announcement
from ..stubs import Admin, Cursor, Limit, not_built

router = APIRouter(tags=["admin"])


# --- team and logs (9.5) -------------------------------------------------------------------
@router.post("/announcements", response_model=Announcement, status_code=status.HTTP_201_CREATED,
             summary="Send an announcement to everyone or one area. Admin.")
def create_announcement(body: AnnouncementIn, conn: Db, user: Admin) -> Announcement:
    not_built("9.5")


@router.delete("/announcements/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
               summary="Remove an announcement. Admin.")
def delete_announcement(announcement_id: uuid.UUID, conn: Db, user: Admin) -> None:
    not_built("9.5")


@router.get("/problem-reports", response_model=ProblemReportPage,
            summary="Problems reported from the Help screen, newest first. Admin.")
def list_problem_reports(conn: Db, user: Admin,
                         status_filter: Annotated[str | None, Query(alias="status", pattern="^(open|done)$")] = None,
                         limit: Limit = 50, cursor: Cursor = None) -> ProblemReportPage:
    not_built("9.5")


@router.get("/audit-log", response_model=AuditPage, summary="Who changed what and when, newest first. Admin.")
def audit_log(conn: Db, user: Admin, entity_type: str | None = None, entity_id: str | None = None,
              actor_user_id: uuid.UUID | None = None, date_from: date | None = None, date_to: date | None = None,
              limit: Limit = 50, cursor: Cursor = None) -> AuditPage:
    not_built("9.5")


@router.get("/reports/worker-activity", response_model=WorkerActivity,
            summary="Surveys, visits, mobiles, new voters and voted marks per worker per day. Admin.")
def worker_activity(conn: Db, user: Admin, date_from: date, date_to: date,
                    user_id: uuid.UUID | None = None) -> WorkerActivity:
    not_built("9.5")


@router.get("/worker-locations", response_model=WorkerLocationPage,
            summary="Where surveys and visits were saved (no live tracking). Admin.")
def worker_locations(conn: Db, user: Admin, date_from: date, date_to: date, user_id: uuid.UUID | None = None,
                     limit: Limit = 50, cursor: Cursor = None) -> WorkerLocationPage:
    not_built("9.5")
