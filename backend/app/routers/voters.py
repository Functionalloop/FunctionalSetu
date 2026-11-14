"""Voters: GET /voters (search, filters, cursor paging), GET /voters/{id}, PUT /voters/{id}/survey."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Connection, text

from ..deps import SURVEY_ROLES, Db, Principal, ReadyUser, require_roles
from ..errors import ApiError
from ..history import voter_history
from ..paging import decode_cursor, encode_cursor, invalid_cursor
from ..schemas import (Gender, Role, Survey, SurveyFields, SurveyIn, SurveyStatus, VoterDetail, VoterListItem,
                       VoterPage)
from ..schemas_field import HistoryPage
from ..scope import Scope, UserScope, require_area

router = APIRouter(prefix="/voters", tags=["voters"])

MAX_TOKENS = 5
MOBILE_MIN_DIGITS = 4  # a number this long or longer also matches part of a mobile

_LIST_COLS = """
    v.id, v.local_body_id, v.ward_id, v.booth_id, v.section_id, v.part_no, v.booth_no, v.serial_no,
    v.epic_no, nullif(v.full_name_mr, '') AS full_name_mr, nullif(v.full_name_en, '') AS full_name_en,
    v.relation_type, v.relative_name_mr, v.relative_name_en, v.gender, v.age, v.house_no, v.roll_status,
    s.mobile_1, s.color_tag_id, coalesce(s.is_surveyed, false) AS is_surveyed
"""
# Roll order: part (ward), booth, serial; id makes the order total for the cursor.
_SORT = "v.part_no, coalesce(v.booth_no, 0), v.serial_no, v.id"


def _encode_cursor(row: Any) -> str:
    return encode_cursor([row["part_no"], row["booth_no"] or 0, row["serial_no"], str(row["id"])])


def _decode_cursor(cursor: str) -> dict:
    p, b, s, i = decode_cursor(cursor, 4)
    try:
        return {"c_part": int(p), "c_booth": int(b), "c_serial": int(s), "c_id": uuid.UUID(str(i))}
    except (ValueError, TypeError):
        raise invalid_cursor() from None


def _like(token: str) -> str:
    esc = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%"


@router.get("", response_model=VoterPage,
            summary="Search and filter voters in the user's area, in roll order. All roles.")
def list_voters(
    conn: Db, user: ReadyUser, scope: UserScope,
    q: Annotated[str | None, Query(max_length=100, description=(
        "Words to find. Every word must match a name (Marathi or English), EPIC or house number. "
        "A number also matches the serial number exactly, and part of a mobile if it has 4+ digits."))] = None,
    ward_id: uuid.UUID | None = None,
    booth_id: uuid.UUID | None = None,
    age_min: Annotated[int | None, Query(ge=0, le=150)] = None,
    age_max: Annotated[int | None, Query(ge=0, le=150)] = None,
    gender: Gender | None = None,
    color_tag_id: uuid.UUID | None = None,
    survey_status: SurveyStatus | None = None,
    caste_id: uuid.UUID | None = None,
    profession_id: uuid.UUID | None = None,
    has_mobile: bool | None = None,
    influencer: Annotated[bool | None, Query(description="true: influencers only; false: the others")] = None,
    influencer_type_id: uuid.UUID | None = None,
    removed: Annotated[bool, Query(description=(
        "true: only the voters a super admin removed (hidden), to restore one. Admin and super admin."))] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> VoterPage:
    if removed and not user.at_least(Role.admin):
        raise ApiError(403, "forbidden_role", "Only an admin can list removed voters.")
    cond, params = scope.filter("v.geo_path")
    where = ["v.deleted_at IS NOT NULL" if removed else "v.deleted_at IS NULL", cond]

    for name, area in (("ward_id", ward_id), ("booth_id", booth_id)):
        if area is not None:
            require_area(conn, scope, area)  # 404 outside the user's area
            where.append(f"v.{name} = :{name}")
            params[name] = area

    tokens = (q or "").lower().split()
    if len(tokens) > MAX_TOKENS:
        raise ApiError(422, "validation_error", f"q: use at most {MAX_TOKENS} words.")
    for i, tok in enumerate(tokens):
        parts = [f"v.search_text LIKE :q{i}"]
        params[f"q{i}"] = _like(tok)
        if tok.isascii() and tok.isdigit():
            if len(tok) <= 9:
                parts.append(f"v.serial_no = :qn{i}")
                params[f"qn{i}"] = int(tok)
            if len(tok) >= MOBILE_MIN_DIGITS:
                parts.append(f"s.mobile_1 LIKE :q{i} OR s.mobile_2 LIKE :q{i}")
        where.append("(" + " OR ".join(parts) + ")")

    simple = {"age_min": ("v.age >= :age_min", age_min), "age_max": ("v.age <= :age_max", age_max),
              "gender": ("v.gender = CAST(:gender AS app.gender)", gender),
              "color_tag_id": ("s.color_tag_id = :color_tag_id", color_tag_id),
              "caste_id": ("s.caste_id = :caste_id", caste_id),
              "profession_id": ("s.profession_id = :profession_id", profession_id),
              "influencer_type_id": ("s.influencer_type_id = :influencer_type_id", influencer_type_id)}
    for key, (sql, value) in simple.items():
        if value is not None:
            where.append(sql)
            params[key] = value.value if isinstance(value, Gender) else value

    if survey_status is not None:
        where.append(("" if survey_status == SurveyStatus.surveyed else "NOT ") + "coalesce(s.is_surveyed, false)")
    if has_mobile is not None:
        where.append("s.mobile_1 IS " + ("NOT NULL" if has_mobile else "NULL"))
    if influencer is not None:
        where.append(("" if influencer else "NOT ") + "coalesce(s.is_influencer, false)")

    if cursor:
        params.update(_decode_cursor(cursor))
        where.append(f"({_SORT}) > (:c_part, :c_booth, :c_serial, :c_id)")

    rows = conn.execute(text(f"""
        SELECT {_LIST_COLS}
          FROM app.voters v
          LEFT JOIN app.voter_surveys s ON s.tenant_id = v.tenant_id AND s.voter_id = v.id
         WHERE {' AND '.join(where)}
         ORDER BY {_SORT}
         LIMIT :limit_plus_one
    """), {**params, "limit_plus_one": limit + 1}).mappings().all()

    more = len(rows) > limit
    rows = rows[:limit]
    return VoterPage(items=[VoterListItem(**r) for r in rows],
                     next_cursor=_encode_cursor(rows[-1]) if more else None)


# --- one voter and the survey ------------------------------------------------------------
SURVEY_COLUMNS = ["voter_id", "version", "is_surveyed", "surveyed_at", "lat", "lng", "location_accuracy_m",
                  "location_captured_at", "updated_at", "updated_by", *SurveyFields.model_fields]  # = Survey
_SURVEY_COLS = ", ".join(SURVEY_COLUMNS)
_EDIT_COLS = list(SurveyFields.model_fields)  # replaced on every save

SurveyUser = Annotated[Principal, Depends(require_roles(SURVEY_ROLES))]


def voter_in_scope(conn: Connection, scope: Scope, voter_id: uuid.UUID, cols: str = "v.id",
                   include_removed: bool = False) -> Any:
    """The voter row, or 404 when it is removed (unless `include_removed`), in another workspace (RLS)
    or outside the user's area."""
    cond, params = scope.filter("v.geo_path")
    live = "TRUE" if include_removed else "v.deleted_at IS NULL"
    row = conn.execute(text(f"""
        SELECT {cols} FROM app.voters v
          LEFT JOIN app.voter_surveys s ON s.tenant_id = v.tenant_id AND s.voter_id = v.id
         WHERE v.id = :voter_id AND {live} AND {cond}
    """), {**params, "voter_id": voter_id}).mappings().first()
    if row is None:
        raise ApiError(404, "not_found", "Voter not found.")
    return row


DETAIL_COLS = f"""{_LIST_COLS},
    v.first_name_mr, v.middle_name_mr, v.last_name_mr, v.first_name_en, v.middle_name_en, v.last_name_en,
    v.age_as_of, v.address_mr, v.address_en, v.list_type, v.deletion_reason, v.is_repeated_in_roll, v.deleted_at"""


def voter_detail(conn: Connection, scope: Scope, voter_id: uuid.UUID, include_removed: bool = False) -> VoterDetail:
    row = voter_in_scope(conn, scope, voter_id, DETAIL_COLS, include_removed)
    return VoterDetail(**row, survey=read_survey(conn, voter_id))


def read_survey(conn: Connection, voter_id: uuid.UUID) -> Survey | None:
    row = conn.execute(text(f"SELECT {_SURVEY_COLS} FROM app.voter_surveys WHERE voter_id = :v"),
                       {"v": voter_id}).mappings().first()
    return Survey(**row) if row else None


def check_survey_references(conn: Connection, body: SurveyIn) -> None:
    """Caste, profession, colour tag and influencer type must be active entries of this
    workspace (RLS), else 422."""
    for field, table in (("caste_id", "castes"), ("profession_id", "professions"), ("color_tag_id", "color_tags"),
                         ("influencer_type_id", "influencer_types")):
        value = getattr(body, field)
        if value is not None and not conn.execute(
                text(f"SELECT EXISTS (SELECT 1 FROM app.{table} WHERE id = :id AND is_active)"), {"id": value}).scalar():
            raise ApiError(422, "validation_error", f"{field}: not found in this workspace's lists.")


@router.get("/{voter_id}", response_model=VoterDetail, summary="One voter: roll details plus survey. All roles.")
def get_voter(voter_id: uuid.UUID, conn: Db, user: ReadyUser, scope: UserScope) -> VoterDetail:
    return voter_detail(conn, scope, voter_id)


@router.get("/{voter_id}/history", response_model=HistoryPage,
            summary="Information Updation: every change to the voter, newest first (survey, Kutumb, visits, "
                    "voted marks, roll edits, slips), each with who, when and the fields changed. All roles.")
def get_voter_history(voter_id: uuid.UUID, conn: Db, user: ReadyUser, scope: UserScope,
                      limit: Annotated[int, Query(ge=1, le=200)] = 50,
                      cursor: Annotated[str | None, Query(description="next_cursor from the previous page")] = None,
                      ) -> HistoryPage:
    voter_in_scope(conn, scope, voter_id)
    return voter_history(conn, voter_id, limit, cursor)


@router.put("/{voter_id}/survey", response_model=Survey,
            summary="Save the survey (first save creates it). Stale version: 409 with the server copy. "
                    "Super admin, admin, supervisor, surveyor; not booth agent.")
def save_survey(voter_id: uuid.UUID, body: SurveyIn, conn: Db, user: SurveyUser, scope: UserScope) -> Survey:
    voter_in_scope(conn, scope, voter_id)
    check_survey_references(conn, body)

    saved = write_survey(conn, user, voter_id, body)
    if saved is None:  # someone saved first, or the version is not the one on the server
        current = read_survey(conn, voter_id)
        raise ApiError(409, "version_conflict",
                       "The survey was changed by someone else. Check the server copy and save again.",
                       extra={"current": current.model_dump(mode="json") if current else None})
    return saved


def _db_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def write_survey(conn: Connection, user: Principal, voter_id: uuid.UUID, body: SurveyIn) -> Survey | None:
    """Create (version 0) or update (current version) the survey; None when the version is stale.
    The caller has checked the role, the voter's area and the references. Used by PUT and sync push."""
    values: dict[str, Any] = {c: _db_value(getattr(body, c)) for c in _EDIT_COLS}
    values.update(voter_id=voter_id, version=body.version, user=user.user_id, device=user.device_id)
    loc = body.location
    values.update(lat=loc.lat if loc else None, lng=loc.lng if loc else None, acc=loc.accuracy_m if loc else None)
    has_loc = loc is not None

    if body.version == 0:
        cols = ", ".join(_EDIT_COLS)
        marks = ", ".join(f":{c}" for c in _EDIT_COLS)
        saved = conn.execute(text(f"""
            INSERT INTO app.voter_surveys (tenant_id, voter_id, {cols}, lat, lng, location_accuracy_m,
                                           location_captured_at, is_surveyed, surveyed_at, updated_by,
                                           updated_device_id)
            VALUES (app.current_tenant_id(), :voter_id, {marks}, :lat, :lng, :acc,
                    CASE WHEN :has_loc THEN now() END, true, now(), :user, :device)
            ON CONFLICT (voter_id) DO NOTHING
            RETURNING voter_id
        """), {**values, "has_loc": has_loc}).first()
    else:
        sets = ", ".join(f"{c} = :{c}" for c in _EDIT_COLS)
        loc_sets = ("lat = :lat, lng = :lng, location_accuracy_m = :acc, location_captured_at = now(),"
                    if has_loc else "")
        saved = conn.execute(text(f"""
            UPDATE app.voter_surveys
               SET {sets}, {loc_sets} is_surveyed = true, surveyed_at = coalesce(surveyed_at, now()),
                   updated_by = :user, updated_device_id = :device
             WHERE voter_id = :voter_id AND version = :version
            RETURNING voter_id
        """), values).first()
    return read_survey(conn, voter_id) if saved is not None else None
