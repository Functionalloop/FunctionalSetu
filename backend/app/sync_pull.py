"""GET /sync/pull: the first download (no `since`) and the delta pull (`since=W`), in pages.

Page 1: settings, lists, areas, `area_ids`, totals and a new watermark W'.
Then phases, each keyset-paged by id:
    voters    first download: every voter in the area (removed ones left out)
              delta: voters in the area with sync_xid >= since, removed ones included (deleted_at set)
    surveys   surveys of voters in the area (delta: sync_xid >= since)
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
from .routers.voters import SURVEY_COLUMNS
from .schemas import (ColorTag, CustomFieldLabel, NamedListEntry, Survey, SyncArea, SyncLists, SyncPage,
                      SyncVoter)
from .scope import Scope
from .workspace_settings import load_workspace_settings

FIRST_PHASES = ("voters", "surveys")
DELTA_PHASES = ("voters", "surveys", "gone")
WATERMARK_PATTERN = r"^[0-9]{1,20}$"
_WATERMARK_RE = re.compile(WATERMARK_PATTERN)

VOTER_COLS = ", ".join(f"v.{c}" for c in SyncVoter.model_fields)
SURVEY_COLS = ", ".join(f"s.{c}" for c in SURVEY_COLUMNS)
_AREA_COLS = ", ".join(f"g.{c}" for c in SyncArea.model_fields)
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
    """Castes, professions, colour tags and custom field labels (RLS: this workspace), inactive included.
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
    )


def _first_page(conn: Connection, scope: Scope, since: str | None) -> SyncPage:
    watermark = current_watermark(conn)
    gcond, gparams = scope.filter("g.path")
    areas = _rows(conn, f"""
        SELECT {_AREA_COLS}, {_changed("g", since)} AS changed
          FROM app.geo_units g WHERE g.is_active AND {gcond}
         ORDER BY nlevel(g.path), g.sort_order, g.number NULLS LAST, g.code
    """, {**gparams, "since": since})

    vcond, vparams = scope.filter("v.geo_path")
    vparams["since"] = since
    voters_where = f"v.deleted_at IS NULL AND {vcond}" if since is None else f"{_changed('v', since)} AND {vcond}"
    total_voters = conn.execute(text(f"SELECT count(*) FROM app.voters v WHERE {voters_where}"), vparams).scalar_one()
    total_surveys = conn.execute(text(f"""
        SELECT count(*) FROM app.voter_surveys s JOIN app.voters v ON v.tenant_id = s.tenant_id AND v.id = s.voter_id
         WHERE v.deleted_at IS NULL AND {_changed('s', since)} AND {vcond}
    """), vparams).scalar_one()

    settings_changed = since is None or bool(conn.execute(
        text(f"SELECT EXISTS (SELECT 1 FROM app.tenant_settings WHERE {_changed('', since)})"),
        {"since": since}).scalar())
    phases = FIRST_PHASES if since is None else DELTA_PHASES
    # Only phases that have rows are visited (the cursor carries the list), so an idle delta pull
    # is a single request and a small one is page 1 plus one page per phase with rows.
    gone = 0 if since is None else conn.execute(text(
        f"SELECT count(*) FROM app.voters v WHERE {_changed('v', since)} AND NOT ({vcond})"), vparams).scalar_one()
    todo = {"voters": total_voters, "surveys": total_surveys, "gone": gone}
    with_rows = [p for p in phases if todo[p] > 0]
    return SyncPage(
        watermark=watermark,
        next_cursor=_cursor(with_rows, None, watermark, since),
        settings=load_workspace_settings(conn) if settings_changed else None,
        lists=load_lists(conn, since),
        areas=[SyncArea(**{k: v for k, v in a.items() if k != "changed"}) for a in areas if a["changed"]],
        area_ids=[a["id"] for a in areas],
        total_voters=total_voters, total_surveys=total_surveys)


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


def pull_page(conn: Connection, scope: Scope, since: str | None, cursor: str | None, limit: int) -> SyncPage:
    """One page of a first download (since=None) or of a delta pull."""
    if cursor is None:
        return _first_page(conn, scope, since)
    phases_left, after, watermark, since = _read_cursor(cursor)
    phase = phases_left[0]

    cond, params = scope.filter("v.geo_path")
    params.update(after=after, limit=limit + 1, since=since)
    if phase == "voters":
        key, select, source = "v.id", VOTER_COLS, "app.voters v"
        where = f"v.deleted_at IS NULL AND {cond}" if since is None else f"{_changed('v', since)} AND {cond}"
    elif phase == "surveys":
        key, select = "s.voter_id", SURVEY_COLS
        source = "app.voter_surveys s JOIN app.voters v ON v.tenant_id = s.tenant_id AND v.id = s.voter_id"
        where = f"v.deleted_at IS NULL AND {_changed('s', since)} AND {cond}"
    else:  # gone: changed since W and now outside the area (ids only)
        key, select, source = "v.id", "v.id", "app.voters v"
        where = f"{_changed('v', since)} AND NOT ({cond})"
    after_sql = f"AND {key} > :after" if after is not None else ""
    rows = _rows(conn, f"SELECT {select} FROM {source} WHERE {where} {after_sql} ORDER BY {key} LIMIT :limit",
                 params)

    more = len(rows) > limit
    rows = rows[:limit]
    if more:
        last = rows[-1]["voter_id" if phase == "surveys" else "id"]
        next_cursor = _cursor(phases_left, str(last), watermark, since)
    else:
        next_cursor = _cursor(phases_left[1:], None, watermark, since)

    page = SyncPage(watermark=watermark, next_cursor=next_cursor)
    if phase == "voters":
        page.voters = [SyncVoter(**r) for r in rows]
    elif phase == "surveys":
        page.surveys = [Survey(**r) for r in rows]
    else:
        page.gone_voter_ids = [r["id"] for r in rows]
    return page
