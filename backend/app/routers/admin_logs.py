"""Team and logs (9.5): announcements (send, remove), problem reports, activity log, worker activity, worker
locations. Admin and super admin.

Whose records an admin sees: those of the users of their own constituency (users.local_body_id), the admin
included; a super admin sees the whole workspace. A user id outside that is 404, like everywhere.

- Announcements: an admin sends to an area inside their constituency; "everyone" from an admin means their
  constituency (only a super admin reaches the whole workspace). Removing = deleted_at; an admin removes only
  those of their constituency.
- Activity log: app.audit_log rows. `password_hash` (users rows) is never sent.
- Worker activity per Indian day: surveys and mobiles from the activity log (voter_surveys keeps only the last
  saver), so a survey saved twice in a day counts once; visits, new voters and standing voted marks from their
  own tables.
- Worker locations: the place a survey was saved with a location (activity log) or a visit was made. No live
  tracking.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import Connection, text

from ..deps import Db, Principal
from ..errors import ApiError
from ..paging import decode_cursor, encode_cursor, invalid_cursor
from ..schemas import Role, UserSummary
from ..schemas_admin import (AnnouncementIn, AuditEntry, AuditPage, ProblemReport, ProblemReportPage, WorkerActivity,
                             WorkerDay, WorkerLocation, WorkerLocationPage)
from ..schemas_field import Announcement
from ..scope import UserScope, require_area
from ..stubs import Admin, Cursor, Limit

router = APIRouter(tags=["admin"])

MAX_DAYS = 92
HIDDEN_AUDIT_KEYS = frozenset({"password_hash"})
_IST = "'Asia/Kolkata'"
_USER_COLS = "u.id AS u_id, u.username, u.full_name_en, u.full_name_mr, u.role"


def _team(admin: Principal, alias: str = "u") -> tuple[str, dict]:
    """Users whose records the caller sees."""
    return (f"({alias}.deleted_at IS NULL AND (:is_super OR {alias}.local_body_id = :lb))",
            {"is_super": admin.role == Role.super_admin, "lb": admin.local_body_id})


def _check_worker(conn: Connection, admin: Principal, user_id: uuid.UUID | None) -> None:
    if user_id is None:
        return
    cond, params = _team(admin)
    if conn.execute(text(f"SELECT 1 FROM app.users u WHERE u.id = :id AND {cond}"), {**params, "id": user_id}).first() \
            is None:
        raise ApiError(404, "not_found", "User not found.")


def _summary(r: Any) -> UserSummary:
    return UserSummary(id=r["u_id"], username=r["username"], full_name_en=r["full_name_en"],
                       full_name_mr=r["full_name_mr"], role=r["role"])


def _range(date_from: date | None, date_to: date | None, required: bool) -> dict:
    """Indian dates -> the params t0 / t1 (timestamptz bounds, t1 exclusive)."""
    if date_from and date_to and date_to < date_from:
        raise ApiError(422, "validation_error", "date_to is before date_from.")
    if required and (date_to - date_from).days >= MAX_DAYS:  # type: ignore[operator]
        raise ApiError(422, "validation_error", f"At most {MAX_DAYS} days at a time.")
    return {"df": date_from, "dt1": date_to + timedelta(days=1) if date_to else None}


_T0 = f"(CAST(:df AS date)::timestamp AT TIME ZONE {_IST})"
_T1 = f"(CAST(:dt1 AS date)::timestamp AT TIME ZONE {_IST})"


# --- announcements ---------------------------------------------------------------------------------
@router.post("/announcements", response_model=Announcement, status_code=status.HTTP_201_CREATED,
             summary="Send an announcement to everyone or one area. Admin.")
def create_announcement(body: AnnouncementIn, conn: Db, user: Admin, scope: UserScope) -> Announcement:
    text_body = body.body.strip()
    if not text_body:
        raise ApiError(422, "validation_error", "body cannot be empty.")
    if body.expires_at is not None and body.expires_at <= datetime.now(body.expires_at.tzinfo):
        raise ApiError(422, "validation_error", "expires_at must be in the future.")
    audience = body.audience_geo_id
    if audience is not None:
        require_area(conn, scope, audience)
    elif user.role != Role.super_admin:
        audience = user.local_body_id  # an admin's "everyone" is their constituency
    row = conn.execute(text(f"""
        WITH a AS (
            INSERT INTO app.announcements (tenant_id, body, audience_geo_id, created_by, expires_at)
            VALUES (:tenant, :body, :aud, :by, :exp)
            RETURNING id, body, audience_geo_id, created_at, expires_at, created_by)
        SELECT a.*, {_USER_COLS} FROM a JOIN app.users u ON u.id = a.created_by
    """), {"tenant": user.tenant_id, "body": text_body, "aud": audience, "by": user.user_id,
           "exp": body.expires_at}).mappings().one()
    return Announcement(id=row["id"], body=row["body"], audience_geo_id=row["audience_geo_id"],
                        created_by=_summary(row), created_at=row["created_at"], expires_at=row["expires_at"],
                        is_read=False)


@router.delete("/announcements/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
               summary="Remove an announcement. Admin.")
def delete_announcement(announcement_id: uuid.UUID, conn: Db, user: Admin, scope: UserScope) -> Response:
    # An admin: only announcements for an area inside their constituency (not the super admin's "everyone").
    cond, params = scope.filter("g.path")
    done = conn.execute(text(f"""
        UPDATE app.announcements a SET deleted_at = now()
          FROM (SELECT a2.id FROM app.announcements a2
                  LEFT JOIN app.geo_units g ON g.id = a2.audience_geo_id
                 WHERE a2.id = :id AND a2.deleted_at IS NULL
                   AND (:is_super OR (g.id IS NOT NULL AND {cond}))) x
         WHERE a.id = x.id
        RETURNING a.id
    """), {**params, "id": announcement_id, "is_super": user.role == Role.super_admin}).first()
    if done is None:
        raise ApiError(404, "not_found", "Announcement not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- problem reports -----------------------------------------------------------------------------
@router.get("/problem-reports", response_model=ProblemReportPage,
            summary="Problems reported from the Help screen, newest first. Admin.")
def list_problem_reports(conn: Db, user: Admin,
                         status_filter: Annotated[str | None, Query(alias="status", pattern="^(open|done)$")] = None,
                         limit: Limit = 50, cursor: Cursor = None) -> ProblemReportPage:
    cond, params = _team(user)
    where = [cond]
    if status_filter:
        where.append("p.status = :st")
        params["st"] = status_filter
    if cursor:
        at, i = decode_cursor(cursor, 2)
        try:
            params.update(c_at=datetime.fromisoformat(str(at)), c_id=uuid.UUID(str(i)))
        except ValueError:
            raise invalid_cursor() from None
        where.append("(p.created_at, p.id) < (:c_at, :c_id)")
    rows = conn.execute(text(f"""
        SELECT p.id, p.device_id, p.body, p.app_version_code, p.phone_model, p.status, p.created_at, {_USER_COLS}
          FROM app.problem_reports p JOIN app.users u ON u.id = p.user_id
         WHERE {' AND '.join(where)}
         ORDER BY p.created_at DESC, p.id DESC LIMIT :n
    """), {**params, "n": limit + 1}).mappings().all()
    items = [ProblemReport(id=r["id"], user=_summary(r), device_id=r["device_id"], body=r["body"],
                           app_version_code=r["app_version_code"], phone_model=r["phone_model"], status=r["status"],
                           created_at=r["created_at"]) for r in rows[:limit]]
    last = rows[limit - 1] if len(rows) > limit else None
    return ProblemReportPage(items=items, next_cursor=encode_cursor([last["created_at"].isoformat(), str(last["id"])])
                             if last else None)


# --- activity log ----------------------------------------------------------------------------------
def _clean(values: dict | None) -> dict | None:
    if values is None:
        return None
    return {k: v for k, v in values.items() if k not in HIDDEN_AUDIT_KEYS}


@router.get("/audit-log", response_model=AuditPage, summary="Who changed what and when, newest first. Admin.")
def audit_log(conn: Db, user: Admin, entity_type: str | None = None, entity_id: str | None = None,
              actor_user_id: uuid.UUID | None = None, date_from: date | None = None, date_to: date | None = None,
              limit: Limit = 50, cursor: Cursor = None) -> AuditPage:
    _check_worker(conn, user, actor_user_id)
    params: dict = {"is_super": user.role == Role.super_admin, "lb": user.local_body_id,
                    **_range(date_from, date_to, required=False), "n": limit + 1}
    # An admin sees the changes made by their team; a super admin also those with no user (scripts).
    where = ["(:is_super OR (u.deleted_at IS NULL AND u.local_body_id = :lb))"]
    for name, value, sql in (("et", entity_type, "a.entity_type = :et"), ("ei", entity_id, "a.entity_id = :ei"),
                             ("ac", actor_user_id, "a.actor_user_id = :ac")):
        if value is not None:
            where.append(sql)
            params[name] = value
    if date_from:
        where.append(f"a.occurred_at >= {_T0}")
    if date_to:
        where.append(f"a.occurred_at < {_T1}")
    if cursor:
        (last,) = decode_cursor(cursor, 1)
        if not isinstance(last, int):
            raise invalid_cursor()
        where.append("a.id < :c_id")
        params["c_id"] = last
    rows = conn.execute(text(f"""
        SELECT a.id, a.occurred_at, a.device_id, a.action, a.entity_type, a.entity_id, a.old_values, a.new_values,
               {_USER_COLS}
          FROM app.audit_log a LEFT JOIN app.users u ON u.id = a.actor_user_id
         WHERE {' AND '.join(where)}
         ORDER BY a.id DESC LIMIT :n
    """), params).mappings().all()
    items = [AuditEntry(id=r["id"], occurred_at=r["occurred_at"], actor=_summary(r) if r["u_id"] else None,
                        device_id=r["device_id"], action=r["action"], entity_type=r["entity_type"],
                        entity_id=r["entity_id"], old_values=_clean(r["old_values"]),
                        new_values=_clean(r["new_values"])) for r in rows[:limit]]
    return AuditPage(items=items, next_cursor=encode_cursor([rows[limit - 1]["id"]]) if len(rows) > limit else None)


# --- worker activity -------------------------------------------------------------------------------
@router.get("/reports/worker-activity", response_model=WorkerActivity,
            summary="Surveys, visits, mobiles, new voters and voted marks per worker per day. Admin.")
def worker_activity(conn: Db, user: Admin, date_from: date, date_to: date,
                    user_id: uuid.UUID | None = None) -> WorkerActivity:
    _check_worker(conn, user, user_id)
    team, params = _team(user)
    params.update(_range(date_from, date_to, required=True), one=user_id)
    day = f"(%s AT TIME ZONE {_IST})::date"
    rows = conn.execute(text(f"""
        WITH w AS (SELECT u.id FROM app.users u WHERE {team} AND (CAST(:one AS uuid) IS NULL OR u.id = :one)),
        ev AS (
            SELECT a.actor_user_id AS uid, {day % 'a.occurred_at'} AS day,
                   count(DISTINCT a.entity_id) AS surveys,
                   count(DISTINCT a.entity_id) FILTER (WHERE a.new_values ->> 'mobile_1' IS NOT NULL
                                                          OR a.new_values ->> 'mobile_2' IS NOT NULL) AS mobiles,
                   0 AS visits, 0 AS new_voters, 0 AS voted
              FROM app.audit_log a
             WHERE a.entity_type = 'voter_surveys' AND a.action IN ('insert', 'update')
               AND a.occurred_at >= {_T0} AND a.occurred_at < {_T1} AND a.actor_user_id IN (SELECT id FROM w)
             GROUP BY 1, 2
            UNION ALL
            SELECT v.visited_by, {day % 'v.visited_at'}, 0, 0, count(*), 0, 0
              FROM app.visits v
             WHERE v.deleted_at IS NULL AND v.visited_at >= {_T0} AND v.visited_at < {_T1}
               AND v.visited_by IN (SELECT id FROM w)
             GROUP BY 1, 2
            UNION ALL
            SELECT n.created_by, {day % 'n.created_at'}, 0, 0, 0, count(*), 0
              FROM app.new_voters n
             WHERE n.deleted_at IS NULL AND n.created_at >= {_T0} AND n.created_at < {_T1}
               AND n.created_by IN (SELECT id FROM w)
             GROUP BY 1, 2
            UNION ALL
            SELECT t.marked_by, {day % 't.marked_at'}, 0, 0, 0, 0, count(*)
              FROM app.voter_turnout t
             WHERE t.is_voted AND t.marked_at >= {_T0} AND t.marked_at < {_T1}
               AND t.marked_by IN (SELECT id FROM w)
             GROUP BY 1, 2)
        SELECT ev.day, sum(ev.surveys) AS surveys, sum(ev.mobiles) AS mobiles, sum(ev.visits) AS visits,
               sum(ev.new_voters) AS new_voters, sum(ev.voted) AS voted, {_USER_COLS}
          FROM ev JOIN app.users u ON u.id = ev.uid
         GROUP BY ev.day, u.id
         ORDER BY ev.day, lower(u.full_name_en), u.id
    """), params).mappings().all()
    return WorkerActivity(date_from=date_from, date_to=date_to, rows=[
        WorkerDay(user=_summary(r), day=r["day"], surveys=r["surveys"], visits=r["visits"],
                  mobiles_collected=r["mobiles"], new_voters=r["new_voters"], voted_marks=r["voted"])
        for r in rows])


# --- worker locations ------------------------------------------------------------------------------
@router.get("/worker-locations", response_model=WorkerLocationPage,
            summary="Where surveys and visits were saved (no live tracking). Admin.")
def worker_locations(conn: Db, user: Admin, date_from: date, date_to: date, user_id: uuid.UUID | None = None,
                     limit: Limit = 50, cursor: Cursor = None) -> WorkerLocationPage:
    _check_worker(conn, user, user_id)
    team, params = _team(user)
    params.update(_range(date_from, date_to, required=True), one=user_id, n=limit + 1)
    after = ""
    if cursor:
        at, key = decode_cursor(cursor, 2)
        try:
            params.update(c_at=datetime.fromisoformat(str(at)), c_key=str(key))
        except ValueError:
            raise invalid_cursor() from None
        after = 'WHERE (x.at < :c_at OR (x.at = :c_at AND x.key COLLATE "C" < :c_key))'
    rows = conn.execute(text(f"""
        WITH w AS (SELECT u.id FROM app.users u WHERE {team} AND (CAST(:one AS uuid) IS NULL OR u.id = :one))
        SELECT x.*, {_USER_COLS} FROM (
            SELECT a.actor_user_id AS uid, 'survey' AS kind, CAST(a.entity_id AS uuid) AS voter_id,
                   CAST(a.new_values ->> 'lat' AS float8) AS lat, CAST(a.new_values ->> 'lng' AS float8) AS lng,
                   CAST(a.new_values ->> 'location_accuracy_m' AS float8) AS accuracy_m,
                   coalesce(CAST(a.new_values ->> 'location_captured_at' AS timestamptz), a.occurred_at) AS at,
                   's' || a.id AS key
              FROM app.audit_log a
             WHERE a.entity_type = 'voter_surveys' AND a.action IN ('insert', 'update')
               AND a.new_values ->> 'lat' IS NOT NULL AND a.new_values ->> 'lng' IS NOT NULL
               AND a.occurred_at >= {_T0} AND a.occurred_at < {_T1} AND a.actor_user_id IN (SELECT id FROM w)
            UNION ALL
            SELECT v.visited_by, 'visit', v.voter_id, CAST(v.lat AS float8), CAST(v.lng AS float8),
                   CAST(v.accuracy_m AS float8), v.visited_at, 'v' || v.id
              FROM app.visits v
             WHERE v.deleted_at IS NULL AND v.lat IS NOT NULL AND v.lng IS NOT NULL
               AND v.visited_at >= {_T0} AND v.visited_at < {_T1} AND v.visited_by IN (SELECT id FROM w)
        ) x JOIN app.users u ON u.id = x.uid
        {after}
        ORDER BY x.at DESC, x.key COLLATE "C" DESC LIMIT :n
    """), params).mappings().all()
    items = [WorkerLocation(user=_summary(r), kind=r["kind"], voter_id=r["voter_id"], lat=r["lat"], lng=r["lng"],
                            accuracy_m=r["accuracy_m"], at=r["at"]) for r in rows[:limit]]
    last = rows[limit - 1] if len(rows) > limit else None
    return WorkerLocationPage(items=items, next_cursor=encode_cursor([last["at"].isoformat(), last["key"]])
                              if last else None)
