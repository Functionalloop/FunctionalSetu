"""Contract (4.10) for the admin screens: users, areas, constituencies, settings, lists, files, logs."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from .schemas import MOBILE_PATTERN, Area, DeviceStatusEnum, Lang, Role, UserSummary, WorkspaceSettings
from .schemas_field import Page

USERNAME_PATTERN = r"^[A-Za-z0-9._-]{3,40}$"


# --- users (9.1) -------------------------------------------------------------------------
class UserIn(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    full_name_en: str = Field(min_length=1, max_length=200)
    full_name_mr: str | None = Field(None, max_length=200)
    mobile: str | None = Field(None, pattern=MOBILE_PATTERN)
    role: Role = Field(description="An admin creates supervisor / surveyor / booth agent; only a super admin "
                                   "creates an admin or super admin")
    local_body_id: uuid.UUID | None = Field(None, description="Constituency; required except for a super admin. "
                                                              "An admin may only use their own.")
    preferred_language: Lang = Lang.mr


class UserPatch(BaseModel):
    """Only the fields sent are changed."""
    full_name_en: str | None = Field(None, min_length=1, max_length=200)
    full_name_mr: str | None = Field(None, max_length=200)
    mobile: str | None = Field(None, pattern=MOBILE_PATTERN)
    role: Role | None = None
    is_active: bool | None = Field(None, description="false = disable (logs the user out everywhere)")
    preferred_language: Lang | None = None


class User(UserSummary):
    mobile: str | None
    local_body_id: uuid.UUID | None
    is_active: bool
    must_change_password: bool
    preferred_language: Lang
    last_login_at: datetime | None
    locked_until: datetime | None
    created_at: datetime
    device_count: int = Field(description="Phones linked to this user")
    pending_device: bool = Field(description="A phone is waiting for approval")
    area_ids: list[uuid.UUID] = Field(default_factory=list, description=(
        "Wards and booths assigned to the user (as GET /users/{id}/assignments); empty for admins. "
        "Added 14 Nov (9.6) so the Booths & karyakartas screen needs one call"))


class UserPage(Page):
    items: list[User]


class TemporaryPassword(BaseModel):
    """Returned once, on create and on reset-password. Give it to the user privately."""
    user: User
    temporary_password: str


# --- assignments (9.2) ------------------------------------------------------------------
class Assignments(BaseModel):
    area_ids: list[uuid.UUID] = Field(description="Wards and booths the user works in (inside their constituency)")


class AssignmentsOut(BaseModel):
    areas: list[Area]


# --- constituencies (9.3) ---------------------------------------------------------------
class ConstituencyIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name_mr: str = Field(min_length=1, max_length=200)
    name_en: str | None = Field(None, max_length=200)
    ac_no: int | None = Field(None, ge=1, description="Vidhan Sabha number")


class ConstituencyPatch(BaseModel):
    name_mr: str | None = Field(None, min_length=1, max_length=200)
    name_en: str | None = Field(None, max_length=200)
    ac_no: int | None = Field(None, ge=1)
    is_active: bool | None = None


class Constituency(Area):
    ac_no: int | None
    is_active: bool
    voter_count: int
    user_count: int


# --- election settings (9.4) ------------------------------------------------------------
class ElectionSettingsIn(BaseModel):
    """PUT /settings/election: the whole editable set (like the survey, a field left out is cleared)."""
    election_code: str | None = None
    election_name_mr: str | None = None
    election_name_en: str | None = None
    election_type: str | None = Field(None, description="nagarpalika, ..., vidhan_sabha, lok_sabha, other")
    polling_date: date | None = None
    polling_start_time: time | None = Field(None, description="Polling hours, local (Indian) time; on voter slips")
    polling_end_time: time | None = None
    code_of_conduct_mode: bool = False
    candidate_name_mr: str | None = None
    candidate_name_en: str | None = None
    party_name_mr: str | None = None
    party_name_en: str | None = None
    candidate_photo_file_id: uuid.UUID | None = None
    symbol_file_id: uuid.UUID | None = None
    candidate_message_mr: str | None = None
    candidate_message_en: str | None = None
    message_start_mr: str | None = None
    message_start_en: str | None = None
    message_end_mr: str | None = None
    message_end_en: str | None = None
    contact_no: str | None = Field(None, pattern=MOBILE_PATTERN)
    slip_header_file_id: uuid.UUID | None = None
    whatsapp_slip_file_id: uuid.UUID | None = None
    feature_voter_photos: bool = True
    feature_survey: bool = True
    feature_slips: bool = True
    feature_workers_edit_slip: bool = False
    feature_mobile_import: bool = True
    feature_surname_first: bool = True
    slip_show_election_name: bool = True
    slip_show_booth_address: bool = True
    slip_show_assembly_mapping: bool = True
    slip_show_candidate: bool = False
    sms_fields: list[str] = Field(default_factory=lambda: ["election_name", "booth_address"])
    default_language: Lang = Lang.mr
    min_app_version_code: int = Field(1, ge=1)
    sync_interval_minutes: int = Field(15, ge=5, le=240)
    middle_name_separator: str | None = None

    @model_validator(mode="after")
    def _times(self) -> ElectionSettingsIn:
        if self.polling_start_time and self.polling_end_time and self.polling_end_time <= self.polling_start_time:
            raise ValueError("polling_end_time must be after polling_start_time")
        return self


class ElectionSettings(WorkspaceSettings):
    """GET/PUT /settings/election: like /me's settings, but candidate fields are never blanked (admin view)."""


# --- lists and labels (9.4) -------------------------------------------------------------
class NamedEntryIn(BaseModel):
    """A caste or a profession."""
    name_mr: str = Field(min_length=1, max_length=200)
    name_en: str | None = Field(None, max_length=200)
    name_hi: str | None = Field(None, max_length=200)
    sort_order: int = 0
    is_active: bool = True


class ColorTagIn(BaseModel):
    code: str = Field(pattern=r"^[a-z_]{2,20}$")
    hex: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    label_mr: str = Field(min_length=1, max_length=100)
    label_en: str = Field(min_length=1, max_length=100)
    label_hi: str | None = Field(None, max_length=100)
    is_default: bool = False
    sort_order: int = 0
    is_active: bool = True


class CustomFieldKey(StrEnum):
    extra_check_1 = "extra_check_1"
    extra_check_2 = "extra_check_2"
    extra_info_1 = "extra_info_1"
    extra_info_2 = "extra_info_2"
    extra_info_3 = "extra_info_3"
    extra_info_4 = "extra_info_4"
    extra_info_5 = "extra_info_5"


class CustomFieldLabelIn(BaseModel):
    label_mr: str | None = Field(None, max_length=100)
    label_en: str | None = Field(None, max_length=100)
    label_hi: str | None = Field(None, max_length=100)
    is_enabled: bool


class TemplateKind(StrEnum):
    birthday = "birthday"
    slip_whatsapp = "slip_whatsapp"
    slip_sms = "slip_sms"
    general = "general"


class MessageTemplateIn(BaseModel):
    body_mr: str | None = Field(None, max_length=2000)
    body_en: str | None = Field(None, max_length=2000)
    body_hi: str | None = Field(None, max_length=2000)


class MessageTemplate(MessageTemplateIn):
    kind: TemplateKind
    updated_at: datetime


# --- files (9.4; GET is a plan gap-table proposal) --------------------------------------
class FileKind(StrEnum):
    candidate_photo = "candidate_photo"
    symbol = "symbol"
    slip_header = "slip_header"
    whatsapp_slip = "whatsapp_slip"
    roll_import = "roll_import"
    mobile_import = "mobile_import"
    export = "export"            # 11.2: made by the worker, downloaded through GET /exports/{id}/download
    other = "other"


class StoredFile(BaseModel):
    id: uuid.UUID
    kind: FileKind
    original_name: str | None
    mime_type: str
    size_bytes: int
    sha256: str
    created_at: datetime


# --- announcements, problem reports (9.5) -----------------------------------------------
class AnnouncementIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    audience_geo_id: uuid.UUID | None = Field(None, description="Only workers in this area; null = everyone")
    expires_at: datetime | None = None


class ProblemReport(BaseModel):
    id: uuid.UUID
    user: UserSummary
    device_id: uuid.UUID | None
    body: str
    app_version_code: int | None
    phone_model: str | None
    status: str = Field(description="open or done")
    created_at: datetime


class ProblemReportPage(Page):
    items: list[ProblemReport]


# --- audit log, worker activity, worker locations (9.5) ---------------------------------
class AuditEntry(BaseModel):
    id: int
    occurred_at: datetime
    actor: UserSummary | None
    device_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: str | None
    old_values: dict | None
    new_values: dict | None


class AuditPage(Page):
    items: list[AuditEntry]


class WorkerDay(BaseModel):
    user: UserSummary
    day: date = Field(description="Indian date")
    surveys: int
    visits: int
    mobiles_collected: int
    new_voters: int
    voted_marks: int


class WorkerActivity(BaseModel):
    date_from: date
    date_to: date
    rows: list[WorkerDay]


class WorkerLocation(BaseModel):
    user: UserSummary
    kind: str = Field(description="survey or visit")
    voter_id: uuid.UUID | None
    lat: float
    lng: float
    accuracy_m: float | None
    at: datetime


class WorkerLocationPage(Page):
    items: list[WorkerLocation]


# device status for the users list filter
UserDeviceFilter = DeviceStatusEnum
