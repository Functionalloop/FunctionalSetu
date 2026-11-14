"""Admin (plan step 9): users, assignments, constituencies, election settings, lists, files, team and logs.

Contract only (4.10): every route answers 501 until its task is built. See app/stubs.py.
`/masters/{list}` in the API document is one explicit route per list, because each list has its
own shape and key (castes/professions/colour tags by id, custom fields by field key, templates by kind).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status

from ..deps import Db, ReadyUser
from ..schemas import ColorTag, CustomFieldLabel, NamedListEntry
from ..schemas_admin import (AnnouncementIn, AuditPage, ColorTagIn, Constituency, ConstituencyIn,
                             ConstituencyPatch, CustomFieldKey, CustomFieldLabelIn, ElectionSettings,
                             ElectionSettingsIn, FileKind, MessageTemplate, MessageTemplateIn, NamedEntryIn,
                             ProblemReportPage, StoredFile, TemplateKind, WorkerActivity, WorkerLocationPage)
from ..schemas_field import Announcement
from ..stubs import Admin, Cursor, Limit, SuperAdmin, not_built

router = APIRouter(tags=["admin"])


# Users (9.1) and assignments (9.2) are in users.py.
# --- constituencies (9.3) -------------------------------------------------------------------
@router.get("/constituencies", response_model=list[Constituency], summary="Constituencies in the workspace. Super admin.")
def list_constituencies(conn: Db, user: SuperAdmin) -> list[Constituency]:
    not_built("9.3")


@router.post("/constituencies", response_model=Constituency, status_code=status.HTTP_201_CREATED,
             summary="Add a constituency (limit 5 per workspace). Super admin.")
def create_constituency(body: ConstituencyIn, conn: Db, user: SuperAdmin) -> Constituency:
    not_built("9.3")


@router.patch("/constituencies/{constituency_id}", response_model=Constituency,
              summary="Rename or switch off a constituency. Super admin.")
def update_constituency(constituency_id: uuid.UUID, body: ConstituencyPatch, conn: Db,
                        user: SuperAdmin) -> Constituency:
    not_built("9.3")


# --- election settings (9.4) ---------------------------------------------------------------
@router.get("/settings/election", response_model=ElectionSettings,
            summary="Election, candidate, slip text and feature switches (candidate shown even in code of conduct). Admin.")
def get_election_settings(conn: Db, user: Admin) -> ElectionSettings:
    not_built("9.4")


@router.put("/settings/election", response_model=ElectionSettings, summary="Save the election settings. Admin.")
def set_election_settings(body: ElectionSettingsIn, conn: Db, user: Admin) -> ElectionSettings:
    not_built("9.4")


# --- lists and labels (9.4) -----------------------------------------------------------------
@router.get("/masters/castes", response_model=list[NamedListEntry], summary="Castes, inactive included. Admin.")
def list_castes(conn: Db, user: Admin) -> list[NamedListEntry]:
    not_built("9.4")


@router.post("/masters/castes", response_model=NamedListEntry, status_code=status.HTTP_201_CREATED,
             summary="Add a caste. Admin.")
def add_caste(body: NamedEntryIn, conn: Db, user: Admin) -> NamedListEntry:
    not_built("9.4")


@router.patch("/masters/castes/{entry_id}", response_model=NamedListEntry,
              summary="Rename, reorder or switch off a caste (never deleted: old surveys keep it). Admin.")
def update_caste(entry_id: uuid.UUID, body: NamedEntryIn, conn: Db, user: Admin) -> NamedListEntry:
    not_built("9.4")


@router.get("/masters/professions", response_model=list[NamedListEntry], summary="Professions. Admin.")
def list_professions(conn: Db, user: Admin) -> list[NamedListEntry]:
    not_built("9.4")


@router.post("/masters/professions", response_model=NamedListEntry, status_code=status.HTTP_201_CREATED,
             summary="Add a profession. Admin.")
def add_profession(body: NamedEntryIn, conn: Db, user: Admin) -> NamedListEntry:
    not_built("9.4")


@router.patch("/masters/professions/{entry_id}", response_model=NamedListEntry,
              summary="Rename, reorder or switch off a profession. Admin.")
def update_profession(entry_id: uuid.UUID, body: NamedEntryIn, conn: Db, user: Admin) -> NamedListEntry:
    not_built("9.4")


@router.get("/masters/color-tags", response_model=list[ColorTag], summary="Colour tags. Admin.")
def list_color_tags(conn: Db, user: Admin) -> list[ColorTag]:
    not_built("9.4")


@router.post("/masters/color-tags", response_model=ColorTag, status_code=status.HTTP_201_CREATED,
             summary="Add a colour tag. Admin.")
def add_color_tag(body: ColorTagIn, conn: Db, user: Admin) -> ColorTag:
    not_built("9.4")


@router.patch("/masters/color-tags/{entry_id}", response_model=ColorTag,
              summary="Change a colour tag's label, colour, order or switch it off. Admin.")
def update_color_tag(entry_id: uuid.UUID, body: ColorTagIn, conn: Db, user: Admin) -> ColorTag:
    not_built("9.4")


@router.get("/masters/custom-fields", response_model=list[CustomFieldLabel],
            summary="Labels of the survey's custom fields (Extra Check 1-2, Extra Info 1-5). Admin.")
def list_custom_fields(conn: Db, user: Admin) -> list[CustomFieldLabel]:
    not_built("9.4")


@router.patch("/masters/custom-fields/{field_key}", response_model=CustomFieldLabel,
              summary="Name, enable or disable one custom field. Admin.")
def update_custom_field(field_key: CustomFieldKey, body: CustomFieldLabelIn, conn: Db,
                        user: Admin) -> CustomFieldLabel:
    not_built("9.4")


@router.get("/masters/message-templates", response_model=list[MessageTemplate],
            summary="Message texts: birthday, slip by WhatsApp / SMS, general. Admin.")
def list_message_templates(conn: Db, user: Admin) -> list[MessageTemplate]:
    not_built("9.4")


@router.patch("/masters/message-templates/{kind}", response_model=MessageTemplate,
              summary="Change one message text. Admin.")
def update_message_template(kind: TemplateKind, body: MessageTemplateIn, conn: Db, user: Admin) -> MessageTemplate:
    not_built("9.4")


# --- files (9.4) ------------------------------------------------------------------------------
@router.post("/files", response_model=StoredFile, status_code=status.HTTP_201_CREATED,
             summary="Upload a candidate photo, symbol or slip header (image, up to 5 MB). Admin.")
def upload_file(conn: Db, user: Admin, file: Annotated[UploadFile, File()],
                kind: Annotated[FileKind, Form()]) -> StoredFile:
    not_built("9.4")


@router.get("/files/{file_id}", response_class=Response,
            responses={200: {"content": {"image/png": {}, "image/jpeg": {}}, "description": "The file"}},
            summary="Download a workspace image (candidate photo, symbol, slip header) for slips. All roles.")
def download_file(file_id: uuid.UUID, conn: Db, user: ReadyUser) -> Response:
    not_built("9.4")


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
