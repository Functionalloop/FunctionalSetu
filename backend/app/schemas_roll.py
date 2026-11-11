"""Contract (4.10) for roll update, one-voter corrections, data quality, reports and exports."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from .schemas import Gender, ListType, RelationType, SyncVoter, UserSummary
from .schemas_field import Page


# --- roll import (10.2, 10.3) ------------------------------------------------------------
class RollImportStatus(StrEnum):
    uploaded = "uploaded"
    parsing = "parsing"
    review = "review"
    applied = "applied"
    failed = "failed"
    discarded = "discarded"


class MatchStatus(StrEnum):
    matched = "matched"
    uncertain = "uncertain"
    possible_duplicate = "possible_duplicate"
    absent_from_current_roll = "absent_from_current_roll"
    new = "new"


class ReviewStatus(StrEnum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"


class RollImport(BaseModel):
    id: uuid.UUID
    local_body_id: uuid.UUID
    list_type: ListType
    title: str
    published_on: date | None
    status: RollImportStatus
    counts: dict[str, int] = Field(description="matched, uncertain, possible_duplicate, absent_from_current_roll, "
                                               "new, reviewed: filled while parsing")
    error: str | None = None
    imported_by: UserSummary | None
    applied_at: datetime | None
    created_at: datetime


class RollImportPage(Page):
    items: list[RollImport]


class RollImportRow(BaseModel):
    id: int
    row_no: int
    part_no: int | None
    serial_no: int | None
    epic_no: str | None
    first_name_en: str | None
    last_name_en: str | None
    first_name_mr: str | None
    last_name_mr: str | None
    gender: Gender | None
    age: int | None
    house_no: str | None
    match_status: MatchStatus | None
    matched_voter_id: uuid.UUID | None
    similarity: float | None
    match_notes: str | None
    review_status: ReviewStatus


class RollImportRowPage(Page):
    items: list[RollImportRow]


class RowResolution(BaseModel):
    accept: bool = Field(description="true = the match is right; false = treat the row as a new voter")
    voter_id: uuid.UUID | None = Field(None, description="Match to this voter instead of the suggested one")


# --- one-voter corrections (10.4) --------------------------------------------------------
class RollEditReason(StrEnum):
    supplementary_list = "supplementary_list"
    typing_mistake = "typing_mistake"
    booth_changed = "booth_changed"
    shifted = "shifted"
    duplicate = "duplicate"
    deleted_in_new_roll = "deleted_in_new_roll"
    dead = "dead"
    other = "other"


class RollFields(BaseModel):
    booth_id: uuid.UUID
    section_id: uuid.UUID | None = None
    serial_no: int = Field(gt=0)
    epic_no: str | None = Field(None, pattern=r"^[A-Z0-9/]{6,20}$")
    first_name_mr: str | None = None
    middle_name_mr: str | None = None
    last_name_mr: str | None = None
    first_name_en: str | None = None
    middle_name_en: str | None = None
    last_name_en: str | None = None
    relation_type: RelationType | None = None
    relative_name_mr: str | None = None
    relative_name_en: str | None = None
    gender: Gender
    age: int | None = Field(None, ge=18, le=125)
    house_no: str | None = None
    address_mr: str | None = None
    address_en: str | None = None
    list_type: ListType = ListType.main


class VoterAdd(RollFields):
    """POST /voters: add one voter to the roll by hand."""
    reason: RollEditReason
    reference: str | None = Field(None, max_length=200, description="List number or date")


class RollPatch(BaseModel):
    """PATCH /voters/{id}/roll: only the fields sent are changed, with a reason."""
    fields: dict = Field(description="Any of the RollFields keys with their new values")
    reason: RollEditReason
    reference: str | None = Field(None, max_length=200)


class RemoveRestore(BaseModel):
    reason: RollEditReason
    reference: str | None = Field(None, max_length=200)


class RollEdit(BaseModel):
    id: int
    voter_id: uuid.UUID
    action: str = Field(description="add, correct, remove, restore")
    reason: RollEditReason
    reference: str | None
    old_values: dict | None
    new_values: dict | None
    edited_by: UserSummary
    edited_at: datetime


class RollEditPage(Page):
    items: list[RollEdit]


# --- data quality (10.5) -----------------------------------------------------------------
class DataQualitySummary(BaseModel):
    voters: int
    no_mobile: int
    no_dob: int
    possible_duplicates: int = Field(description="Pairs not yet checked")
    repeated_in_roll: int
    shifted: int = Field(description="Residence check says moved, or last visit 'shifted'")
    doubtful_dead: int = Field(description="Marked dead by a worker, not yet confirmed")
    name_fixes_waiting: int


class PairStatus(StrEnum):
    unchecked = "unchecked"
    same_person = "same_person"
    different_people = "different_people"


class DuplicatePair(BaseModel):
    id: uuid.UUID
    voter_a: SyncVoter
    voter_b: SyncVoter
    source: str = Field(description="roll_flag, fuzzy_match, roll_update")
    similarity: float | None
    status: PairStatus


class DuplicatePairPage(Page):
    items: list[DuplicatePair]


class PairResolution(BaseModel):
    same_person: bool
    keep_voter_id: uuid.UUID | None = Field(None, description="same_person: the record to keep; the other is hidden")


class NameFix(BaseModel):
    id: uuid.UUID
    voter_id: uuid.UUID
    current: dict = Field(description="first/middle/last name in English now")
    suggested: dict = Field(description="first/middle/last name suggested")
    status: ReviewStatus
    requested_by: UserSummary
    requested_at: datetime


class NameFixPage(Page):
    items: list[NameFix]


class NameFixIn(BaseModel):
    """Push type `name_fix` (plan gap table: spelling fixes come from the phone). entity_id = the voter."""
    first_name_en: str | None = Field(None, max_length=100)
    middle_name_en: str | None = Field(None, max_length=100)
    last_name_en: str | None = Field(None, max_length=100)


class Accept(BaseModel):
    accept: bool


# --- mobile number sheets (10.5) ---------------------------------------------------------
class MobileImportStatus(StrEnum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class MobileMatchStatus(StrEnum):
    matched = "matched"
    needs_review = "needs_review"
    not_found = "not_found"
    skipped = "skipped"


class MobileImportRow(BaseModel):
    id: int
    row_no: int
    name: str | None
    mobile: str
    address_text: str | None
    status: MobileMatchStatus
    matched_voter_id: uuid.UUID | None
    candidate_voter_ids: list[uuid.UUID]


class MobileImport(BaseModel):
    id: uuid.UUID
    status: MobileImportStatus
    matched_count: int
    review_count: int
    not_found_count: int
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    rows: list[MobileImportRow] = Field(description="Rows that need review first, then the rest (first 500)")


class MobileRowResolution(BaseModel):
    voter_id: uuid.UUID | None = Field(description="The voter this mobile belongs to; null = skip the row")


# --- reports (11.1, 9.5) ----------------------------------------------------------------
class AreaCount(BaseModel):
    area_id: uuid.UUID
    name: str
    level: str
    total: int
    done: int
    percent: float


class SurveyProgress(BaseModel):
    total: int
    surveyed: int
    percent: float
    by_area: list[AreaCount] = Field(description="Wards, and booths inside them")


class ColorTagCount(BaseModel):
    color_tag_id: uuid.UUID | None = Field(description="null = no colour tag")
    count: int


class ColorTagReport(BaseModel):
    total: int
    by_tag: list[ColorTagCount]
    by_area: dict[str, list[ColorTagCount]] = Field(description="area id -> counts")


class AgeBand(BaseModel):
    band: str = Field(examples=["18-25"])
    male: int
    female: int
    other: int


class Demographics(BaseModel):
    total: int
    male: int
    female: int
    other: int
    age_bands: list[AgeBand]


class TurnoutHour(BaseModel):
    hour: int = Field(ge=0, le=23, description="Indian time")
    voted: int
    cumulative: int


class TurnoutReport(BaseModel):
    total: int
    voted: int
    percent: float
    by_area: list[AreaCount]
    by_hour: list[TurnoutHour]


# --- exports (11.2) ---------------------------------------------------------------------
class ExportKind(StrEnum):
    voter_list = "voter_list"
    report = "report"
    turnout = "turnout"
    mobile_list = "mobile_list"


class ExportFormat(StrEnum):
    pdf = "pdf"
    xlsx = "xlsx"


class ExportIn(BaseModel):
    kind: ExportKind
    format: ExportFormat
    language: str = Field("mr", pattern=r"^(mr|en|hi)$")
    filter: dict = Field(default_factory=dict, description="The same keys as GET /voters (ward_id, booth_id, ...)")
    columns: list[str] = Field(default_factory=list, description="Empty = the default columns")
    options: dict = Field(default_factory=dict, description="paper, text_size, group_by_house, header")


class Export(BaseModel):
    id: uuid.UUID
    kind: ExportKind
    format: ExportFormat
    status: MobileImportStatus = Field(description="queued, running, done, failed")
    row_count: int | None
    page_count: int | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None
