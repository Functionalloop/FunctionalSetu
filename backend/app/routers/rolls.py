"""Roll update and data quality (plan step 10): roll import and review, one-voter corrections,
data quality, duplicates, spelling fixes, mobile number sheets.

Contract only (4.10): every route answers 501 until its task is built. See app/stubs.py.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from ..deps import Db
from ..schemas import ListType, VoterDetail
from ..schemas_roll import (Accept, DataQualitySummary, DuplicatePair, DuplicatePairPage, MatchStatus, MobileImport,
                            MobileRowResolution, NameFix, NameFixPage, PairResolution, RemoveRestore, RollEditPage,
                            RollImport, RollImportPage, RollImportRow, RollImportRowPage, RollPatch, RowResolution,
                            VoterAdd)
from ..stubs import Admin, Cursor, Limit, Supervisor, not_built

router = APIRouter(tags=["roll and data quality"])


# --- roll import (10.2, 10.3) ----------------------------------------------------------------
@router.post("/rolls/imports", response_model=RollImport, status_code=status.HTTP_202_ACCEPTED,
             summary="Upload a roll file (CSV or Excel; text PDF from 12.1). Starts a job; poll the import. Admin.")
def start_roll_import(conn: Db, user: Admin, file: Annotated[UploadFile, File()],
                      local_body_id: Annotated[uuid.UUID, Form()], list_type: Annotated[ListType, Form()],
                      title: Annotated[str, Form(min_length=1, max_length=200)],
                      published_on: Annotated[date | None, Form()] = None) -> RollImport:
    not_built("10.2")


@router.get("/rolls/imports", response_model=RollImportPage, summary="Roll imports, newest first. Admin.")
def list_roll_imports(conn: Db, user: Admin, limit: Limit = 50, cursor: Cursor = None) -> RollImportPage:
    not_built("10.2")


@router.get("/rolls/imports/{import_id}", response_model=RollImport, summary="One import's progress and counts. Admin.")
def get_roll_import(import_id: uuid.UUID, conn: Db, user: Admin) -> RollImport:
    not_built("10.2")


@router.get("/rolls/imports/{import_id}/rows", response_model=RollImportRowPage,
            summary="Rows of an import by match status. Admin.")
def roll_import_rows(import_id: uuid.UUID, conn: Db, user: Admin, match_status: MatchStatus | None = None,
                     pending_only: bool = False, limit: Limit = 50, cursor: Cursor = None) -> RollImportRowPage:
    not_built("10.2")


@router.post("/rolls/imports/{import_id}/rows/{row_id}/resolve", response_model=RollImportRow,
             summary="Accept or reject one uncertain match. Admin.")
def resolve_roll_row(import_id: uuid.UUID, row_id: int, body: RowResolution, conn: Db, user: Admin) -> RollImportRow:
    not_built("10.3")


@router.post("/rolls/imports/{import_id}/apply", response_model=RollImport,
             summary="Apply the reviewed roll. Surveys stay linked; missing voters become 'not in current roll'. Admin.")
def apply_roll_import(import_id: uuid.UUID, conn: Db, user: Admin) -> RollImport:
    not_built("10.3")


@router.post("/rolls/imports/{import_id}/discard", response_model=RollImport, summary="Throw an import away. Admin.")
def discard_roll_import(import_id: uuid.UUID, conn: Db, user: Admin) -> RollImport:
    not_built("10.3")


# --- one-voter corrections (10.4) --------------------------------------------------------------
@router.post("/voters", response_model=VoterDetail, status_code=status.HTTP_201_CREATED,
             summary="Add one voter to the roll by hand, with reason and reference. Admin.")
def add_voter(body: VoterAdd, conn: Db, user: Admin) -> VoterDetail:
    not_built("10.4")


@router.patch("/voters/{voter_id}/roll", response_model=VoterDetail,
              summary="Correct one roll record, with reason and reference. Admin.")
def correct_voter(voter_id: uuid.UUID, body: RollPatch, conn: Db, user: Admin) -> VoterDetail:
    not_built("10.4")


@router.post("/voters/{voter_id}/remove", response_model=VoterDetail,
             summary="Hide one voter (survey work is kept), with reason. Admin.")
def remove_voter(voter_id: uuid.UUID, body: RemoveRestore, conn: Db, user: Admin) -> VoterDetail:
    not_built("10.4")


@router.post("/voters/{voter_id}/restore", response_model=VoterDetail, summary="Bring back a hidden voter. Admin.")
def restore_voter(voter_id: uuid.UUID, body: RemoveRestore, conn: Db, user: Admin) -> VoterDetail:
    not_built("10.4")


@router.get("/voters/{voter_id}/roll-edits", response_model=RollEditPage,
            summary="Roll corrections made to this voter. Admin.")
def voter_roll_edits(voter_id: uuid.UUID, conn: Db, user: Admin, limit: Limit = 50,
                     cursor: Cursor = None) -> RollEditPage:
    not_built("10.4")


# --- data quality (10.5) ------------------------------------------------------------------------
@router.get("/data-quality/summary", response_model=DataQualitySummary,
            summary="Counts: no mobile, no date of birth, duplicates, repeated, shifted, doubtful dead. Supervisor.")
def data_quality_summary(conn: Db, user: Supervisor, ward_id: uuid.UUID | None = None) -> DataQualitySummary:
    not_built("10.5")


@router.get("/data-quality/duplicates", response_model=DuplicatePairPage,
            summary="Possible duplicate and repeated pairs in the user's area. Supervisor.")
def duplicate_pairs(conn: Db, user: Supervisor, unchecked_only: bool = True, limit: Limit = 50,
                    cursor: Cursor = None) -> DuplicatePairPage:
    not_built("10.5")


@router.post("/data-quality/duplicates/{pair_id}/resolve", response_model=DuplicatePair,
             summary="Same person (hide one) or different people. Supervisor.")
def resolve_duplicate(pair_id: uuid.UUID, body: PairResolution, conn: Db, user: Supervisor) -> DuplicatePair:
    not_built("10.5")


@router.get("/name-fixes", response_model=NameFixPage, summary="Spelling fixes waiting for review. Admin.")
def list_name_fixes(conn: Db, user: Admin,
                    status_filter: Annotated[str | None, Query(alias="status", pattern="^(pending|accepted|rejected)$")] = "pending",
                    limit: Limit = 50, cursor: Cursor = None) -> NameFixPage:
    not_built("10.5")


@router.post("/name-fixes/{fix_id}/resolve", response_model=NameFix,
             summary="Accept (writes the English name) or reject a spelling fix. Admin.")
def resolve_name_fix(fix_id: uuid.UUID, body: Accept, conn: Db, user: Admin) -> NameFix:
    not_built("10.5")


# --- mobile number sheets (10.5) ---------------------------------------------------------------
@router.post("/mobile-imports", response_model=MobileImport, status_code=status.HTTP_202_ACCEPTED,
             summary="Upload a sheet of names and mobiles (CSV or Excel); matching runs as a job. Admin.")
def start_mobile_import(conn: Db, user: Admin, file: Annotated[UploadFile, File()]) -> MobileImport:
    not_built("10.5")


@router.get("/mobile-imports/{import_id}", response_model=MobileImport,
            summary="A sheet's progress, counts and rows to review. Admin.")
def get_mobile_import(import_id: uuid.UUID, conn: Db, user: Admin) -> MobileImport:
    not_built("10.5")


@router.post("/mobile-imports/{import_id}/rows/{row_id}/resolve", response_model=MobileImport,
             summary="Give a row under review its voter, or skip it. Admin. (Plan gap table proposal.)")
def resolve_mobile_row(import_id: uuid.UUID, row_id: int, body: MobileRowResolution, conn: Db,
                       user: Admin) -> MobileImport:
    not_built("10.5")
