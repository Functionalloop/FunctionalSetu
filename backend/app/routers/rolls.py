"""Matching Engine (plan 10.2, 10.3): roll import, review, apply, discard. (Spelling fixes were removed
by the client, 12 Nov.)

Official roll data is changed by the super admin only (client, 12 Nov): an admin can read
imports but every write answers 403.

Roll import (10.2): upload -> app.files + roll_versions (uploaded) + a "roll_import" job; the worker
reads and matches the file (app/roll_match.py) and leaves the import in "review". An import is seen
through its constituency: a super admin sees every one, an admin only their own (else 404).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile, status
from sqlalchemy import Connection, text

from .. import roll_apply
from ..deps import Db
from ..errors import ApiError
from ..paging import decode_cursor, encode_cursor, invalid_cursor
from ..roll_match import CSV_MIME, KIND as ROLL_JOB, MAX_BYTES, XLSX_MIME, sniff
from ..schemas import ListType, UserSummary
from ..schemas_admin import FileKind
from ..schemas_roll import (MatchStatus, RollImport, RollImportPage, RollImportRow, RollImportRowPage,
                            RowResolution)
from ..scope import Scope, UserScope, require_area
from ..stubs import Admin, Cursor, Limit, SuperAdmin
from ..worker import enqueue
from .files import store_file

router = APIRouter(tags=["roll and data quality"])


# --- roll import (10.2, 10.3) ----------------------------------------------------------------
COUNT_KEYS = ("matched", "uncertain", "possible_duplicate", "absent_from_current_roll", "new", "unreadable",
              "rows", "to_review", "reviewed")
APPLIED_KEYS = ("updated", "unchanged", "added", "marked_absent", "deleted_in_roll", "skipped")
OPEN_STATUSES = ("uploaded", "parsing", "review")

_IMPORT_SELECT = """
    SELECT rv.id, rv.local_body_id, rv.list_type::text AS list_type, rv.title, rv.published_on,
           rv.status::text AS status, rv.applied_at, rv.created_at, rv.stats,
           u.id AS u_id, u.username, u.full_name_en, u.full_name_mr, u.role::text AS u_role,
           j.status::text AS job_status, j.error AS job_error
      FROM app.roll_versions rv
      JOIN app.geo_units g ON g.id = rv.local_body_id
      LEFT JOIN app.users u ON u.id = rv.imported_by
      LEFT JOIN LATERAL (SELECT status, error FROM app.jobs
                          WHERE ref_id = rv.id AND kind = :job_kind
                          ORDER BY created_at DESC LIMIT 1) j ON TRUE
"""


def _counts(conn: Connection, ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    out: dict[uuid.UUID, dict[str, int]] = defaultdict(lambda: dict.fromkeys(COUNT_KEYS, 0))
    if not ids:
        return out
    rows = conn.execute(text("""
        SELECT roll_version_id AS id, coalesce(match_status::text, 'unreadable') AS st,
               review_status::text AS review, reviewed_by IS NOT NULL AS by_person, count(*) AS n
          FROM app.roll_import_rows WHERE roll_version_id = ANY(:ids)
         GROUP BY 1, 2, 3, 4"""), {"ids": ids}).mappings().all()
    for r in rows:
        c = out[r["id"]]
        r = {**r, "pending": r["review"] == "pending"}
        if r["st"] == "absent_from_current_roll" and r["review"] == "rejected":
            continue   # a voter a reviewed row now holds: not absent any more
        c[r["st"]] += r["n"]
        if r["st"] != "absent_from_current_roll":
            c["rows"] += r["n"]
        c["to_review"] += r["n"] if r["pending"] else 0
        c["reviewed"] += r["n"] if r["by_person"] else 0
    return out


def _to_import(r, counts: dict[str, int]) -> RollImport:
    st = r["status"]
    if st == "uploaded" and r["job_status"] == "running":
        st = "parsing"
    by = (UserSummary(id=r["u_id"], username=r["username"], full_name_en=r["full_name_en"],
                      full_name_mr=r["full_name_mr"], role=r["u_role"]) if r["u_id"] else None)
    if st == "applied":   # what apply did (10.3)
        counts = {**counts, **{k: int(r["stats"].get(k, 0)) for k in APPLIED_KEYS}}
    return RollImport(id=r["id"], local_body_id=r["local_body_id"], list_type=r["list_type"], title=r["title"],
                      published_on=r["published_on"], status=st, counts=counts,
                      error=r["job_error"] if r["status"] == "failed" else None, imported_by=by,
                      applied_at=r["applied_at"], created_at=r["created_at"])


def get_import(conn: Connection, scope: Scope, import_id: uuid.UUID) -> RollImport:
    """The import, if its constituency is in the caller's area; else 404."""
    cond, params = scope.filter("g.path")
    r = conn.execute(text(f"{_IMPORT_SELECT} WHERE rv.id = :id AND {cond}"),
                     {**params, "id": import_id, "job_kind": ROLL_JOB}).mappings().first()
    if r is None:
        raise ApiError(404, "not_found", "Roll import not found.")
    return _to_import(r, _counts(conn, [r["id"]])[r["id"]])


@router.post("/rolls/imports", response_model=RollImport, status_code=status.HTTP_202_ACCEPTED,
             summary="Upload a roll file (CSV or Excel; scanned PDF from 13.7). Starts a job; poll the import. Super admin.")
def start_roll_import(conn: Db, user: SuperAdmin, scope: UserScope, file: Annotated[UploadFile, File()],
                      local_body_id: Annotated[uuid.UUID, Form()], list_type: Annotated[ListType, Form()],
                      title: Annotated[str, Form(min_length=1, max_length=200)],
                      published_on: Annotated[date | None, Form()] = None) -> RollImport:
    require_area(conn, scope, local_body_id)
    level = conn.execute(text("SELECT level::text FROM app.geo_units WHERE id = :id"), {"id": local_body_id}).scalar()
    if level != "local_body":
        raise ApiError(422, "validation_error", "Choose a constituency.")
    title = title.strip()
    if not title:
        raise ApiError(422, "validation_error", "Give the import a title.")
    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ApiError(422, "file_too_large", f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    kind = sniff(data[:1024]) if data else None
    if kind is None:
        raise ApiError(422, "unsupported_file", "Only CSV or Excel (.xlsx) roll files.")

    # one open import per constituency: two reviews of one roll at once would fight on apply
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('roll_import:' || :lb, 0))"),
                 {"lb": str(local_body_id)})
    busy = conn.execute(text("""SELECT 1 FROM app.roll_versions WHERE local_body_id = :lb
                                 AND status = ANY(CAST(:open AS app.roll_import_status[]))"""),
                        {"lb": local_body_id, "open": list(OPEN_STATUSES)}).first()
    if busy:
        raise ApiError(409, "import_in_progress",
                       "This constituency has an import that is not applied or discarded yet. Finish that one first.")

    stored = store_file(conn, user, FileKind.roll_import, data, file.filename, XLSX_MIME if kind == "xlsx" else CSV_MIME)
    rv = conn.execute(text("""
        INSERT INTO app.roll_versions (tenant_id, local_body_id, list_type, title, published_on, source_file_id,
                                       imported_by)
        VALUES (:tenant, :lb, CAST(:lt AS app.list_type), :title, :pub, :file, :by)
        RETURNING id"""), {"tenant": user.tenant_id, "lb": local_body_id, "lt": list_type.value, "title": title,
                           "pub": published_on, "file": stored["id"], "by": user.user_id}).scalar_one()
    enqueue(conn, ROLL_JOB, rv)
    return get_import(conn, scope, rv)


@router.get("/rolls/imports", response_model=RollImportPage, summary="Roll imports, newest first. Admin.")
def list_roll_imports(conn: Db, user: Admin, scope: UserScope, limit: Limit = 50,
                      cursor: Cursor = None) -> RollImportPage:
    cond, params = scope.filter("g.path")
    where = [cond]
    if cursor:
        at, i = decode_cursor(cursor, 2)
        try:
            params.update(c_at=datetime.fromisoformat(str(at)), c_id=uuid.UUID(str(i)))
        except ValueError:
            raise invalid_cursor() from None
        where.append("(rv.created_at, rv.id) < (:c_at, :c_id)")
    rows = conn.execute(text(f"""{_IMPORT_SELECT} WHERE {' AND '.join(where)}
                                 ORDER BY rv.created_at DESC, rv.id DESC LIMIT :n"""),
                        {**params, "n": limit + 1, "job_kind": ROLL_JOB}).mappings().all()
    page = rows[:limit]
    counts = _counts(conn, [r["id"] for r in page])
    last = rows[limit - 1] if len(rows) > limit else None
    return RollImportPage(items=[_to_import(r, counts[r["id"]]) for r in page],
                          next_cursor=encode_cursor([last["created_at"].isoformat(), str(last["id"])]) if last else None)


@router.get("/rolls/imports/{import_id}", response_model=RollImport, summary="One import's progress and counts. Admin.")
def get_roll_import(import_id: uuid.UUID, conn: Db, user: Admin, scope: UserScope) -> RollImport:
    return get_import(conn, scope, import_id)


@router.get("/rolls/imports/{import_id}/rows", response_model=RollImportRowPage,
            summary="Rows of an import by match status. Admin.")
def roll_import_rows(import_id: uuid.UUID, conn: Db, user: Admin, scope: UserScope,
                     match_status: MatchStatus | None = None, pending_only: bool = False, limit: Limit = 50,
                     cursor: Cursor = None) -> RollImportRowPage:
    get_import(conn, scope, import_id)
    where, params = ["r.roll_version_id = :id"], {"id": import_id}
    if match_status is not None:
        where.append("r.match_status = CAST(:ms AS app.match_status)")
        params["ms"] = match_status.value
    if pending_only:
        where.append("r.review_status = 'pending'")
    if cursor:
        (after,) = decode_cursor(cursor, 1)
        if not isinstance(after, int):
            raise invalid_cursor()
        where.append("r.row_no > :after")
        params["after"] = after
    rows = conn.execute(text(f"""{_ROW_SELECT} WHERE {' AND '.join(where)}
                                 ORDER BY r.row_no LIMIT :n"""), {**params, "n": limit + 1}).mappings().all()
    items = [RollImportRow(**r) for r in rows[:limit]]
    return RollImportRowPage(items=items, next_cursor=encode_cursor([items[-1].row_no]) if len(rows) > limit else None)


_ROW_SELECT = """
    SELECT r.id, r.row_no, r.part_no, r.serial_no, r.epic_no, r.first_name_en, r.last_name_en, r.first_name_mr,
           r.last_name_mr, r.gender::text AS gender, r.age, r.house_no, r.match_status::text AS match_status,
           r.matched_voter_id, r.similarity::float AS similarity, r.match_notes,
           r.review_status::text AS review_status
      FROM app.roll_import_rows r
"""


@router.post("/rolls/imports/{import_id}/rows/{row_id}/resolve", response_model=RollImportRow,
             summary="Accept or reject one uncertain match, or give a row its voter. Super admin.")
def resolve_roll_row(import_id: uuid.UUID, row_id: int, body: RowResolution, conn: Db, user: SuperAdmin,
                     scope: UserScope) -> RollImportRow:
    get_import(conn, scope, import_id)
    rv = roll_apply.lock_import(conn, import_id)
    roll_apply.resolve_row(conn, user, rv, row_id, body.accept, body.voter_id)
    return RollImportRow(**conn.execute(text(f"{_ROW_SELECT} WHERE r.id = :id"), {"id": row_id}).mappings().one())


@router.post("/rolls/imports/{import_id}/apply", response_model=RollImport,
             summary="Apply the reviewed roll. Surveys stay linked; missing voters become 'not in current roll'. Super admin.")
def apply_roll_import(import_id: uuid.UUID, conn: Db, user: SuperAdmin, scope: UserScope) -> RollImport:
    get_import(conn, scope, import_id)
    roll_apply.apply_import(conn, user, roll_apply.lock_import(conn, import_id))
    return get_import(conn, scope, import_id)


@router.post("/rolls/imports/{import_id}/discard", response_model=RollImport,
             summary="Throw an import away (not an applied one). Super admin.")
def discard_roll_import(import_id: uuid.UUID, conn: Db, user: SuperAdmin, scope: UserScope) -> RollImport:
    get_import(conn, scope, import_id)
    roll_apply.discard_import(conn, roll_apply.lock_import(conn, import_id))
    return get_import(conn, scope, import_id)


# One-voter corrections (10.4): routers/roll_edits.py. Data quality and mobile sheets (10.5): routers/data_quality.py.
