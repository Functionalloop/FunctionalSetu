"""Data quality and mobile number sheets (plan 10.5): GET /data-quality/summary, /data-quality/duplicates,
POST /data-quality/duplicates/{id}/resolve, POST /mobile-imports, GET /mobile-imports/{id},
POST /mobile-imports/{id}/rows/{row_id}/resolve.

Data quality (supervisor and above) counts the live voters of the caller's area. A duplicate pair
(app/duplicates.py) is seen when both its voters are in the area. Deciding a pair: anyone who sees
it marks "same person" or "different people"; hiding one of the two (keep_voter_id) removes a voter
from the roll, which only a super admin may do (client, 12 Nov), so a lower role gets 403 for it and
the super admin finishes the "same person" pairs (resolve again with keep_voter_id).

Mobile sheets (admin and above; the workspace's feature_mobile_import switch): app/mobile_match.py.
A sheet is seen by the uploader's team (admin: own constituency's users; super admin: all) and is
matched against the uploader's area.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, File, UploadFile, status
from sqlalchemy import Connection, text

from ..deps import Db, Principal
from ..errors import ApiError
from ..mobile_match import KIND as MOBILE_JOB, normalise_mobile, recount, store_mobile
from ..paging import decode_cursor, encode_cursor, invalid_cursor
from ..roll_match import CSV_MIME, MAX_BYTES, XLSX_MIME, sniff
from ..schemas import Role, SyncVoter
from ..schemas_admin import FileKind
from ..schemas_roll import (DataQualitySummary, DuplicatePair, DuplicatePairPage, MobileImport, MobileImportPage,
                            MobileImportRow, MobileRowResolution, PairResolution)
from ..scope import Scope, UserScope, require_area
from ..stubs import Admin, Cursor, Limit, Supervisor
from ..sync_pull import VOTER_COLS
from ..worker import enqueue
from .files import store_file
from .roll_edits import hide_voter
from .voters import voter_in_scope

router = APIRouter(tags=["roll and data quality"])

PAIR_SOURCES = ("roll_flag", "fuzzy_match", "roll_update")
MAX_SHEET_ROWS_SHOWN = 500


# --- summary ---------------------------------------------------------------------------------------
@router.get("/data-quality/summary", response_model=DataQualitySummary,
            summary="Counts: no mobile, no date of birth, duplicates, repeated, shifted, doubtful dead. Supervisor.")
def data_quality_summary(conn: Db, user: Supervisor, scope: UserScope,
                         ward_id: uuid.UUID | None = None) -> DataQualitySummary:
    cond, params = scope.filter("v.geo_path")
    where = ["v.deleted_at IS NULL", cond]
    if ward_id is not None:
        require_area(conn, scope, ward_id)
        where.append("v.ward_id = :ward")
        params["ward"] = ward_id
    row = conn.execute(text(f"""
        WITH last_visit AS (SELECT DISTINCT ON (voter_id) voter_id, outcome FROM app.visits
                             WHERE deleted_at IS NULL ORDER BY voter_id, visited_at DESC, id DESC)
        SELECT count(*) AS voters,
               count(*) FILTER (WHERE s.mobile_1 IS NULL) AS no_mobile,
               count(*) FILTER (WHERE s.dob IS NULL) AS no_dob,
               count(*) FILTER (WHERE v.is_repeated_in_roll) AS repeated_in_roll,
               count(*) FILTER (WHERE s.has_new_address OR lv.outcome = 'shifted') AS shifted,
               count(*) FILTER (WHERE s.dead_marked AND s.dead_confirmed_at IS NULL) AS doubtful_dead
          FROM app.voters v
          LEFT JOIN app.voter_surveys s ON s.tenant_id = v.tenant_id AND s.voter_id = v.id
          LEFT JOIN last_visit lv ON lv.voter_id = v.id
         WHERE {' AND '.join(where)}"""), params).mappings().one()
    pcond, pparams = _pair_scope(scope)
    pwhere = [pcond, "p.status = 'unchecked'", "a.deleted_at IS NULL", "b.deleted_at IS NULL"]
    if ward_id is not None:
        pwhere.append("(a.ward_id = :ward OR b.ward_id = :ward)")
        pparams["ward"] = ward_id
    pairs = conn.execute(text(f"SELECT count(*) FROM {_PAIR_FROM} WHERE {' AND '.join(pwhere)}"), pparams).scalar_one()
    return DataQualitySummary(**row, possible_duplicates=pairs)


# --- duplicate pairs -------------------------------------------------------------------------------
_PAIR_FROM = """app.voter_duplicate_pairs p
    JOIN app.voters a ON a.tenant_id = p.tenant_id AND a.id = p.voter_a_id
    JOIN app.voters b ON b.tenant_id = p.tenant_id AND b.id = p.voter_b_id"""


def _pair_scope(scope: Scope) -> tuple[str, dict[str, Any]]:
    """Both voters in the caller's area."""
    ca, pa = scope.filter("a.geo_path")
    cb, pb = scope.filter("b.geo_path")   # same parameter names and values as for a
    return f"({ca}) AND ({cb})", {**pa, **pb}


def _pairs(conn: Connection, rows: list[Any]) -> list[DuplicatePair]:
    ids = {r["voter_a_id"] for r in rows} | {r["voter_b_id"] for r in rows}
    voters = {v["id"]: SyncVoter(**v) for v in conn.execute(
        text(f"SELECT {VOTER_COLS} FROM app.voters v WHERE v.id = ANY(:ids)"), {"ids": list(ids)}).mappings()}
    return [DuplicatePair(id=r["id"], voter_a=voters[r["voter_a_id"]], voter_b=voters[r["voter_b_id"]],
                          source=r["source"], similarity=r["similarity"], status=r["status"]) for r in rows]


_PAIR_COLS = ("p.id, p.voter_a_id, p.voter_b_id, p.source, p.similarity::float AS similarity, "
              "p.status::text AS status, p.created_at")


@router.get("/data-quality/duplicates", response_model=DuplicatePairPage,
            summary="Possible duplicate and repeated pairs in the user's area. Supervisor.")
def duplicate_pairs(conn: Db, user: Supervisor, scope: UserScope, unchecked_only: bool = True,
                    source: str | None = None, limit: Limit = 50, cursor: Cursor = None) -> DuplicatePairPage:
    cond, params = _pair_scope(scope)
    where = [cond]
    if unchecked_only:
        where += ["p.status = 'unchecked'", "a.deleted_at IS NULL", "b.deleted_at IS NULL"]
    if source is not None:
        if source not in PAIR_SOURCES:
            raise ApiError(422, "validation_error", f"source: one of {', '.join(PAIR_SOURCES)}.")
        where.append("p.source = :source")
        params["source"] = source
    if cursor:
        at, i = decode_cursor(cursor, 2)
        try:
            params.update(c_at=datetime.fromisoformat(str(at)), c_id=uuid.UUID(str(i)))
        except ValueError:
            raise invalid_cursor() from None
        where.append("(p.created_at, p.id) > (:c_at, :c_id)")
    rows = conn.execute(text(f"""SELECT {_PAIR_COLS} FROM {_PAIR_FROM} WHERE {' AND '.join(where)}
                                 ORDER BY p.created_at, p.id LIMIT :n"""), {**params, "n": limit + 1}).mappings().all()
    page = rows[:limit]
    last = rows[limit - 1] if len(rows) > limit else None
    return DuplicatePairPage(items=_pairs(conn, list(page)),
                             next_cursor=encode_cursor([last["created_at"].isoformat(), str(last["id"])]) if last else None)


@router.post("/data-quality/duplicates/{pair_id}/resolve", response_model=DuplicatePair,
             summary="Same person or different people; a super admin may also hide one (keep_voter_id). Supervisor.")
def resolve_duplicate(pair_id: uuid.UUID, body: PairResolution, conn: Db, user: Supervisor,
                      scope: UserScope) -> DuplicatePair:
    cond, params = _pair_scope(scope)
    pair = conn.execute(text(f"SELECT {_PAIR_COLS} FROM {_PAIR_FROM} WHERE p.id = :id AND {cond} FOR UPDATE OF p"),
                        {**params, "id": pair_id}).mappings().first()
    if pair is None:
        raise ApiError(404, "not_found", "Pair not found.")
    keep = body.keep_voter_id
    if keep is not None:
        if not body.same_person:
            raise ApiError(422, "validation_error", "keep_voter_id: only with same_person.")
        if user.role != Role.super_admin:
            raise ApiError(403, "forbidden_role", "Only a super admin can hide a voter. Mark the pair as the same "
                                                  "person without keep_voter_id; a super admin hides one later.")
        if keep not in (pair["voter_a_id"], pair["voter_b_id"]):
            raise ApiError(422, "validation_error", "keep_voter_id: one of the pair's two voters.")
        other = pair["voter_b_id"] if keep == pair["voter_a_id"] else pair["voter_a_id"]
        hide_voter(conn, user, other, "duplicate", f"duplicate pair {pair_id}")
    conn.execute(text("""UPDATE app.voter_duplicate_pairs
                            SET status = CAST(:st AS app.pair_status), reviewed_by = :by, reviewed_at = now()
                          WHERE id = :id"""),
                 {"id": pair_id, "by": user.user_id, "st": "same_person" if body.same_person else "different_people"})
    row = conn.execute(text(f"SELECT {_PAIR_COLS} FROM app.voter_duplicate_pairs p WHERE p.id = :id"),
                       {"id": pair_id}).mappings().one()
    return _pairs(conn, [row])[0]


# --- mobile number sheets ----------------------------------------------------------------------------
def _sheet_team(user: Principal) -> tuple[str, dict[str, Any]]:
    """Sheets the caller sees: uploaded by a user of their constituency (super admin: all)."""
    return "(:is_super OR u.local_body_id = :lb)", {"is_super": user.role == Role.super_admin,
                                                     "lb": user.local_body_id}


_SHEET_SELECT = """
    SELECT b.id, b.status::text AS status, b.matched_count, b.review_count, b.not_found_count, b.error,
           b.created_at, b.finished_at,
           (SELECT j.status::text FROM app.jobs j WHERE j.ref_id = b.id AND j.kind = :kind
             ORDER BY j.created_at DESC LIMIT 1) AS job_status
      FROM app.mobile_import_batches b JOIN app.users u ON u.tenant_id = b.tenant_id AND u.id = b.created_by"""


def _to_sheet(b: Any, rows: list[MobileImportRow]) -> MobileImport:
    st = "running" if b["status"] == "queued" and b["job_status"] == "running" else b["status"]
    return MobileImport(**{k: b[k] for k in ("id", "matched_count", "review_count", "not_found_count", "error",
                                             "created_at", "finished_at")}, status=st, rows=rows)


def get_sheet(conn: Connection, user: Principal, batch_id: uuid.UUID, lock: bool = False) -> MobileImport:
    cond, params = _sheet_team(user)
    b = conn.execute(text(f"{_SHEET_SELECT} WHERE b.id = :id AND {cond} {'FOR UPDATE OF b' if lock else ''}"),
                     {**params, "id": batch_id, "kind": MOBILE_JOB}).mappings().first()
    if b is None:
        raise ApiError(404, "not_found", "Mobile number sheet not found.")
    rows = conn.execute(text("""
        SELECT id, row_no, name, mobile, address_text, status::text AS status, matched_voter_id, candidate_voter_ids
          FROM app.mobile_import_rows WHERE batch_id = :id
         ORDER BY CASE status WHEN 'needs_review' THEN 0 WHEN 'not_found' THEN 1 WHEN 'matched' THEN 2 ELSE 3 END,
                  row_no
         LIMIT :n"""), {"id": batch_id, "n": MAX_SHEET_ROWS_SHOWN}).mappings().all()
    return _to_sheet(b, [MobileImportRow(**r) for r in rows])


@router.get("/mobile-imports", response_model=MobileImportPage,
            summary="Mobile number sheets of the caller's team, newest first, without rows. Admin.")
def list_mobile_imports(conn: Db, user: Admin, limit: Limit = 50, cursor: Cursor = None) -> MobileImportPage:
    cond, params = _sheet_team(user)
    where = [cond]
    if cursor:
        at, i = decode_cursor(cursor, 2)
        try:
            params.update(c_at=datetime.fromisoformat(str(at)), c_id=uuid.UUID(str(i)))
        except ValueError:
            raise invalid_cursor() from None
        where.append("(b.created_at, b.id) < (:c_at, :c_id)")
    found = conn.execute(text(f"""{_SHEET_SELECT} WHERE {' AND '.join(where)}
                                  ORDER BY b.created_at DESC, b.id DESC LIMIT :n"""),
                         {**params, "kind": MOBILE_JOB, "n": limit + 1}).mappings().all()
    last = found[limit - 1] if len(found) > limit else None
    return MobileImportPage(items=[_to_sheet(b, []) for b in found[:limit]],
                            next_cursor=encode_cursor([last["created_at"].isoformat(), str(last["id"])]) if last else None)


@router.post("/mobile-imports", response_model=MobileImport, status_code=status.HTTP_202_ACCEPTED,
             summary="Upload a sheet of names and mobiles (CSV or Excel); matching runs as a job. Admin.")
def start_mobile_import(conn: Db, user: Admin, file: Annotated[UploadFile, File()]) -> MobileImport:
    if not conn.execute(text("SELECT coalesce((SELECT feature_mobile_import FROM app.tenant_settings), true)")).scalar():
        raise ApiError(403, "feature_off", "Mobile number sheets are switched off for this workspace.")
    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ApiError(422, "file_too_large", f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    kind = sniff(data[:1024]) if data else None
    if kind is None:
        raise ApiError(422, "unsupported_file", "Only CSV or Excel (.xlsx) sheets.")
    stored = store_file(conn, user, FileKind.mobile_import, data, file.filename, XLSX_MIME if kind == "xlsx" else CSV_MIME)
    bid = conn.execute(text("""
        INSERT INTO app.mobile_import_batches (tenant_id, source, file_id, created_by)
        VALUES (app.current_tenant_id(), 'file', :file, :by) RETURNING id"""),
                       {"file": stored["id"], "by": user.user_id}).scalar_one()
    # matched against the uploader's area: own constituency, or the whole workspace for a super admin
    enqueue(conn, MOBILE_JOB, bid, {"local_body_id": None if user.role == Role.super_admin
                                    else str(user.local_body_id)})
    return get_sheet(conn, user, bid)


@router.get("/mobile-imports/{import_id}", response_model=MobileImport,
            summary="A sheet's progress, counts and rows to review. Admin.")
def get_mobile_import(import_id: uuid.UUID, conn: Db, user: Admin) -> MobileImport:
    return get_sheet(conn, user, import_id)


@router.post("/mobile-imports/{import_id}/rows/{row_id}/resolve", response_model=MobileImport,
             summary="Give a row under review its voter, or skip it. Admin. (Plan gap table proposal.)")
def resolve_mobile_row(import_id: uuid.UUID, row_id: int, body: MobileRowResolution, conn: Db,
                       user: Admin, scope: UserScope) -> MobileImport:
    get_sheet(conn, user, import_id, lock=True)
    row = conn.execute(text("""SELECT mobile, status::text AS status FROM app.mobile_import_rows
                                WHERE id = :id AND batch_id = :b FOR UPDATE"""),
                       {"id": row_id, "b": import_id}).mappings().first()
    if row is None:
        raise ApiError(404, "not_found", "Row not found.")
    if row["status"] not in ("needs_review", "not_found"):
        raise ApiError(409, "row_resolved", "This row is already matched or skipped.")
    mobile = normalise_mobile(row["mobile"])
    if body.voter_id is not None:
        voter_in_scope(conn, scope, body.voter_id)
        if mobile is None:   # rows with a bad number are skipped when read; never here
            raise ApiError(422, "validation_error", "This row has no valid mobile number.")
        store_mobile(conn, user.user_id, body.voter_id, mobile, replace=True)
    conn.execute(text("""UPDATE app.mobile_import_rows
                            SET status = CAST(:st AS app.mobile_match_status), matched_voter_id = :v,
                                reviewed_by = :by, reviewed_at = now()
                          WHERE id = :id"""),
                 {"id": row_id, "v": body.voter_id, "by": user.user_id,
                  "st": "matched" if body.voter_id else "skipped"})
    recount(conn, import_id)
    return get_sheet(conn, user, import_id)
