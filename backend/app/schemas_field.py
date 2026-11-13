"""Contract (4.10) for field work, polling day, sync conflicts and the More menu.

Request bodies are also the `data` of the matching /sync/push item types (see PushType):
the phone sends the same shape online (REST) and offline (push).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .schemas import (MOBILE_PATTERN, Form6Status, Gender, Location, NewVoter, NewVoterFields,  # noqa: F401
                      UserSummary, Visit, VisitOutcome)  # (re-exported)


class Page(BaseModel):
    next_cursor: str | None = Field(None, description="Pass as `cursor` for the next page; null on the last page")


# --- families and walk list (7.1, 7.2) ------------------------------------------------
# Kutumb name: spaces at the ends are dropped; blank is refused.
KutumbName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class FamilySource(StrEnum):
    roll_import = "roll_import"
    manual = "manual"
    name_suggestion = "name_suggestion"


class Family(BaseModel):
    """A Kutumb (Kutumb Connect): made by hand by a surveyor, in one booth, with no head (client, 12 Nov)."""
    id: uuid.UUID
    ward_id: uuid.UUID
    booth_id: uuid.UUID | None
    house_no: str | None = Field(description="Not set on hand-made Kutumbs")
    label: str | None = Field(description="Kutumb name, free text typed by the surveyor (often the name of the "
                                          "head of the family)")
    source: FamilySource
    member_ids: list[uuid.UUID] = Field(description="Voters in this Kutumb, in roll order")
    updated_at: datetime


class FamilyChange(BaseModel):
    """PUT /voters/{id}/family and push type `family`: family_id puts the voter in that Kutumb (moving them
    out of any other), or leave_family = true alone takes them out. A Kutumb is made with POST /families.
    There is no head (13 Nov): unknown fields such as make_head are refused (422)."""
    model_config = ConfigDict(extra="forbid")

    family_id: uuid.UUID | None = Field(None, description="Put the voter in this Kutumb (same booth as the voter)")
    leave_family: bool = Field(False, description="Take the voter out of their Kutumb")

    @model_validator(mode="after")
    def _one(self) -> FamilyChange:
        if self.leave_family == (self.family_id is not None):
            raise ValueError("give family_id, or leave_family = true alone")
        return self


class FamilyIn(BaseModel):
    """POST /families and push type `family_new` (entity_id = the family id): a Kutumb made by hand."""
    id: uuid.UUID = Field(description="Made by the phone; a repeat with the same id is stored once (first name kept)")
    booth_id: uuid.UUID = Field(description="The booth (part) the Kutumb belongs to")
    label: KutumbName = Field(description="Kutumb name, free text")


class FamilyPatch(BaseModel):
    """PATCH /families/{id}: rename."""
    label: KutumbName


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
class VisitIn(BaseModel):
    """POST /voters/{id}/visits and push type `visit` (push: entity_id = the voter)."""
    id: uuid.UUID = Field(description="Made by the phone; a repeat with the same id is stored once")
    outcome: VisitOutcome
    visited_at: datetime
    revisit_at: datetime | None = Field(None, description="Only with outcome = revisit: when to come back")
    note: str | None = Field(None, max_length=2000)
    location: Location | None = None

    @model_validator(mode="after")
    def _revisit(self) -> VisitIn:
        if self.revisit_at is not None and self.outcome != VisitOutcome.revisit:
            raise ValueError("revisit_at needs outcome = revisit")
        return self


# --- new voters (7.5) --------------------------------------------------------------------
class NewVoterIn(NewVoterFields):
    """POST /new-voters and push type `new_voter` (entity_id = this id)."""
    id: uuid.UUID = Field(description="Made by the phone (offline); a repeat with the same id is stored once")


class NewVoterPatch(NewVoterFields):
    """PATCH /new-voters/{id} and push type `new_voter_update` (without `version`; base_version = it):
    the whole record plus the version last seen."""
    version: int = Field(ge=1)


class NewVoterPage(Page):
    items: list[NewVoter]


# --- history (7.6) -----------------------------------------------------------------------
class HistoryEntry(BaseModel):
    """One change (Information Updation, 7.6)."""
    at: datetime = Field(description="When it was saved on the server; for a visit, the visit's own time")
    kind: str = Field(description="survey, family (Kutumb membership), visit, voted, roll_edit, slip; "
                                  "new_voter_match later (Matching Engine)")
    action: str = Field(description="insert, update, delete; for a slip, the channel (pdf, print, whatsapp, sms)")
    by: UserSummary | None = Field(description="Null for system changes (roll import)")
    changes: dict = Field(description=(
        "field -> {old, new} with the database column names (e.g. mobile_1, notes, caste_id, family_id, "
        "is_voted, outcome). An update lists only the fields that changed; an insert or delete lists the "
        "fields that have a value. Reference fields (caste_id, profession_id, color_tag_id, influencer_type_id, "
        "karyakarta_id, family_id, ward_id, booth_id, ...) also carry old_label / new_label. "
        "Empty for a slip, or when only bookkeeping changed."))


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
