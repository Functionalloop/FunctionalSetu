"""GET /sync/pull: the first download (no `since`) and the delta pull (`since=W`), in pages.

Page 1: settings, lists, areas, `area_ids`, totals and a new watermark W'.
Then phases, each keyset-paged by id:
    voters    first download: every voter in the area (removed ones left out)
              delta: voters in the area with sync_xid >= since, removed ones included (deleted_at set)
    surveys   surveys of voters in the area (delta: sync_xid >= since, or the voter's; also for members
              and turnout, so a restored voter gets its rows back)
    families  Kutumbs whose booth is in the area (first: not deleted; delta: sync_xid >= since, deleted included)
    visits    visits in the user's booths (first: all not deleted; delta: sync_xid >= since)
    members   family_members of voters in the area (first: in a Kutumb; delta: sync_xid >= since, also the
              rows with family_id null = taken out)
    new_voters Eligible but Not Registered whose part (or Village Panchayat, with no part) is in the area;
              survey roles only (a booth agent gets none). First: not deleted; delta: sync_xid >= since
    part_notes the shared note of each part in the area (7.11; first: all; delta: sync_xid >= since); all roles
    turnout   voted marks of voters in the area (8.1); polling-day roles only (a surveyor gets none).
              First: voted ones; delta: sync_xid >= since, undone ones included (is_voted false)
    gone      delta only: ids of voters changed since W that are now outside the area
W' is taken once, on page 1, and carried in the cursor with `since`, so every page of one pull
returns the same W'. Later pages run in later transactions and see everything committed up to
then; anything written after page 1 has sync_xid >= W' and comes again in the next delta pull.
Rows may arrive twice; the phone replaces them by id. How the phone uses this: context/sync.md.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import Connection, text

from .paging import decode_cursor, encode_cursor, invalid_cursor
from .routers.turnout import MARK_COLS
from .routers.voters import SURVEY_COLUMNS
from .schemas import (ColorTag, CustomFieldLabel, NamedListEntry, NewVoter, Survey, SyncArea, SyncFamily,
                      SyncFamilyMember, SyncLists, SyncPage, SyncVoter, TurnoutMark, Visit)
from .schemas_field import PartNote
from .scope import Scope
from .workspace_settings import load_workspace_settings

FIRST_PHASES = ("voters", "surveys", "families", "members", "visits", "new_voters", "part_notes", "turnout")
DELTA_PHASES = ("voters", "surveys", "families", "members", "visits", "new_voters", "part_notes", "turnout", "gone")
WATERMARK_PATTERN = r"^[0-9]{1,20}$"
_WATERMARK_RE = re.compile(WATERMARK_PATTERN)

VOTER_COLS = ", ".join(f"v.{c}" for c in SyncVoter.model_fields)
SURVEY_COLS = ", ".join(f"s.{c}" for c in SURVEY_COLUMNS)
_AREA_COLS = ", ".join(f"g.{c}" for c in SyncArea.model_fields)
FAMILY_COLS = ", ".join(f"f.{c}" for c in SyncFamily.model_fields)
MEMBER_COLS = ", ".join(f"m.{c}" for c in SyncFamilyMember.model_fields)
VISIT_COLS = ", ".join(f"t.{c}" for c in Visit.model_fields)
NEW_VOTER_COLS = ", ".join(f"n.{c}" for c in NewVoter.model_fields)
PART_NOTE_COLS = ", ".join(f"p.{c}" for c in PartNote.model_fields)
_NAMED = "id, name_mr, name_en, name_hi, sort_order, is_active"


def current_watermark(conn: Connection) -> str:
    return conn.execute(text("SELECT app.sync_watermark()::text")).scalar_one()


def _rows(conn: Connection, sql: str, params: dict | None = None) -> list[Any]:
    return list(conn.execute(text(sql), params or {}).mappings().all())


def _changed(alias: str, since: str | None) -> str:
    """SQL: the row changed since the watermark (always true on a first download)."""
    prefix = f"{alias}." if alias else ""
    return f"{prefix}sync_xid >= CAST(:since AS xid8)" if since is not None else "TRUE"


def load_lists(conn: Connection, since: str | None = None) -> SyncLists:
    """Castes, professions, colour tags, custom field labels and influencer types
    (RLS: this workspace), inactive included.
    With `since`: only entries changed since then."""
    p = {"since": since}
    ch = _changed("", since)
    return SyncLists(
        castes=[NamedListEntry(**r) for r in _rows(
            conn, f"SELECT {_NAMED} FROM app.castes WHERE {ch} ORDER BY sort_order, name_mr", p)],
        professions=[NamedListEntry(**r) for r in _rows(
            conn, f"SELECT {_NAMED} FROM app.professions WHERE {ch} ORDER BY sort_order, name_mr", p)],
        color_tags=[ColorTag(**r) for r in _rows(
            conn, f"SELECT {', '.join(ColorTag.model_fields)} FROM app.color_tags WHERE {ch} ORDER BY sort_order, code",
            p)],
        custom_field_labels=[CustomFieldLabel(**r) for r in _rows(
            conn, f"SELECT field_key::text AS field_key, label_mr, label_en, label_hi, is_enabled "
                  f"FROM app.custom_field_labels WHERE {ch} ORDER BY field_key", p)],
        influencer_types=[NamedListEntry(**r) for r in _rows(
            conn, f"SELECT {_NAMED} FROM app.influencer_types WHERE {ch} ORDER BY sort_order, name_mr", p)],
    )


def _first_page(conn: Connection, scope: Scope, since: str | None, survey_role: bool,
                polling_role: bool) -> SyncPage:
    watermark = current_watermark(conn)
    gcond, gparams = scope.filter("g.path")
    areas = _rows(conn, f"""
        SELECT {_AREA_COLS}, {_changed("g", since)} AS changed
          FROM app.geo_units g WHERE g.is_active AND {gcond}
         ORDER BY nlevel(g.path), g.sort_order, g.number NULLS LAST, g.code
    """, {**gparams, "since": since})

    phases = FIRST_PHASES if since is None else DELTA_PHASES
    todo = {}
    for p in phases:
        q = _phase(p, scope, since, survey_role, polling_role)
        todo[p] = conn.execute(text(f"SELECT count(*) FROM {q.source} WHERE {q.where}"), q.params).scalar_one()

    settings_changed = since is None or bool(conn.execute(
        text(f"SELECT EXISTS (SELECT 1 FROM app.tenant_settings WHERE {_changed('', since)})"),
        {"since": since}).scalar())
    # Only phases that have rows are visited (the cursor carries the list), so an idle delta pull
    # is a single request and a small one is page 1 plus one page per phase with rows.
    with_rows = [p for p in phases if todo[p] > 0]
    return SyncPage(
        watermark=watermark,
        next_cursor=_cursor(with_rows, None, watermark, since),
        settings=load_workspace_settings(conn) if settings_changed else None,
        lists=load_lists(conn, since),
        areas=[SyncArea(**{k: v for k, v in a.items() if k != "changed"}) for a in areas if a["changed"]],
        area_ids=[a["id"] for a in areas],
        total_voters=todo["voters"], total_surveys=todo["surveys"], total_families=todo["families"])


class _PhaseSql:
    """FROM and WHERE of one phase, its sort key and the column the cursor keeps."""

    def __init__(self, source: str, where: str, params: dict, key: str, select: str, id_field: str):
        self.source, self.where, self.params, self.key, self.select, self.id_field = (
            source, where, params, key, select, id_field)


def _changed_or_voter(alias: str, since: str | None) -> str:
    """SQL for a voter's own rows (survey, Kutumb membership, voted mark): the row changed since the
    watermark, or its voter did. A voter that comes back (restored, 10.4; moved into the area by a
    roll) was dropped on the phone with these rows, so they must come again although they did not change."""
    if since is None:
        return "TRUE"
    return f"({_changed(alias, since)} OR {_changed('v', since)})"


def _phase(phase: str, scope: Scope, since: str | None, survey_role: bool, polling_role: bool) -> _PhaseSql:
    vcond, params = scope.filter("v.geo_path")
    params["since"] = since
    with_voter = "JOIN app.voters v ON v.tenant_id = {a}.tenant_id AND v.id = {a}.voter_id"
    if phase == "voters":
        where = f"v.deleted_at IS NULL AND {vcond}" if since is None else f"{_changed('v', since)} AND {vcond}"
        return _PhaseSql("app.voters v", where, params, "v.id", VOTER_COLS, "id")
    if phase == "surveys":
        return _PhaseSql(f"app.voter_surveys s {with_voter.format(a='s')}",
                         f"v.deleted_at IS NULL AND {_changed_or_voter('s', since)} AND {vcond}", params,
                         "s.voter_id", SURVEY_COLS, "voter_id")
    if phase == "families":  # seen through its booth, like GET /booths/{id}/families
        gcond, gparams = scope.filter("g.path")
        where = f"f.deleted_at IS NULL AND {gcond}" if since is None else f"{_changed('f', since)} AND {gcond}"
        return _PhaseSql("app.families f JOIN app.geo_units g ON g.tenant_id = f.tenant_id AND g.id = f.booth_id",
                         where, {**gparams, "since": since}, "f.id", FAMILY_COLS, "id")
    if phase == "visits":  # through the booth too; no delete route, so deleted rows never go out
        gcond, gparams = scope.filter("g.path")
        return _PhaseSql("app.visits t JOIN app.geo_units g ON g.tenant_id = t.tenant_id AND g.id = t.booth_id",
                         f"t.deleted_at IS NULL AND {_changed('t', since)} AND {gcond}", {**gparams, "since": since},
                         "t.id", VISIT_COLS, "id")
    if phase == "new_voters":  # through its part, else its Village Panchayat (routers/new_voters.py)
        gcond, gparams = scope.filter("g.path")
        role = "" if survey_role else "FALSE AND "
        return _PhaseSql("app.new_voters n JOIN app.geo_units g ON g.tenant_id = n.tenant_id "
                         "AND g.id = coalesce(n.booth_id, n.ward_id)",
                         f"{role}n.deleted_at IS NULL AND {_changed('n', since)} AND {gcond}",
                         {**gparams, "since": since}, "n.id", NEW_VOTER_COLS, "id")
    if phase == "part_notes":  # through its booth; booth agents read them too
        gcond, gparams = scope.filter("g.path")
        return _PhaseSql("app.part_notes p JOIN app.geo_units g ON g.tenant_id = p.tenant_id AND g.id = p.booth_id",
                         f"{_changed('p', since)} AND {gcond}", {**gparams, "since": since}, "p.booth_id",
                         PART_NOTE_COLS, "booth_id")
    if phase == "turnout":  # through the voter; polling-day roles only
        role = "" if polling_role else "FALSE AND "
        first = "t.is_voted" if since is None else _changed_or_voter("t", since)
        return _PhaseSql(f"app.voter_turnout t {with_voter.format(a='t')}",
                         f"{role}{first} AND v.deleted_at IS NULL AND {vcond}", params, "t.voter_id", MARK_COLS,
                         "voter_id")
    if phase == "members":
        first = "m.family_id IS NOT NULL" if since is None else _changed_or_voter("m", since)
        return _PhaseSql(f"app.family_members m {with_voter.format(a='m')}",
                         f"{first} AND v.deleted_at IS NULL AND {vcond}", params, "m.voter_id", MEMBER_COLS,
                         "voter_id")
    # gone: changed since W and now outside the area (ids only)
    return _PhaseSql("app.voters v", f"{_changed('v', since)} AND NOT ({vcond})", params, "v.id", "v.id", "id")


def _cursor(phases_left: list[str], after: str | None, watermark: str, since: str | None) -> str | None:
    """Cursor [phases still to send (current first), last id sent, W, since]; None when nothing is left."""
    return encode_cursor([phases_left, after, watermark, since]) if phases_left else None


def _read_cursor(cursor: str) -> tuple[list[str], uuid.UUID | None, str, str | None]:
    phases_left, after, watermark, since = decode_cursor(cursor, 4)
    allowed = FIRST_PHASES if since is None else DELTA_PHASES
    for w in (watermark, since):
        if w is not None and (not isinstance(w, str) or not _WATERMARK_RE.match(w)):
            raise invalid_cursor()
    if (watermark is None or not isinstance(phases_left, list) or not phases_left
            or any(p not in allowed for p in phases_left)):
        raise invalid_cursor()
    try:
        return phases_left, (uuid.UUID(after) if after is not None else None), watermark, since
    except (TypeError, ValueError, AttributeError):
        raise invalid_cursor() from None


def pull_page(conn: Connection, scope: Scope, since: str | None, cursor: str | None, limit: int,
              survey_role: bool = True, polling_role: bool = True) -> SyncPage:
    """One page of a first download (since=None) or of a delta pull. survey_role: False for a booth agent
    (no Eligible but Not Registered records); polling_role: False for a surveyor (no voted marks)."""
    if cursor is None:
        return _first_page(conn, scope, since, survey_role, polling_role)
    phases_left, after, watermark, since = _read_cursor(cursor)
    phase = phases_left[0]

    q = _phase(phase, scope, since, survey_role, polling_role)
    after_sql = f"AND {q.key} > :after" if after is not None else ""
    rows = _rows(conn, f"SELECT {q.select} FROM {q.source} WHERE {q.where} {after_sql} ORDER BY {q.key} LIMIT :limit",
                 {**q.params, "after": after, "limit": limit + 1})

    more = len(rows) > limit
    rows = rows[:limit]
    if more:
        last = rows[-1][q.id_field]
        next_cursor = _cursor(phases_left, str(last), watermark, since)
    else:
        next_cursor = _cursor(phases_left[1:], None, watermark, since)

    page = SyncPage(watermark=watermark, next_cursor=next_cursor)
    if phase == "voters":
        page.voters = [SyncVoter(**r) for r in rows]
    elif phase == "surveys":
        page.surveys = [Survey(**r) for r in rows]
    elif phase == "families":
        page.families = [SyncFamily(**r) for r in rows]
    elif phase == "members":
        page.family_members = [SyncFamilyMember(**r) for r in rows]
    elif phase == "visits":
        page.visits = [Visit(**r) for r in rows]
    elif phase == "new_voters":
        page.new_voters = [NewVoter(**r) for r in rows]
    elif phase == "part_notes":
        page.part_notes = [PartNote(**r) for r in rows]
    elif phase == "turnout":
        page.turnout = [TurnoutMark(**r) for r in rows]
    else:
        page.gone_voter_ids = [r["id"] for r in rows]
    return page
