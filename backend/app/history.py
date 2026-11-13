"""Information Updation (plan 7.6): every change to one voter, newest first.

Sources:
  audit_log  (written by the audit triggers; entity_id = the voter's id)
    voter_surveys  -> kind "survey"    (survey fields and notes)
    family_members -> kind "family"    (put in / taken out of a Kutumb)
    voter_turnout  -> kind "voted"
    voters         -> kind "roll_edit" (roll corrections by a super admin; bulk imports skip the audit)
  visits       -> kind "visit"  (visits have no audit trigger; one entry per visit, at the visit time)
  slip_events  -> kind "slip"   (action = the channel)

Entries are paged by (at, key) newest first; key breaks ties and is unique per source row.
Reference fields (caste, colour tag, Kutumb, user, ...) get `old_label` / `new_label` next to the id.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from .paging import decode_cursor, encode_cursor, invalid_cursor
from .schemas import UserSummary
from .schemas_field import HistoryEntry, HistoryPage

KINDS = {"voter_surveys": "survey", "family_members": "family", "voter_turnout": "voted", "voters": "roll_edit"}

# Bookkeeping columns that are not information about the voter (who / when is the entry's own `by` / `at`).
HIDDEN = frozenset({
    "id", "tenant_id", "voter_id", "created_at", "updated_at", "deleted_at", "sync_xid", "version",
    "created_by", "updated_by", "updated_device_id", "device_id", "client_mutation_id",
    "search_text", "full_name_en", "full_name_mr", "geo_path", "first_roll_version_id", "last_roll_version_id",
    "legacy_id", "photo_file_id",
    "is_surveyed", "surveyed_at", "location_accuracy_m", "location_captured_at",
    "is_important", "position_id",  # no longer used (7.13); old audit rows still carry them
    "marked_by", "marked_at", "cleared_by", "cleared_at",  # voted: the entry's by / at
})

_USER = "users", "full_name_en"
REFS: dict[str, tuple[str, str]] = {
    "caste_id": ("castes", "coalesce(name_en, name_mr)"),
    "profession_id": ("professions", "coalesce(name_en, name_mr)"),
    "color_tag_id": ("color_tags", "label_en"),
    "influencer_type_id": ("influencer_types", "coalesce(name_en, name_mr)"),
    "karyakarta_id": ("karyakartas", "name_en"),
    "family_id": ("families", "label"),
    "dead_marked_by": _USER, "dead_confirmed_by": _USER, "last_visited_by": _USER,
    "local_body_id": ("geo_units", "coalesce(name_en, name_mr)"),
    "ward_id": ("geo_units", "coalesce(name_en, name_mr)"),
    "booth_id": ("geo_units", "coalesce(name_en, name_mr)"),
    "section_id": ("geo_units", "coalesce(name_en, name_mr)"),
}

_SQL = """
WITH h AS (
  SELECT a.occurred_at AS at, 'a' || lpad(a.id::text, 19, '0') AS k,
         CASE a.entity_type WHEN 'voter_surveys' THEN 'survey' WHEN 'family_members' THEN 'family'
                            WHEN 'voter_turnout' THEN 'voted' ELSE 'roll_edit' END AS kind,
         a.action, a.actor_user_id AS by_id, a.old_values, a.new_values
    FROM app.audit_log a
   WHERE a.entity_type IN ('voter_surveys', 'family_members', 'voter_turnout', 'voters')
     AND a.entity_id = :vid_text
  UNION ALL
  SELECT t.visited_at, 'v' || t.id::text, 'visit', 'insert', t.visited_by, NULL,
         jsonb_build_object('outcome', t.outcome, 'revisit_at', t.revisit_at, 'note', t.note)
    FROM app.visits t
   WHERE t.voter_id = :vid AND t.deleted_at IS NULL
  UNION ALL
  SELECT e.created_at, 's' || lpad(e.id::text, 19, '0'), 'slip', e.channel::text, e.created_by, NULL, NULL
    FROM app.slip_events e
   WHERE e.voter_id = :vid
)
SELECT h.at, h.k, h.kind, h.action, h.old_values, h.new_values,
       u.id AS u_id, u.username, u.full_name_en, u.full_name_mr, u.role
  FROM h LEFT JOIN app.users u ON u.id = h.by_id
 WHERE {after}
 ORDER BY h.at DESC, h.k COLLATE "C" DESC
 LIMIT :n
"""


def _changes(action: str, old: dict | None, new: dict | None) -> dict[str, dict[str, Any]]:
    """field -> {old, new}. An update row holds only the changed columns; an insert or delete holds
    the whole row, of which the fields with a value are shown (false / empty = nothing to say)."""
    old, new = old or {}, new or {}
    if action == "update":
        keys = list(new)
    else:
        whole = new if action != "delete" else old
        keys = [k for k, v in whole.items() if v not in (None, False, "")]
    return {k: {"old": old.get(k), "new": new.get(k)} for k in keys if k not in HIDDEN}


def _is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


def _add_labels(conn: Connection, entries: list[HistoryEntry]) -> None:
    wanted: dict[str, set[str]] = {}
    for e in entries:
        for field, ch in e.changes.items():
            if field in REFS:
                table, _ = REFS[field]
                wanted.setdefault(table, set()).update(
                    str(v) for v in (ch["old"], ch["new"]) if v is not None and _is_uuid(v))
    exprs = {table: expr for table, expr in REFS.values()}
    names: dict[str, dict[str, str]] = {}
    for table, ids in wanted.items():
        rows = conn.execute(text(f"SELECT id::text, {exprs[table]} FROM app.{table} WHERE id = ANY(CAST(:ids AS uuid[]))"),
                            {"ids": sorted(ids)}).all()
        names[table] = {r[0]: r[1] for r in rows if r[1] is not None}
    for e in entries:
        for field, ch in e.changes.items():
            if field in REFS:
                found = names.get(REFS[field][0], {})
                for side in ("old", "new"):
                    if ch[side] is not None and str(ch[side]) in found:
                        ch[f"{side}_label"] = found[str(ch[side])]


def voter_history(conn: Connection, voter_id: uuid.UUID, limit: int, cursor: str | None) -> HistoryPage:
    params: dict[str, Any] = {"vid": voter_id, "vid_text": str(voter_id), "n": limit + 1}
    after = "TRUE"
    if cursor:
        at, k = decode_cursor(cursor, 2)
        try:
            params["c_at"], params["c_k"] = datetime.fromisoformat(str(at)), str(k)
        except ValueError:
            raise invalid_cursor() from None
        after = '(h.at, h.k COLLATE "C") < (:c_at, CAST(:c_k AS text) COLLATE "C")'
    rows = conn.execute(text(_SQL.format(after=after)), params).mappings().all()

    entries = [HistoryEntry(
        at=r["at"], kind=r["kind"], action=r["action"],
        by=UserSummary(id=r["u_id"], username=r["username"], full_name_en=r["full_name_en"],
                       full_name_mr=r["full_name_mr"], role=r["role"]) if r["u_id"] else None,
        changes=_changes(r["action"], r["old_values"], r["new_values"]),
    ) for r in rows[:limit]]
    _add_labels(conn, entries)
    more = len(rows) > limit
    last = rows[limit - 1] if more else None
    return HistoryPage(items=entries,
                       next_cursor=encode_cursor([last["at"].isoformat(), last["k"]]) if last else None)
