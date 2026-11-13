"""Polling day (plan 8.1): voted marks and turnout. Booth agent, supervisor, admin, super admin; not surveyor.

A mark is one app.voter_turnout row per voter (its primary key), so two phones marking the same voter
leave one mark: the first is kept, the second request reports the voter as `already`. An undo keeps
the row with is_voted = false (cleared_by, cleared_at); a later mark sets it again.

Retry safety: each voter's row stores a key made from the request id and the voter id
(`mark_key`, uuid5) in client_mutation_id (unique per workspace). The same request sent again (REST
retry, or the same mark under a new outbox item) never marks again, not even after the mark was
undone in between, and lists those voters as `marked` again. Push items are also recorded in
sync_mutations, like every other type.

The push types `voted` and `unvoted` (sync_push.py) call write_marks and undo_mark.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Response, status
from sqlalchemy import Connection, text

from ..deps import Db, Principal
from ..errors import ApiError
from ..schemas_field import TurnoutBooth, TurnoutMark, TurnoutMarkIn, TurnoutMarkResult, TurnoutSummary, parse_serials
from ..scope import Scope, UserScope, require_area
from ..stubs import BoothAgent
from .families import _require_booth
from .voters import voter_in_scope

router = APIRouter(prefix="/turnout", tags=["polling day"])

MARK_COLS = "t.voter_id, t.is_voted, t.marked_by, t.marked_at, t.source::text AS source"


def mark_key(request_id: uuid.UUID, voter_id: uuid.UUID) -> uuid.UUID:
    """The key kept on a voter's mark: the same request and voter always give the same key."""
    return uuid.uuid5(request_id, str(voter_id))


def read_marks(conn: Connection, voter_ids: list[uuid.UUID]) -> list[TurnoutMark]:
    if not voter_ids:
        return []
    rows = conn.execute(text(f"""
        SELECT {MARK_COLS} FROM app.voter_turnout t WHERE t.voter_id = ANY(CAST(:ids AS uuid[]))
    """), {"ids": voter_ids}).mappings().all()
    by_id = {r["voter_id"]: TurnoutMark(**r) for r in rows}
    return [by_id[v] for v in voter_ids if v in by_id]


def mark_targets(conn: Connection, scope: Scope, body: TurnoutMarkIn) -> tuple[list[uuid.UUID], list[int]]:
    """(voter ids in request order, serials with no voter). Only voters on the current roll (roll_status
    active) can vote. 404 when a voter id is not in the user's area (removed, another area or workspace),
    or the booth is not a booth in the area; 422 for a voter id not on the current roll."""
    cond, params = scope.filter("v.geo_path")
    if body.voter_ids:
        ids = list(dict.fromkeys(body.voter_ids))
        found = dict(conn.execute(text(f"""
            SELECT v.id, v.roll_status::text FROM app.voters v
             WHERE v.id = ANY(CAST(:ids AS uuid[])) AND v.deleted_at IS NULL AND {cond}
        """), {**params, "ids": ids}).all())
        if len(found) != len(ids):
            raise ApiError(404, "not_found", "Voter not found.")
        off_roll = [str(v) for v in ids if found[v] != "active"]
        if off_roll:
            raise ApiError(422, "validation_error", f"voter_ids: not on the current roll: {', '.join(off_roll)}")
        return ids, []

    _require_booth(conn, scope, body.booth_id)
    serials = parse_serials(body.serials or "")
    rows = conn.execute(text(f"""
        SELECT v.serial_no, v.id FROM app.voters v
         WHERE v.booth_id = :booth AND v.serial_no = ANY(CAST(:serials AS int[]))
           AND v.roll_status = 'active' AND v.deleted_at IS NULL AND {cond}
    """), {**params, "booth": body.booth_id, "serials": serials}).all()
    by_serial = {r.serial_no: r.id for r in rows}
    return [by_serial[s] for s in serials if s in by_serial], [s for s in serials if s not in by_serial]


def write_marks(conn: Connection, user: Principal, scope: Scope, body: TurnoutMarkIn) -> TurnoutMarkResult:
    """Mark the voters as voted. The caller checked the role."""
    ids, missing = mark_targets(conn, scope, body)
    keys = {v: mark_key(body.id, v) for v in ids}
    existing: dict[uuid.UUID, Any] = {r.voter_id: r for r in conn.execute(text("""
        SELECT voter_id, is_voted, client_mutation_id FROM app.voter_turnout WHERE voter_id = ANY(CAST(:ids AS uuid[]))
    """), {"ids": ids})} if ids else {}

    def done_before(v: uuid.UUID) -> bool:  # this request marked it already (it may be undone since)
        return v in existing and existing[v].client_mutation_id == keys[v]

    todo = [v for v in ids if not done_before(v) and not (v in existing and existing[v].is_voted)]
    new: set[uuid.UUID] = set()
    if todo:
        # Only a voter not voted now is (re)marked; a parallel mark of the same voter wins once.
        new = set(conn.execute(text("""
            INSERT INTO app.voter_turnout AS t (voter_id, tenant_id, is_voted, marked_by, marked_at, device_id,
                                                source, client_mutation_id)
            SELECT u.voter_id, app.current_tenant_id(), true, :user,
                   least(coalesce(CAST(:at AS timestamptz), now()), now()), CAST(:device AS uuid),
                   CAST(:source AS app.turnout_source), u.mark_key
              FROM unnest(CAST(:ids AS uuid[]), CAST(:keys AS uuid[])) AS u(voter_id, mark_key)
            ON CONFLICT (voter_id) DO UPDATE
               SET is_voted = true, marked_by = EXCLUDED.marked_by, marked_at = EXCLUDED.marked_at,
                   device_id = EXCLUDED.device_id, source = EXCLUDED.source,
                   client_mutation_id = EXCLUDED.client_mutation_id, cleared_by = NULL, cleared_at = NULL
             WHERE NOT t.is_voted
            RETURNING t.voter_id
        """), {"user": user.user_id, "at": body.marked_at, "device": user.device_id, "source": body.source.value,
               "ids": todo, "keys": [keys[v] for v in todo]}).scalars())
    marked = [v for v in ids if done_before(v) or v in new]
    marked_set = set(marked)
    return TurnoutMarkResult(marked=marked, already=[v for v in ids if v not in marked_set],
                             not_found_serials=missing)


def undo_mark(conn: Connection, user: Principal, scope: Scope, voter_id: uuid.UUID) -> None:
    """Undo the voter's mark. Nothing to undo is fine (a repeat, or never marked). The caller checked the role."""
    voter_in_scope(conn, scope, voter_id)
    conn.execute(text("""
        UPDATE app.voter_turnout SET is_voted = false, cleared_by = :user, cleared_at = now()
         WHERE voter_id = :voter AND is_voted
    """), {"voter": voter_id, "user": user.user_id})


@router.get("/summary", response_model=TurnoutSummary,
            summary="Voted count and percentage for the user's area, by booth (voters on the current roll). "
                    "Polling-day roles.")
def turnout_summary(conn: Db, user: BoothAgent, scope: UserScope, ward_id: uuid.UUID | None = None,
                    booth_id: uuid.UUID | None = None) -> TurnoutSummary:
    gcond, params = scope.filter("g.path")
    where = ["g.level = 'booth'", "g.is_active", gcond]
    for name, area in (("ward_path", ward_id), ("booth_path", booth_id)):
        if area is not None:
            params[name] = require_area(conn, scope, area)
            where.append(f"g.path <@ CAST(:{name} AS ltree)")
    # Marks are counted on their own, from the marks to the voters (primary key). One join of voters and
    # marks went to a nested loop of every voter x every mark while the table's statistics still said
    # "empty" (polling morning, before autoanalyze): 0.5 s for one part's marks on the real roll.
    rows = conn.execute(text(f"""
        WITH booths AS (SELECT g.id, g.sort_order, g.number, g.code FROM app.geo_units g WHERE {' AND '.join(where)}),
             totals AS (SELECT v.booth_id, count(*) AS n FROM app.voters v
                         WHERE v.deleted_at IS NULL AND v.roll_status = 'active' AND v.booth_id IN (SELECT id FROM booths)
                         GROUP BY v.booth_id),
             done AS (SELECT v.booth_id, count(*) AS n FROM app.voter_turnout t
                        JOIN app.voters v ON v.tenant_id = t.tenant_id AND v.id = t.voter_id
                       WHERE t.is_voted AND v.deleted_at IS NULL AND v.roll_status = 'active'
                         AND v.booth_id IN (SELECT id FROM booths)
                       GROUP BY v.booth_id)
        SELECT b.id AS booth_id, coalesce(totals.n, 0) AS total, coalesce(done.n, 0) AS voted
          FROM booths b LEFT JOIN totals ON totals.booth_id = b.id LEFT JOIN done ON done.booth_id = b.id
         ORDER BY b.sort_order, b.number NULLS LAST, b.code
    """), params).mappings().all()
    booths = [TurnoutBooth(**r, percent=_percent(r["voted"], r["total"])) for r in rows]
    total, voted = sum(b.total for b in booths), sum(b.voted for b in booths)
    return TurnoutSummary(total=total, voted=voted, percent=_percent(voted, total), booths=booths,
                          updated_at=conn.execute(text("SELECT now()")).scalar_one())


def _percent(voted: int, total: int) -> float:
    return round(voted * 100 / total, 1) if total else 0.0


@router.post("/marks", response_model=TurnoutMarkResult,
             summary="Mark voters as voted, by id or by booth + serial numbers ('12, 15, 18-25'). A voter already "
                     "marked stays as it was; the same request id sent again marks nothing again. Polling-day roles.")
def add_marks(body: TurnoutMarkIn, conn: Db, user: BoothAgent, scope: UserScope) -> TurnoutMarkResult:
    return write_marks(conn, user, scope, body)


@router.delete("/marks/{voter_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
               summary="Undo a wrong voted mark (nothing to undo is fine). Polling-day roles.")
def clear_mark(voter_id: uuid.UUID, conn: Db, user: BoothAgent, scope: UserScope) -> Response:
    undo_mark(conn, user, scope, voter_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
