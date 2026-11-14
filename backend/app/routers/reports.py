"""Reports (plan 11.1) and exports (11.2). Supervisor and above, for their own area.

Reports count the voters of the caller's area (app/scope.py). `ward_id` narrows it to that area and
everything below it (a booth id works too); demographics also takes `booth_id`. Outside the area: 404.

- Voters counted: not removed (deleted_at), i.e. the voters GET /voters lists (also those absent from
  the current roll), so a report's number equals the list it leads to. Turnout counts only voters on
  the current roll (roll_status active), like GET /turnout/summary and the marks themselves.
- Surveyed = voter_surveys.is_surveyed (the survey_status filter of GET /voters).
- by_area: the active wards and booths in the area, each ward followed by its booths (`parent_id`).
  A ward is listed only when it is in the area itself (a user with one booth of a ward gets the booth,
  not the ward). Totals are counted from the voters, never added up from the rows.
- Colour tags: counts above zero only; color_tag_id null = no tag (also never surveyed). Order: the
  tags' sort order, null last. by_area has a key for every listed area (an empty list = no voters).
- Age bands: the roll's age (voters.age), not the survey's date of birth. Every band in AGE_BANDS is
  listed, zeros included; "unknown" (no age on the roll) only when there is one.
- Turnout by hour: standing marks by the Indian hour of marked_at, from the first hour with a mark to
  the last, zeros filled in between; `cumulative` adds up. Rehearsal marks count until they are undone.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from typing import Any

from fastapi import APIRouter, Response, status
from sqlalchemy import Connection, text

from ..deps import Db
from ..schemas_roll import (AgeBand, AreaCount, ColorTagCount, ColorTagReport, Demographics, Export, ExportIn,
                            SurveyProgress, TurnoutHour, TurnoutReport)
from ..scope import Scope, UserScope, require_area
from ..stubs import NOT_BUILT, Supervisor, not_built

router = APIRouter(tags=["reports"])

AGE_BANDS: list[tuple[int, int | None]] = [(18, 25), (26, 35), (36, 45), (46, 55), (56, 65), (66, 75), (76, None)]
UNKNOWN_AGE = "unknown"
_IST = "'Asia/Kolkata'"

Key = tuple[uuid.UUID, uuid.UUID]   # (ward_id, booth_id) of a group of voters


def percent(done: int, total: int) -> float:
    return round(done * 100 / total, 1) if total else 0.0


# --- the area ----------------------------------------------------------------------------------------
def _paths(conn: Connection, scope: Scope, *areas: uuid.UUID | None) -> list[str]:
    """The ltree paths of the narrowing areas given (404 outside the caller's area)."""
    return [require_area(conn, scope, a) for a in areas if a is not None]


def _voters_where(scope: Scope, paths: list[str]) -> tuple[str, dict[str, Any]]:
    cond, params = scope.filter("v.geo_path")
    where = ["v.deleted_at IS NULL", cond]
    for i, path in enumerate(paths):
        params[f"area{i}"] = path
        where.append(f"v.geo_path <@ CAST(:area{i} AS ltree)")
    return " AND ".join(where), params


def _areas(conn: Connection, scope: Scope, paths: list[str]) -> list[Any]:
    """Active wards and booths in the area, each ward followed by its booths."""
    cond, params = scope.filter("g.path")
    where = ["g.level IN ('ward', 'booth')", "g.is_active", cond]
    for i, path in enumerate(paths):
        params[f"area{i}"] = path
        where.append(f"g.path <@ CAST(:area{i} AS ltree)")
    rows = conn.execute(text(f"""
        SELECT g.id, g.parent_id, g.level::text AS level, coalesce(nullif(g.name_en, ''), g.name_mr) AS name,
               g.sort_order, g.number, g.code
          FROM app.geo_units g WHERE {' AND '.join(where)}"""), params).mappings().all()

    def order(r: Any) -> tuple[Any, ...]:
        return r["sort_order"], r["number"] is None, r["number"] or 0, r["code"]

    wards = sorted((r for r in rows if r["level"] == "ward"), key=order)
    booths = sorted((r for r in rows if r["level"] == "booth"), key=order)
    under: dict[uuid.UUID, list[Any]] = defaultdict(list)
    for b in booths:
        under[b["parent_id"]].append(b)
    out: list[Any] = []
    for w in wards:
        out += [w, *under.pop(w["id"], [])]
    return out + [b for b in booths if b["parent_id"] in under]   # booths whose ward is not in the area


def _per_area(counts: dict[Key, int]) -> Counter[uuid.UUID]:
    """Voter counts by (ward, booth) -> by area id (wards and booths)."""
    out: Counter[uuid.UUID] = Counter()
    for (ward, booth), n in counts.items():
        out[ward] += n
        out[booth] += n
    return out


def _grouped(conn: Connection, sql: str, params: dict[str, Any]) -> dict[Key, int]:
    """Run a query returning (ward_id, booth_id, n) rows."""
    return {(r[0], r[1]): r[2] for r in conn.execute(text(sql), params)}


def _area_counts(areas: list[Any], total: dict[Key, int], done: dict[Key, int]) -> list[AreaCount]:
    t, d = _per_area(total), _per_area(done)
    return [AreaCount(area_id=a["id"], parent_id=a["parent_id"] if a["level"] == "booth" else None,
                      name=a["name"], level=a["level"], total=t[a["id"]], done=d[a["id"]],
                      percent=percent(d[a["id"]], t[a["id"]])) for a in areas]


# --- reports -----------------------------------------------------------------------------------------
@router.get("/reports/survey-progress", response_model=SurveyProgress,
            summary="Surveyed vs total by ward and booth. Supervisor.")
def survey_progress(conn: Db, user: Supervisor, scope: UserScope, ward_id: uuid.UUID | None = None) -> SurveyProgress:
    paths = _paths(conn, scope, ward_id)
    where, params = _voters_where(scope, paths)
    rows = conn.execute(text(f"""
        SELECT v.ward_id, v.booth_id, count(*) AS total, count(*) FILTER (WHERE s.is_surveyed) AS done
          FROM app.voters v
          LEFT JOIN app.voter_surveys s ON s.tenant_id = v.tenant_id AND s.voter_id = v.id
         WHERE {where} GROUP BY v.ward_id, v.booth_id"""), params).all()
    total = {(r.ward_id, r.booth_id): r.total for r in rows}
    done = {(r.ward_id, r.booth_id): r.done for r in rows}
    t, d = sum(total.values()), sum(done.values())
    return SurveyProgress(total=t, surveyed=d, percent=percent(d, t),
                          by_area=_area_counts(_areas(conn, scope, paths), total, done))


@router.get("/reports/colour-tags", response_model=ColorTagReport, summary="Counts by colour tag. Supervisor.")
def colour_tags(conn: Db, user: Supervisor, scope: UserScope, ward_id: uuid.UUID | None = None) -> ColorTagReport:
    paths = _paths(conn, scope, ward_id)
    where, params = _voters_where(scope, paths)
    rows = conn.execute(text(f"""
        SELECT v.ward_id, v.booth_id, s.color_tag_id, count(*) AS n
          FROM app.voters v
          LEFT JOIN app.voter_surveys s ON s.tenant_id = v.tenant_id AND s.voter_id = v.id
         WHERE {where} GROUP BY v.ward_id, v.booth_id, s.color_tag_id"""), params).all()
    tag_order = {r.id: (r.sort_order, r.code) for r in conn.execute(text("SELECT id, sort_order, code FROM app.color_tags"))}

    def counts(c: Counter[uuid.UUID | None]) -> list[ColorTagCount]:
        tags = sorted((t for t in c if c[t]), key=lambda t: (t is None, tag_order.get(t, (0, ""))))
        return [ColorTagCount(color_tag_id=t, count=c[t]) for t in tags]

    whole: Counter[uuid.UUID | None] = Counter()
    by_area: dict[uuid.UUID, Counter[uuid.UUID | None]] = defaultdict(Counter)
    for r in rows:
        whole[r.color_tag_id] += r.n
        by_area[r.ward_id][r.color_tag_id] += r.n
        by_area[r.booth_id][r.color_tag_id] += r.n
    return ColorTagReport(total=sum(whole.values()), by_tag=counts(whole),
                          by_area={str(a["id"]): counts(by_area[a["id"]]) for a in _areas(conn, scope, paths)})


def _label(lo: int, hi: int | None) -> str:
    return f"{lo}-{hi}" if hi is not None else f"{lo}+"


def age_band(age: int | None) -> str:
    if age is None:
        return UNKNOWN_AGE
    return next(_label(lo, hi) for lo, hi in AGE_BANDS if hi is None or age <= hi)


@router.get("/reports/demographics", response_model=Demographics, summary="Age and gender. Supervisor.")
def demographics(conn: Db, user: Supervisor, scope: UserScope, ward_id: uuid.UUID | None = None,
                 booth_id: uuid.UUID | None = None) -> Demographics:
    where, params = _voters_where(scope, _paths(conn, scope, ward_id, booth_id))
    rows = conn.execute(text(f"""
        SELECT v.gender::text AS gender, v.age, count(*) AS n FROM app.voters v
         WHERE {where} GROUP BY v.gender, v.age"""), params).all()
    bands: dict[str, Counter[str]] = {_label(lo, hi): Counter() for lo, hi in AGE_BANDS}
    gender: Counter[str] = Counter()
    for r in rows:   # "unknown" is added (last) only when a voter has no age
        bands.setdefault(age_band(r.age), Counter())[r.gender] += r.n
        gender[r.gender] += r.n
    return Demographics(total=sum(gender.values()), male=gender["M"], female=gender["F"], other=gender["O"],
                        age_bands=[AgeBand(band=b, male=c["M"], female=c["F"], other=c["O"]) for b, c in bands.items()])


@router.get("/reports/turnout", response_model=TurnoutReport,
            summary="Polling-day turnout by area and hour (voters on the current roll). Supervisor.")
def turnout_report(conn: Db, user: Supervisor, scope: UserScope, ward_id: uuid.UUID | None = None) -> TurnoutReport:
    paths = _paths(conn, scope, ward_id)
    where, params = _voters_where(scope, paths)
    where += " AND v.roll_status = 'active'"
    # Marks are counted from the marks to the voters (see GET /turnout/summary for why).
    marks = f"""FROM app.voter_turnout t JOIN app.voters v ON v.tenant_id = t.tenant_id AND v.id = t.voter_id
                WHERE t.is_voted AND {where}"""
    total = _grouped(conn, f"SELECT v.ward_id, v.booth_id, count(*) FROM app.voters v WHERE {where} "
                           "GROUP BY v.ward_id, v.booth_id", params)
    done = _grouped(conn, f"SELECT v.ward_id, v.booth_id, count(*) {marks} GROUP BY v.ward_id, v.booth_id", params)
    per_hour = dict(conn.execute(text(f"""
        SELECT extract(hour FROM t.marked_at AT TIME ZONE {_IST})::int AS hour, count(*) {marks}
         GROUP BY 1"""), params).all())
    by_hour: list[TurnoutHour] = []
    running = 0
    for hour in range(min(per_hour), max(per_hour) + 1) if per_hour else ():
        running += per_hour.get(hour, 0)
        by_hour.append(TurnoutHour(hour=hour, voted=per_hour.get(hour, 0), cumulative=running))
    t, d = sum(total.values()), sum(done.values())
    return TurnoutReport(total=t, voted=d, percent=percent(d, t),
                         by_area=_area_counts(_areas(conn, scope, paths), total, done), by_hour=by_hour)


# --- exports (11.2) ----------------------------------------------------------------------------------
@router.post("/exports", response_model=Export, status_code=status.HTTP_202_ACCEPTED, responses=NOT_BUILT,
             summary="Start a PDF or Excel export of a list (filters and columns); poll it. Supervisor.")
def start_export(body: ExportIn, conn: Db, user: Supervisor) -> Export:
    not_built("11.2")


@router.get("/exports/{export_id}", response_model=Export, responses=NOT_BUILT, summary="An export's status. Supervisor.")
def get_export(export_id: uuid.UUID, conn: Db, user: Supervisor) -> Export:
    not_built("11.2")


@router.get("/exports/{export_id}/download", response_class=Response,
            responses={**NOT_BUILT,
                       200: {"content": {"application/pdf": {}, "application/vnd.openxmlformats-officedocument."
                                                                 "spreadsheetml.sheet": {}},
                             "description": "The finished file"}},
            summary="Download a finished export. Supervisor.")
def download_export(export_id: uuid.UUID, conn: Db, user: Supervisor) -> Response:
    not_built("11.2")
