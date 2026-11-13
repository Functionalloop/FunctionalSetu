"""Contract (4.10) for field work, polling day, sync conflicts and the More menu.

Request bodies are also the `data` of the matching /sync/push item types (see PushType):
the phone sends the same shape online (REST) and offline (push).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from .schemas import MOBILE_PATTERN, Gender, Location, UserSummary


class Page(BaseModel):
    next_cursor: str | None = Field(None, description="Pass as `cursor` for the next page; null on the last page")


# --- families and walk list (7.1, 7.2) ------------------------------------------------
class FamilySource(StrEnum):
    roll_import = "roll_import"
    manual = "manual"
    name_suggestion = "name_suggestion"


class Family(BaseModel):
    id: uuid.UUID
    ward_id: uuid.UUID
    booth_id: uuid.UUID | None
    house_no: str | None
    label: str | None = Field(description="Family name, typed by the surveyor (families are made by hand, client 12 Nov)")
    head_voter_id: uuid.UUID | None
    source: FamilySource
    member_ids: list[uuid.UUID] = Field(description="Voters in this family")
    updated_at: datetime


class FamilyChange(BaseModel):
    """PUT /voters/{id}/family and push type `family`. Exactly one of family_id / new_family_id,
    or leave_family = true with neither (takes the voter out of their family)."""
    family_id: uuid.UUID | None = Field(None, description="Move the voter into this existing family")
    new_family_id: uuid.UUID | None = Field(None, description="Start a new family with this phone-made id")
    new_family_label: str | None = Field(None, max_length=200)
    make_head: bool = Field(False, description="Make this voter the head of the family")
    leave_family: bool = Field(False, description="Take the voter out of their family (added 12 Nov)")

    @model_validator(mode="after")
    def _one(self) -> FamilyChange:
        if self.leave_family:
            if self.family_id or self.new_family_id or self.make_head:
                raise ValueError("leave_family goes alone: no family_id, new_family_id or make_head")
        elif (self.family_id is None) == (self.new_family_id is None):
            raise ValueError("give exactly one of family_id or new_family_id")
        return self


class FamilyIn(BaseModel):
    """POST /families and push type `family_new` (entity_id = the family id): a family made by hand."""
    id: uuid.UUID = Field(description="Made by the phone; a repeat with the same id is stored once")
    booth_id: uuid.UUID = Field(description="The booth (part) the family belongs to")
    label: str = Field(min_length=1, max_length=200, description="Family name, free text")


class FamilyPatch(BaseModel):
    """PATCH /families/{id}: rename."""
    label: str = Field(min_length=1, max_length=200)


class FamilyPage(Page):
    items: list[Family]


class PartNote(BaseModel):
    """The one shared note of a roll part (its booth)."""
    booth_id: uuid.UUID
    note: str
    version: int = Field(description="0 = no note yet")
    updated_at: datetime | None
    updated_by: uuid.UUID | None


class PartNoteIn(BaseModel):
    """PUT /booths/{id}/note and push type `part_note` (entity_id = the booth id, base_version = version)."""
    note: str = Field(max_length=2000)
    version: int = Field(ge=0, description="The version you last saw; 0 if the part had no note yet. "
                                           "A stale one: 409 with the server copy (push: conflict)")


class VoterFamily(BaseModel):
    family: Family | None = Field(description="Null when the voter is in no family yet")


class WalkListHouse(BaseModel):
    """One house on the walk list of a booth."""
    family_id: uuid.UUID | None
    house_no: str | None
    label: str | None
    voter_ids: list[uuid.UUID]
    last_visit_outcome: VisitOutcome | None
    last_visit_at: datetime | None
    revisit_at: datetime | None


class WalkListPage(Page):
    items: list[WalkListHouse]


# --- visits (7.3) ------------------------------------------------------------------------
class VisitOutcome(StrEnum):
    met = "met"
    not_home = "not_home"
    revisit = "revisit"
    shifted = "shifted"


class VisitIn(BaseModel):
    """POST /voters/{id}/visits and push type `visit` (push: entity_id = the voter)."""
    id: uuid.UUID = Field(description="Made by the phone; a repeat with the same id is stored once")
    outcome: VisitOutcome
    visited_at: datetime
    revisit_at: datetime | None = Field(None, description="outcome = revisit: when to come back")
    note: str | None = Field(None, max_length=2000)
    location: Location | None = None


class Visit(BaseModel):
    id: uuid.UUID
    voter_id: uuid.UUID | None
    family_id: uuid.UUID | None
    booth_id: uuid.UUID
    house_no: str | None
    outcome: VisitOutcome
    visited_at: datetime
    revisit_at: datetime | None
    note: str | None
    visited_by: uuid.UUID
    lat: float | None
    lng: float | None


# --- new voters (7.5) --------------------------------------------------------------------
class Form6Status(StrEnum):
    not_applied = "not_applied"
    applied = "applied"
    approved = "approved"
    rejected = "rejected"


class NewVoterFields(BaseModel):
    full_name_en: str | None = Field(None, max_length=200)
    full_name_mr: str | None = Field(None, max_length=200)
    relative_name: str | None = Field(None, max_length=200)
    dob: date | None = None
    gender: Gender | None = None
    mobile: str | None = Field(None, pattern=MOBILE_PATTERN)
    address: str | None = Field(None, max_length=500)
    ward_id: uuid.UUID
    booth_id: uuid.UUID | None = None
    family_id: uuid.UUID | None = None
    form6_status: Form6Status = Form6Status.not_applied
    notes: str | None = Field(None, max_length=2000)

    @model_validator(mode="after")
    def _name(self) -> NewVoterFields:
        if not (self.full_name_en or self.full_name_mr):
            raise ValueError("give full_name_en or full_name_mr")
        return self


class NewVoterIn(NewVoterFields):
    """POST /new-voters and push type `new_voter`."""
    id: uuid.UUID = Field(description="Made by the phone (offline); a repeat with the same id is stored once")


class NewVoterPatch(NewVoterFields):
    """PATCH /new-voters/{id} and push type `new_voter_update`: the whole record plus the version last seen."""
    version: int = Field(ge=1)


class NewVoter(NewVoterFields):
    id: uuid.UUID
    version: int
    matched_voter_id: uuid.UUID | None = Field(description="Set when this person appears in a new roll")
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class NewVoterPage(Page):
    items: list[NewVoter]


# --- history (7.6) -----------------------------------------------------------------------
class HistoryEntry(BaseModel):
    at: datetime
    kind: str = Field(description="survey, visit, voted, roll_edit, family, slip, new_voter_match")
    action: str = Field(description="insert, update, delete, or the event name")
    by: UserSummary | None = Field(description="Null for system changes (roll import)")
    changes: dict = Field(description="field -> {old, new}; empty when not a field change")


class HistoryPage(Page):
    items: list[HistoryEntry]


# --- slips (7.7, 12.2) -------------------------------------------------------------------
class SlipChannel(StrEnum):
    pdf = "pdf"
    print = "print"
    whatsapp = "whatsapp"
    sms = "sms"


class SlipEventIn(BaseModel):
    """POST /voters/{id}/slip-events and push type `slip_event`."""
    id: uuid.UUID = Field(description="Made by the phone; a repeat with the same id is stored once")
    channel: SlipChannel
    at: datetime


# --- birthdays (7.8) ---------------------------------------------------------------------
class Birthday(BaseModel):
    voter_id: uuid.UUID
    full_name_mr: str | None
    full_name_en: str | None
    booth_id: uuid.UUID
    dob: date
    turns: int = Field(description="Age on this birthday")
    mobile_1: str | None


class BirthdayPage(Page):
    items: list[Birthday]


# --- polling day (8.1) -------------------------------------------------------------------
class TurnoutSource(StrEnum):
    single = "single"
    bulk_typed = "bulk_typed"
    booth_list = "booth_list"


class TurnoutMarkIn(BaseModel):
    """POST /turnout/marks and push type `voted`. Either voter_ids, or booth_id + serials ("12, 15, 18-25")."""
    id: uuid.UUID = Field(description="Made by the phone; a repeat with the same id is applied once")
    voter_ids: list[uuid.UUID] = Field(default_factory=list, max_length=2000)
    booth_id: uuid.UUID | None = None
    serials: str | None = Field(None, max_length=2000, examples=["12, 15, 18-25"])
    source: TurnoutSource = TurnoutSource.single
    marked_at: datetime | None = None

    @model_validator(mode="after")
    def _target(self) -> TurnoutMarkIn:
        if bool(self.voter_ids) == bool(self.booth_id and self.serials):
            raise ValueError("give voter_ids, or booth_id with serials")
        return self


class TurnoutMarkResult(BaseModel):
    marked: list[uuid.UUID] = Field(description="Newly marked as voted")
    already: list[uuid.UUID] = Field(description="Were already marked (kept as they were)")
    not_found_serials: list[int] = Field(default_factory=list, description="Serials with no voter in the booth")


class TurnoutMark(BaseModel):
    voter_id: uuid.UUID
    is_voted: bool = Field(description="false = the mark was undone")
    marked_by: uuid.UUID
    marked_at: datetime
    source: str


class TurnoutBooth(BaseModel):
    booth_id: uuid.UUID
    total: int
    voted: int
    percent: float


class TurnoutSummary(BaseModel):
    total: int
    voted: int
    percent: float
    booths: list[TurnoutBooth]
    updated_at: datetime


# --- sync conflicts (7.10, proposed) ------------------------------------------------------
class ConflictStatus(StrEnum):
    open = "open"
    kept_client = "kept_client"
    kept_server = "kept_server"


class Conflict(BaseModel):
    id: uuid.UUID
    entity_type: str = Field(description="voter_survey, new_voter or family")
    entity_id: uuid.UUID
    field_name: str
    client_value: object | None
    server_value: object | None
    client_user: UserSummary
    client_changed_at: datetime | None
    server_user_id: uuid.UUID | None
    server_changed_at: datetime | None
    status: ConflictStatus
    created_at: datetime


class ConflictPage(Page):
    items: list[Conflict]


class ConflictResolution(BaseModel):
    keep: ConflictStatus = Field(description="kept_client (write the phone's value) or kept_server (leave it)")

    @model_validator(mode="after")
    def _not_open(self) -> ConflictResolution:
        if self.keep == ConflictStatus.open:
            raise ValueError("keep must be kept_client or kept_server")
        return self


# --- More menu: terms, announcements, problem reports, app version (6.3, 7.9) -----------
class Terms(BaseModel):
    version: int
    body_mr: str
    body_en: str
    published_at: datetime


class TermsAccept(BaseModel):
    version: int = Field(description="The version the user read")


class Announcement(BaseModel):
    id: uuid.UUID
    body: str
    audience_geo_id: uuid.UUID | None = Field(description="Null = everyone")
    created_by: UserSummary
    created_at: datetime
    expires_at: datetime | None
    is_read: bool


class AnnouncementPage(Page):
    items: list[Announcement]


class ProblemReportIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    app_version_code: int | None = None
    phone_model: str | None = Field(None, max_length=200)


class AppVersion(BaseModel):
    latest_version_code: int
    latest_version_name: str
    min_version_code: int = Field(description="Below this the app must update before anything else")
    apk_url: str
    apk_sha256: str
    size_bytes: int
    notes_mr: str | None
    notes_en: str | None


# Visit is used by WalkListHouse above it.
WalkListHouse.model_rebuild()
