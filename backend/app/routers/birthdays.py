"""Birthdays (plan 7.8): GET /birthdays.

Date of birth comes from the survey (voter_surveys.dob; the roll has only the age). A range is by
day and month and may run over the year end (28 Dec to 3 Jan). Results come in birthday order from
date_from: the days up to 31 Dec first, then the days after the year end. A 29 Feb birthday shows on
28 Feb in a year without 29 Feb, so it is never skipped. The phone reads its own database for its
Birthdays screen; this endpoint is for the portal and checks.
"""

from __future__ import annotations

import calendar
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import text

from ..deps import Db, ReadyUser
from ..errors import ApiError
from ..paging import decode_cursor, encode_cursor, invalid_cursor
from ..schemas_field import Birthday, BirthdayPage
from ..scope import UserScope, require_area

router = APIRouter(tags=["field work"])

MAX_DAYS = 366


@router.get("/birthdays", response_model=BirthdayPage,
            summary="Voters in the user's area with a birthday between two dates (day and month), in birthday "
                    "order. Date of birth from the survey. All roles.")
def birthdays(conn: Db, user: ReadyUser, scope: UserScope, date_from: date,
              date_to: Annotated[date | None, Query(description="Default: date_from (one day). At most 365 days "
                                                                  "after date_from.")] = None,
              booth_id: uuid.UUID | None = None,
              limit: Annotated[int, Query(ge=1, le=200)] = 50,
              cursor: Annotated[str | None, Query(description="next_cursor from the previous page")] = None,
              ) -> BirthdayPage:
    date_to = date_to or date_from
    if date_to < date_from or (date_to - date_from).days >= MAX_DAYS:
        raise ApiError(422, "validation_error", "date_to: from date_from up to 365 days later.")
    full_year = (date_to - date_from).days >= 365

    cond, params = scope.filter("v.geo_path")
    where = [cond, "v.deleted_at IS NULL", "s.dob IS NOT NULL"]
    if booth_id is not None:
        require_area(conn, scope, booth_id)
        where.append("v.booth_id = :booth_id")
        params["booth_id"] = booth_id

    # md = the birthday as 'MM-DD'; 29 Feb counts as 28 Feb in a year without it.
    leap = calendar.isleap(date_from.year)
    md = "to_char(s.dob, 'MM-DD')" if leap else \
        "CASE WHEN to_char(s.dob, 'MM-DD') = '02-29' THEN '02-28' ELSE to_char(s.dob, 'MM-DD') END"
    f, t = date_from.strftime("%m-%d"), date_to.strftime("%m-%d")
    params.update(f=f, t=t)
    if not full_year:
        # less than a year: f > t only when the range runs over the year end
        where.append(f"({md}) BETWEEN :f AND :t" if f <= t else f"(({md}) >= :f OR ({md}) <= :t)")
    # wrap = 0 for birthdays from date_from to 31 Dec, 1 for those after the year end
    wrap = f"CASE WHEN ({md}) >= :f THEN 0 ELSE 1 END"

    after = ""
    if cursor:
        w, m, i = decode_cursor(cursor, 3)
        try:
            params.update(c_w=int(w), c_m=str(m), c_id=uuid.UUID(str(i)))
        except (TypeError, ValueError):
            raise invalid_cursor() from None
        after = f"AND ({wrap}, ({md}) COLLATE \"C\", v.id) > (:c_w, CAST(:c_m AS text) COLLATE \"C\", :c_id)"

    rows = conn.execute(text(f"""
        SELECT v.id AS voter_id, nullif(v.full_name_mr, '') AS full_name_mr, nullif(v.full_name_en, '') AS full_name_en,
               v.booth_id, s.dob, s.mobile_1, {wrap} AS wrap, ({md}) AS md
          FROM app.voters v
          JOIN app.voter_surveys s ON s.tenant_id = v.tenant_id AND s.voter_id = v.id
         WHERE {' AND '.join(where)} {after}
         ORDER BY {wrap}, ({md}) COLLATE "C", v.id
         LIMIT :n
    """), {**params, "n": limit + 1}).mappings().all()

    items = [Birthday(voter_id=r["voter_id"], full_name_mr=r["full_name_mr"], full_name_en=r["full_name_en"],
                      booth_id=r["booth_id"], dob=r["dob"], mobile_1=r["mobile_1"],
                      turns=_turns(r["dob"], date_from, r["wrap"])) for r in rows[:limit]]
    last = rows[limit - 1] if len(rows) > limit else None
    return BirthdayPage(items=items,
                        next_cursor=encode_cursor([last["wrap"], last["md"], str(last["voter_id"])]) if last else None)


def _turns(dob: date, start: date, wrap: int) -> int:
    """Age on the birthday that falls in the range (the year of date_from, or the next one after the year end)."""
    return start.year + wrap - dob.year

