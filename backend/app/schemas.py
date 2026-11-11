"""Request and response bodies. These become the OpenAPI schema the portal and app build from."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


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


class AdminDeviceListItem(AdminDevice):
    username: str
    full_name_en: str
    role: Role
    last_seen_at: datetime | None = Field(description="Last login or refresh from this phone")


class DevicePage(BaseModel):
    items: list[AdminDeviceListItem]
    next_cursor: str | None = Field(description="Pass as `cursor` for the next page; null on the last page")


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


class Gender(StrEnum):
    M = "M"
    F = "F"
    O = "O"  # noqa: E741


class RelationType(StrEnum):
    father = "father"
    mother = "mother"
    husband = "husband"
    wife = "wife"
    other = "other"


class RollStatus(StrEnum):
    active = "active"
    absent_from_current_roll = "absent_from_current_roll"  # never treated as dead
    deleted_in_roll = "deleted_in_roll"


class SurveyStatus(StrEnum):
    surveyed = "surveyed"
    not_surveyed = "not_surveyed"


class VoterListItem(BaseModel):
    id: uuid.UUID
    local_body_id: uuid.UUID
    ward_id: uuid.UUID
    booth_id: uuid.UUID
    section_id: uuid.UUID | None
    part_no: int
    booth_no: int | None
    serial_no: int
    epic_no: str | None
    full_name_mr: str | None
    full_name_en: str | None
    relation_type: RelationType | None
    relative_name_mr: str | None
    relative_name_en: str | None
    gender: Gender
    age: int | None
    house_no: str | None
    roll_status: RollStatus
    mobile_1: str | None = Field(description="From the survey; null until surveyed")
    color_tag_id: uuid.UUID | None
    is_surveyed: bool


class VoterPage(BaseModel):
    items: list[VoterListItem]
    next_cursor: str | None = Field(description="Pass as `cursor` for the next page; null on the last page")


# --- survey ------------------------------------------------------------------------
MOBILE_PATTERN = r"^[6-9][0-9]{9}$"


class ListType(StrEnum):
    main = "main"
    supplementary = "supplementary"
    draft = "draft"


class SurveyFields(BaseModel):
    """The part of a survey a worker edits. PUT replaces all of it: a field left out is cleared."""
    mobile_1: str | None = Field(None, pattern=MOBILE_PATTERN, examples=["9876543210"])
    mobile_2: str | None = Field(None, pattern=MOBILE_PATTERN, description="Only together with mobile_1")
    dob: date | None = Field(None, description="Date of birth")
    caste_id: uuid.UUID | None = None
    profession_id: uuid.UUID | None = None
    color_tag_id: uuid.UUID | None = None
    has_new_address: bool = Field(False, description=(
        "Residence check: true when the voter no longer lives at the roll address. "
        "new_address_mr / new_address_en only with true."))
    new_address_mr: str | None = Field(None, max_length=500)
    new_address_en: str | None = Field(None, max_length=500)
    notes: str | None = Field(None, max_length=2000, description="Notes about the voter, shared with the team")
    extra_check_1: bool | None = Field(None, description="Custom yes/no field 1 (label in settings)")
    extra_check_2: bool | None = None
    extra_info_1: str | None = Field(None, max_length=500, description="Custom text field 1 (label in settings)")
    extra_info_2: str | None = Field(None, max_length=500)
    extra_info_3: str | None = Field(None, max_length=500)
    extra_info_4: str | None = Field(None, max_length=500)
    extra_info_5: str | None = Field(None, max_length=500)


class Location(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(None, ge=0)


class SurveyIn(SurveyFields):
    version: int = Field(ge=0, description="The survey version you last saw; 0 if the voter had no survey yet")
    location: Location | None = Field(None, description=(
        "Where the phone was when the survey was saved. Left out: the previous location is kept."))

    @model_validator(mode="after")
    def _check(self) -> SurveyIn:
        if self.mobile_2 and not self.mobile_1:
            raise ValueError("mobile_2 needs mobile_1")
        if not self.has_new_address and (self.new_address_mr or self.new_address_en):
            raise ValueError("new_address_* needs has_new_address = true")
        if self.dob and not (date(1900, 1, 1) <= self.dob <= date.today()):
            raise ValueError("dob must be between 1900-01-01 and today")
        return self


class Survey(SurveyFields):
    voter_id: uuid.UUID
    version: int
    is_surveyed: bool
    surveyed_at: datetime | None = Field(description="First survey save")
    lat: float | None
    lng: float | None
    location_accuracy_m: float | None
    location_captured_at: datetime | None
    updated_at: datetime
    updated_by: uuid.UUID | None


class VoterDetail(VoterListItem):
    first_name_mr: str | None
    middle_name_mr: str | None
    last_name_mr: str | None
    first_name_en: str | None
    middle_name_en: str | None
    last_name_en: str | None
    age_as_of: date | None
    address_mr: str | None = Field(description="Roll section text")
    address_en: str | None
    list_type: ListType
    deletion_reason: str | None = Field(description="Only as printed in the roll")
    is_repeated_in_roll: bool
    survey: Survey | None = Field(description="Null until the first survey save")


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


# --- sync pull ---------------------------------------------------------------------
class SyncArea(Area):
    address_mr: str | None
    address_en: str | None
    ac_no: int | None
    sort_order: int


class SyncVoter(BaseModel):
    """Official roll fields of one voter (the survey comes separately in `surveys`)."""
    id: uuid.UUID
    local_body_id: uuid.UUID
    ward_id: uuid.UUID
    booth_id: uuid.UUID
    section_id: uuid.UUID | None
    part_no: int
    booth_no: int | None
    serial_no: int
    epic_no: str | None
    first_name_mr: str | None
    middle_name_mr: str | None
    last_name_mr: str | None
    first_name_en: str | None
    middle_name_en: str | None
    last_name_en: str | None
    relation_type: RelationType | None
    relative_name_mr: str | None
    relative_name_en: str | None
    gender: Gender
    age: int | None
    age_as_of: date | None
    house_no: str | None
    address_mr: str | None
    address_en: str | None
    list_type: ListType
    roll_status: RollStatus
    deletion_reason: str | None
    is_repeated_in_roll: bool
    deleted_at: datetime | None = Field(description="Set when the voter was removed: delete it on the phone")


class NamedListEntry(BaseModel):
    """A caste or a profession."""
    id: uuid.UUID
    name_mr: str
    name_en: str | None
    name_hi: str | None
    sort_order: int
    is_active: bool = Field(description="Inactive: keep showing it on old surveys, do not offer it for new ones")


class ColorTag(BaseModel):
    id: uuid.UUID
    code: str
    hex: str
    label_mr: str
    label_en: str
    label_hi: str | None
    is_default: bool
    sort_order: int
    is_active: bool


class CustomFieldLabel(BaseModel):
    field_key: str = Field(description="extra_check_1-2 or extra_info_1-5 in the survey")
    label_mr: str | None
    label_en: str | None
    label_hi: str | None
    is_enabled: bool = Field(description="Disabled fields are hidden in the survey")


class SyncLists(BaseModel):
    castes: list[NamedListEntry]
    professions: list[NamedListEntry]
    color_tags: list[ColorTag]
    custom_field_labels: list[CustomFieldLabel]


class SyncPage(BaseModel):
    """One page of a sync pull. If `wipe` is true, delete all local data and log out; nothing else
    in the page applies. Otherwise save every row it holds (insert or replace by id; a voter with
    `deleted_at` set is deleted), delete `gone_voter_ids`, then ask for `next_cursor`. When
    `next_cursor` is null the pull is complete: store `watermark` and send it as `since` next time.
    `area_ids` (page 1): the user's areas now. Drop local areas (and their voters) not in it; if it
    holds an area the phone does not have, run a first download again (no `since`)."""
    watermark: str = Field(description="The same on every page of one download (a whole number, as text)")
    next_cursor: str | None
    settings: WorkspaceSettings | None = Field(None, description=(
        "Page 1 only; on a delta pull only when the settings changed"))
    lists: SyncLists | None = Field(None, description="Page 1 only; on a delta pull only the entries that changed")
    wipe: bool = Field(False, description="The phone was blocked: delete all local data and log out")
    areas: list[SyncArea] = Field(default_factory=list, description=(
        "Page 1: the user's areas (delta: only those changed since `since`)"))
    area_ids: list[uuid.UUID] | None = Field(None, description="Page 1 only: ids of all the user's areas now")
    total_voters: int | None = Field(None, description="Page 1 only: voters this pull will send (progress bar)")
    total_surveys: int | None = Field(None, description="Page 1 only: surveys this pull will send")
    voters: list[SyncVoter] = Field(default_factory=list)
    surveys: list[Survey] = Field(default_factory=list)
    gone_voter_ids: list[uuid.UUID] = Field(default_factory=list, description=(
        "Delta only: voters that changed and are now outside the user's area; delete them on the phone"))


# --- sync push ---------------------------------------------------------------------
MAX_PUSH_ITEMS = 500


class PushType(StrEnum):
    survey = "survey"  # visits, voted marks, new voters, families, slips: later steps


class PushStatus(StrEnum):
    applied = "applied"    # saved (or already the same as on the server)
    conflict = "conflict"  # stale base_version: nothing written, kept in sync_conflicts for review
    rejected = "rejected"  # not allowed or invalid: will never apply, drop it from the outbox


class PushItem(BaseModel):
    id: uuid.UUID = Field(description="Made by the phone for this outbox item; a retry sends the same id")
    type: PushType
    entity_id: uuid.UUID = Field(description="survey: the voter id")
    base_version: int = Field(ge=0, description="survey: the version the phone last had; 0 = no survey yet")
    changed_at: datetime | None = Field(None, description="When the change was made on the phone")
    data: dict = Field(description=(
        "survey: the same body as PUT /voters/{id}/survey (SurveyIn) without `version`. "
        "Checked per item: an invalid item is rejected on its own, the rest of the batch still applies."))


class PushRequest(BaseModel):
    items: list[PushItem] = Field(max_length=MAX_PUSH_ITEMS, description="Applied in this order")


class PushError(BaseModel):
    code: str
    message: str


class PushResult(BaseModel):
    id: uuid.UUID = Field(description="The item's id")
    status: PushStatus
    duplicate: bool = Field(description="This id was received before: the stored result, nothing applied again")
    error: PushError | None = Field(None, description="rejected only")
    survey: Survey | None = Field(None, description=(
        "applied: the saved copy (new version); conflict: the server copy"))
    conflict_fields: list[str] = Field(default_factory=list, description="conflict: fields that differ")


class PushResponse(BaseModel):
    results: list[PushResult] = Field(description="One per item, in the same order")
