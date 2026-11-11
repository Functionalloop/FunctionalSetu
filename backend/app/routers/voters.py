"""Voters: GET /voters (search, filters, cursor paging)."""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import text

from ..deps import Db, ReadyUser
from ..errors import ApiError
from ..schemas import Gender, SurveyStatus, VoterListItem, VoterPage
from ..scope import UserScope, require_area

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
    key = [row["part_no"], row["booth_no"] or 0, row["serial_no"], str(row["id"])]
    return base64.urlsafe_b64encode(json.dumps(key).encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> dict:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        p, b, s, i = json.loads(raw)
        return {"c_part": int(p), "c_booth": int(b), "c_serial": int(s), "c_id": uuid.UUID(str(i))}
    except (ValueError, TypeError, binascii.Error, json.JSONDecodeError):
        raise ApiError(400, "invalid_cursor", "This cursor is not valid; start again without it.") from None


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
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> VoterPage:
    cond, params = scope.filter("v.geo_path")
    where = ["v.deleted_at IS NULL", cond]

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
              "profession_id": ("s.profession_id = :profession_id", profession_id)}
    for key, (sql, value) in simple.items():
        if value is not None:
            where.append(sql)
            params[key] = value.value if isinstance(value, Gender) else value

    if survey_status is not None:
        where.append(("" if survey_status == SurveyStatus.surveyed else "NOT ") + "coalesce(s.is_surveyed, false)")
    if has_mobile is not None:
        where.append("s.mobile_1 IS " + ("NOT NULL" if has_mobile else "NULL"))

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
