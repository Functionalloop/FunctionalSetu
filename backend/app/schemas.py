"""Request and response bodies. These become the OpenAPI schema the portal and app build from."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Role(StrEnum):
    super_admin = "super_admin"
    admin = "admin"
    supervisor = "supervisor"
    surveyor = "surveyor"
    booth_agent = "booth_agent"


class DeviceStatusEnum(StrEnum):
    pending = "pending"
    approved = "approved"
    blocked = "blocked"
    wiped = "wiped"


class Lang(StrEnum):
    mr = "mr"
    en = "en"
    hi = "hi"


# --- auth ----------------------------------------------------------------------
class DeviceInfo(BaseModel):
    device_uid: str = Field(min_length=8, max_length=128,
                            description="Stable id of this install (Android ID, or a hash of it). "
                                        "The server stores only its SHA-256.")
    model: str | None = Field(None, max_length=100, examples=["Samsung SM-A155F"])
    os_version: str | None = Field(None, max_length=40, examples=["Android 14"])
    app_version_code: int | None = Field(None, ge=1)


class LoginRequest(BaseModel):
    workspace_code: str = Field(min_length=3, max_length=40, examples=["naik"])
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=1, max_length=128)
    device: DeviceInfo | None = Field(
        None, description="Required from the Android app. Omit from the web portal "
                          "(portal login is allowed for supervisor and above).")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=200)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class UserSummary(BaseModel):
    id: uuid.UUID
    username: str
    full_name_en: str
    full_name_mr: str | None
    role: Role


class WorkspaceSummary(BaseModel):
    id: uuid.UUID
    code: str
    name_en: str
    name_mr: str | None


class DeviceSummary(BaseModel):
    id: uuid.UUID
    status: DeviceStatusEnum


class AuthTokens(BaseModel):
    access_token: str
    refresh_token: str = Field(description="Send to /auth/refresh. A new one is returned each time; "
                                           "the old one stops working.")
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds.")
    must_change_password: bool = Field(description="If true, only /auth/change-password, /auth/logout and "
                                                   "/devices/me work until the password is changed.")
    user: UserSummary
    workspace: WorkspaceSummary
    device: DeviceSummary | None = Field(description="Null for a web portal session. If status is pending, "
                                                     "poll /devices/me until an admin approves it.")


# --- devices ---------------------------------------------------------------------
class DeviceDetail(BaseModel):
    id: uuid.UUID
    status: DeviceStatusEnum
    model: str | None
    os_version: str | None
    app_version_code: int | None
    requested_at: datetime
    decided_at: datetime | None
    wipe_required: bool = Field(description="True when an admin blocked this phone: delete all local data.")


class AdminDevice(DeviceDetail):
    """A phone as an admin sees it."""
    user_id: uuid.UUID
    decided_by: uuid.UUID | None
    blocked_reason: str | None


class BlockDeviceRequest(BaseModel):
    reason: str | None = Field(None, max_length=500, examples=["Phone lost"])


# --- /me -------------------------------------------------------------------------
class GeoLevel(StrEnum):
    local_body = "local_body"
    taluka = "taluka"
    gat = "gat"
    gan = "gan"
    ward = "ward"
    booth = "booth"
    section = "section"


class Area(BaseModel):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    level: GeoLevel
    code: str
    number: int | None
    name_mr: str
    name_en: str | None


class GeoNode(Area):
    address_mr: str | None = Field(description="Polling station address (booth level)")
    address_en: str | None
    ac_no: int | None = Field(description="Vidhan Sabha constituency number (constituency level)")
    children: list[GeoNode] = Field(default_factory=list)


class GeoTree(BaseModel):
    roots: list[GeoNode] = Field(description=(
        "Top areas the user may see, each with everything below it. Super admin: every constituency; "
        "admin: own constituency; supervisor / surveyor / booth agent: the assigned wards and booths "
        "(no parent above them). Inactive areas and everything below them are left out."))


class MeUser(UserSummary):
    mobile: str | None
    local_body_id: uuid.UUID | None = Field(description="Constituency of an admin / worker. Null for super admin.")
    preferred_language: Lang
    terms_version: int | None = Field(description="Terms version the user accepted, or null.")


class WorkspaceSettings(BaseModel):
    """Election details and feature switches. Candidate fields are null while code_of_conduct_mode is on."""
    election_code: str | None
    election_name_mr: str | None
    election_name_en: str | None
    election_type: str | None
    polling_date: date | None
    code_of_conduct_mode: bool
    candidate_name_mr: str | None
    candidate_name_en: str | None
    party_name_mr: str | None
    party_name_en: str | None
    candidate_photo_file_id: uuid.UUID | None
    symbol_file_id: uuid.UUID | None
    candidate_message_mr: str | None
    candidate_message_en: str | None
    message_start_mr: str | None
    message_start_en: str | None
    message_end_mr: str | None
    message_end_en: str | None
    contact_no: str | None
    slip_header_file_id: uuid.UUID | None
    whatsapp_slip_file_id: uuid.UUID | None
    feature_voter_photos: bool
    feature_survey: bool
    feature_slips: bool
    feature_workers_edit_slip: bool
    feature_mobile_import: bool
    feature_surname_first: bool
    feature_bluetooth_printer: bool
    slip_show_election_name: bool
    slip_show_booth_address: bool
    slip_show_assembly_mapping: bool
    slip_show_candidate: bool
    sms_fields: list[str]
    default_language: Lang
    min_app_version_code: int
    sync_interval_minutes: int
    middle_name_separator: str | None
    updated_at: datetime


CANDIDATE_FIELDS = ("candidate_name_mr", "candidate_name_en", "party_name_mr", "party_name_en",
                    "candidate_photo_file_id", "symbol_file_id", "candidate_message_mr", "candidate_message_en")


class Me(BaseModel):
    user: MeUser
    workspace: WorkspaceSummary
    areas: list[Area] = Field(description="Where this user works: every constituency for a super admin, "
                                          "their constituency for an admin, assigned wards / booths for others.")
    settings: WorkspaceSettings | None


# --- health ----------------------------------------------------------------------
class Health(BaseModel):
    status: str = Field(examples=["ok"])
    database: str = Field(examples=["ok"])
    version: str
