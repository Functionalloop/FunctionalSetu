"""GET /sync/pull without `since`: the first download of a phone's area, in pages.

Page order: (1) settings, lists, areas and totals; (2) voters by id; (3) surveys by voter id.
The watermark W is taken once, on the first page, and carried in the cursor, so every page
of one download returns the same W. Pages after the first run in later transactions and so
see everything committed up to then: a row changed while the phone is still downloading
either arrives in a later page or (sync_xid >= W) in the first delta pull. It may arrive
twice; the phone replaces rows by id, so that is harmless.
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

PHASES = ("voters", "surveys")
_WATERMARK_RE = re.compile(r"^[0-9]{1,20}$")

VOTER_COLS = ", ".join(f"v.{c}" for c in SyncVoter.model_fields)
SURVEY_COLS = ", ".join(f"s.{c}" for c in SURVEY_COLUMNS)
_AREA_COLS = ", ".join(f"g.{c}" for c in SyncArea.model_fields)
_NAMED = "id, name_mr, name_en, name_hi, sort_order, is_active"


def current_watermark(conn: Connection) -> str:
    return conn.execute(text("SELECT app.sync_watermark()::text")).scalar_one()


def _rows(conn: Connection, sql: str, params: dict | None = None) -> list[Any]:
    return list(conn.execute(text(sql), params or {}).mappings().all())


def load_lists(conn: Connection) -> SyncLists:
    """Castes, professions, colour tags and custom field labels of the workspace (RLS), inactive included."""
    return SyncLists(
        castes=[NamedListEntry(**r) for r in _rows(
            conn, f"SELECT {_NAMED} FROM app.castes ORDER BY sort_order, name_mr")],
        professions=[NamedListEntry(**r) for r in _rows(
            conn, f"SELECT {_NAMED} FROM app.professions ORDER BY sort_order, name_mr")],
        color_tags=[ColorTag(**r) for r in _rows(
            conn, f"SELECT {', '.join(ColorTag.model_fields)} FROM app.color_tags ORDER BY sort_order, code")],
        custom_field_labels=[CustomFieldLabel(**r) for r in _rows(
            conn, "SELECT field_key::text AS field_key, label_mr, label_en, label_hi, is_enabled "
                  "FROM app.custom_field_labels ORDER BY field_key")],
    )


def load_areas(conn: Connection, scope: Scope) -> list[SyncArea]:
    cond, params = scope.filter("g.path")
    return [SyncArea(**a) for a in _rows(conn, f"""
        SELECT {_AREA_COLS} FROM app.geo_units g WHERE g.is_active AND {cond}
         ORDER BY nlevel(g.path), g.sort_order, g.number NULLS LAST, g.code
    """, params)]


def _first_page(conn: Connection, scope: Scope) -> SyncPage:
    watermark = current_watermark(conn)
    cond, params = scope.filter("v.geo_path")
    total_voters, total_surveys = conn.execute(text(f"""
        SELECT count(*), count(s.voter_id)
          FROM app.voters v
          LEFT JOIN app.voter_surveys s ON s.tenant_id = v.tenant_id AND s.voter_id = v.id
         WHERE v.deleted_at IS NULL AND {cond}
    """), params).one()
    return SyncPage(watermark=watermark, next_cursor=encode_cursor([PHASES[0], None, watermark]),
                    settings=load_workspace_settings(conn), lists=load_lists(conn), areas=load_areas(conn, scope),
                    total_voters=total_voters, total_surveys=total_surveys)


def _read_cursor(cursor: str) -> tuple[str, uuid.UUID | None, str]:
    phase, after, watermark = decode_cursor(cursor, 3)
    if phase not in PHASES or not isinstance(watermark, str) or not _WATERMARK_RE.match(watermark):
        raise invalid_cursor()
    try:
        return phase, (uuid.UUID(after) if after is not None else None), watermark
    except (TypeError, ValueError, AttributeError):
        raise invalid_cursor() from None


def first_download_page(conn: Connection, scope: Scope, cursor: str | None, limit: int) -> SyncPage:
    if cursor is None:
        return _first_page(conn, scope)
    phase, after, watermark = _read_cursor(cursor)

    cond, params = scope.filter("v.geo_path")
    params.update(after=after, limit=limit + 1)
    if phase == "voters":
        key, select, source = "v.id", VOTER_COLS, "app.voters v"
    else:
        key, select = "s.voter_id", SURVEY_COLS
        source = "app.voter_surveys s JOIN app.voters v ON v.tenant_id = s.tenant_id AND v.id = s.voter_id"
    after_sql = f"AND {key} > :after" if after is not None else ""
    rows = _rows(conn, f"""
        SELECT {select} FROM {source}
         WHERE v.deleted_at IS NULL AND {cond} {after_sql}
         ORDER BY {key}
         LIMIT :limit
    """, params)

    more = len(rows) > limit
    rows = rows[:limit]
    if more:
        last = rows[-1]["id" if phase == "voters" else "voter_id"]
        next_cursor: str | None = encode_cursor([phase, str(last), watermark])
    else:
        nxt = PHASES.index(phase) + 1
        next_cursor = encode_cursor([PHASES[nxt], None, watermark]) if nxt < len(PHASES) else None

    page = SyncPage(watermark=watermark, next_cursor=next_cursor)
    if phase == "voters":
        page.voters = [SyncVoter(**r) for r in rows]
    else:
        page.surveys = [Survey(**r) for r in rows]
    return page
