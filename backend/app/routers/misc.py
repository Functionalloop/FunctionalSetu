"""More menu (7.9): terms, announcements, problem reports. The app version check (6.3) is in app_version.py.

- Terms are global rows (app.terms_versions), loaded by us from the client's text; none yet = 404, and
  the phone says the text has not arrived. Accepting stores the version on the user (GET /me shows it).
- Announcements are made by admins (Step 9). A user sees those for everyone and those whose area
  overlaps theirs: the area contains the user's area (a ward's announcement reaches its booths) or lies
  inside it (an admin sees the booth announcements of the constituency). Expired or deleted ones are
  left out. Reading one stores a row in announcement_reads (once).
- Problem reports come from Help: who, which phone, app version, phone model. Admins read them later.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import Connection, text

from ..db import transaction
from ..deps import ActiveUser, Db, Principal, ReadyUser
from ..errors import ApiError
from ..paging import decode_cursor, encode_cursor, invalid_cursor
from ..schemas import UserSummary
from ..schemas_field import Announcement, AnnouncementPage, ProblemReportIn, Terms, TermsAccept
from ..scope import Scope, UserScope

router = APIRouter(tags=["more"])

_TERMS = text("SELECT version, body_mr, body_en, published_at FROM app.terms_versions ORDER BY version DESC LIMIT 1")


@router.get("/terms/current", response_model=Terms,
            summary="Current terms of use. Public. 404 not_found until the terms text has been loaded.")
def current_terms() -> Terms:
    with transaction() as conn:
        row = conn.execute(_TERMS).mappings().first()
    if row is None:
        raise ApiError(404, "not_found", "The terms of use have not been published yet.")
    return Terms(**row)


@router.post("/terms/accept", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
             summary="Record that the user accepted this terms version (it must be the current one, else 409 "
                     "terms_changed). All roles (also while the phone waits).")
def accept_terms(body: TermsAccept, conn: Db, user: ActiveUser) -> Response:
    current = conn.execute(_TERMS).mappings().first()
    if current is None:
        raise ApiError(404, "not_found", "The terms of use have not been published yet.")
    if current["version"] != body.version:
        raise ApiError(409, "terms_changed", "The terms of use have changed. Read the new text and accept again.")
    conn.execute(text("UPDATE app.users SET terms_version = :v, terms_accepted_at = now() WHERE id = :u"),
                 {"v": body.version, "u": user.user_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _visible(scope: Scope) -> tuple[str, dict[str, Any]]:
    """Announcements this user may see (besides RLS, expiry and deletion)."""
    base = "a.deleted_at IS NULL AND (a.expires_at IS NULL OR a.expires_at > now())"
    if scope.is_empty:
        return f"{base} AND a.audience_geo_id IS NULL", {}
    if scope.whole_workspace:
        return base, {}
    return (f"{base} AND (a.audience_geo_id IS NULL OR g.path <@ CAST(:aud_paths AS ltree[]) "
            f"OR g.path @> CAST(:aud_paths AS ltree[]))"), {"aud_paths": list(scope.paths)}


_FROM = """
    FROM app.announcements a
    JOIN app.users u ON u.id = a.created_by
    LEFT JOIN app.geo_units g ON g.id = a.audience_geo_id
"""


@router.get("/announcements", response_model=AnnouncementPage,
            summary="Announcements for this user's area, newest first, with read flags. All roles.")
def list_announcements(conn: Db, user: ReadyUser, scope: UserScope,
                       limit: Annotated[int, Query(ge=1, le=200)] = 50,
                       cursor: Annotated[str | None, Query(description="next_cursor from the previous page")] = None,
                       ) -> AnnouncementPage:
    cond, params = _visible(scope)
    if cursor:
        at, i = decode_cursor(cursor, 2)
        try:
            params.update(c_at=datetime.fromisoformat(str(at)), c_id=uuid.UUID(str(i)))
        except ValueError:
            raise invalid_cursor() from None
        cond += " AND (a.created_at, a.id) < (:c_at, :c_id)"
    rows = conn.execute(text(f"""
        SELECT a.id, a.body, a.audience_geo_id, a.created_at, a.expires_at,
               u.id AS u_id, u.username, u.full_name_en, u.full_name_mr, u.role,
               EXISTS (SELECT 1 FROM app.announcement_reads r
                        WHERE r.announcement_id = a.id AND r.user_id = :me) AS is_read
        {_FROM}
        WHERE {cond}
        ORDER BY a.created_at DESC, a.id DESC
        LIMIT :n
    """), {**params, "me": user.user_id, "n": limit + 1}).mappings().all()
    items = [_announcement(r) for r in rows[:limit]]
    last = rows[limit - 1] if len(rows) > limit else None
    return AnnouncementPage(items=items,
                            next_cursor=encode_cursor([last["created_at"].isoformat(), str(last["id"])]) if last else None)


def _announcement(r: Any) -> Announcement:
    return Announcement(id=r["id"], body=r["body"], audience_geo_id=r["audience_geo_id"], created_at=r["created_at"],
                        expires_at=r["expires_at"], is_read=r["is_read"],
                        created_by=UserSummary(id=r["u_id"], username=r["username"], full_name_en=r["full_name_en"],
                                               full_name_mr=r["full_name_mr"], role=r["role"]))


@router.post("/announcements/{announcement_id}/read", status_code=status.HTTP_204_NO_CONTENT,
             response_class=Response, summary="Mark one announcement as read (again is fine). All roles.")
def read_announcement(announcement_id: uuid.UUID, conn: Db, user: ReadyUser, scope: UserScope) -> Response:
    mark_read(conn, user, scope, announcement_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def mark_read(conn: Connection, user: Principal, scope: Scope, announcement_id: uuid.UUID) -> None:
    cond, params = _visible(scope)
    seen = conn.execute(text(f"SELECT 1 {_FROM} WHERE a.id = :id AND {cond}"),
                        {**params, "id": announcement_id}).first()
    if seen is None:
        raise ApiError(404, "not_found", "Announcement not found.")
    conn.execute(text("""
        INSERT INTO app.announcement_reads (tenant_id, announcement_id, user_id)
        VALUES (app.current_tenant_id(), :a, :u) ON CONFLICT DO NOTHING
    """), {"a": announcement_id, "u": user.user_id})


@router.post("/problem-reports", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
             summary="'Report a problem' from the Help screen. All roles (also while the phone waits).")
def report_problem(body: ProblemReportIn, conn: Db, user: ActiveUser) -> Response:
    text_body = body.body.strip()
    if not text_body:
        raise ApiError(422, "validation_error", "body: write what went wrong.")
    conn.execute(text("""
        INSERT INTO app.problem_reports (tenant_id, user_id, device_id, body, app_version_code, phone_model)
        VALUES (app.current_tenant_id(), :u, CAST(:d AS uuid), :b, :v, :m)
    """), {"u": user.user_id, "d": user.device_id, "b": text_body, "v": body.app_version_code,
           "m": body.phone_model.strip() if body.phone_model else None})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
