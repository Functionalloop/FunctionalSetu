"""More menu (7.9): terms, announcements, problem reports. The app version check (6.3) is in app_version.py.

Contract only (4.10): every route answers 501 until its task is built. See app/stubs.py.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from ..deps import ActiveUser, Db, ReadyUser
from ..schemas_field import AnnouncementPage, ProblemReportIn, Terms, TermsAccept
from ..stubs import Cursor, Limit, not_built

router = APIRouter(tags=["more"])


@router.get("/terms/current", response_model=Terms, summary="Current terms of use. Public.")
def current_terms() -> Terms:
    not_built("7.9")


@router.post("/terms/accept", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
             summary="Record that the user accepted this terms version. All roles (also while the phone waits).")
def accept_terms(body: TermsAccept, conn: Db, user: ActiveUser) -> None:
    not_built("7.9")


@router.get("/announcements", response_model=AnnouncementPage,
            summary="Announcements for this user's area, newest first, with read flags. All roles.")
def list_announcements(conn: Db, user: ReadyUser, limit: Limit = 50, cursor: Cursor = None) -> AnnouncementPage:
    not_built("7.9")


@router.post("/announcements/{announcement_id}/read", status_code=status.HTTP_204_NO_CONTENT,
             response_class=Response, summary="Mark one announcement as read. All roles.")
def read_announcement(announcement_id: uuid.UUID, conn: Db, user: ReadyUser) -> None:
    not_built("7.9")


@router.post("/problem-reports", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
             summary="'Report a problem' from the Help screen. All roles (also while the phone waits).")
def report_problem(body: ProblemReportIn, conn: Db, user: ActiveUser) -> None:
    not_built("7.9")
