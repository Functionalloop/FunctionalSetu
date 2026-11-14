"""Matching Engine, part 2 (plan 10.3): review single rows, apply the roll, discard an import.

Only a super admin calls these (client, 12 Nov). They run in the request's transaction with the
super admin's context, so every voter change gets its audit row (History: "roll_edit") and a new
sync_xid (phones pull it). The import row is locked FOR UPDATE first, so two clicks never apply twice.

Resolve (one row, import in review):
  accept + voter_id   this row is that voter (uncertain / new / matched rows): the row becomes an
                      accepted "uncertain" match to it. The voter must be in the constituency and not
                      held by another row (409 voter_taken).
  accept              the suggested match is right (matched / uncertain / possible_duplicate).
  reject              not that voter: matched / uncertain / possible_duplicate rows are added as new
                      voters on apply; an unreadable row is skipped; a new row stays new.
  Absent rows follow the matches (refresh_absent): a voter nobody holds any more is listed absent
  again, one a row now holds is not. They cannot be resolved by hand (422).

Apply (nothing may wait for review: 409 review_not_finished):
  - voters held by an accepted row get the row's roll fields (only when something changed, so an
    unchanged voter gets no history entry); a live row brings an absent / deleted voter back;
  - a deleted entry (is_deleted) makes its voter "deleted_in_roll" and keeps the deletion_reason on
    record (the roll prints none; a new one gets none; never "dead");
  - accepted new rows and rejected matches are added as voters (a deleted entry is not added);
  - accepted absent rows: the voter becomes "absent_from_current_roll". Never dead, never hidden;
  - surveys, Kutumbs, visits, marks: not touched. The voter id never changes.
  - a part that is not on record gets a ward and a booth (one booth per part, like the first import).
  Serial numbers move between rolls, and (booth, serial) is unique among active voters: voters
  leaving a slot go first, the rest in an order that frees each slot before it is taken; a cycle
  (two voters swapping serials) parks one voter as absent for a moment (an extra history line).
  An EPIC another voter holds (other constituency, or two rows added with one EPIC): 409 epic_in_use.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

from sqlalchemy import Connection, text

from .deps import Principal
from .duplicates import find_pairs
from .errors import ApiError
from .roll_match import Row, row_from_raw, similarity

HOLDING = ("matched", "uncertain", "new")


def lock_import(conn: Connection, import_id: uuid.UUID) -> dict[str, Any]:
    """The import row, locked. The caller has checked it is in the user's area."""
    return dict(conn.execute(text("""
        SELECT id, local_body_id, list_type::text AS list_type, status::text AS status, published_on, stats
          FROM app.roll_versions WHERE id = :id FOR UPDATE"""), {"id": import_id}).mappings().one())


def _in_review(rv: dict[str, Any]) -> None:
    if rv["status"] != "review":
        raise ApiError(409, "import_closed", f"This import is not waiting for review (it is {rv['status']}).")


# --- absent rows follow the matches ----------------------------------------------------------------
def _file_parts(conn: Connection, rv_id: uuid.UUID) -> set[int]:
    return set(conn.execute(text("""
        SELECT DISTINCT part_no FROM app.roll_import_rows
         WHERE roll_version_id = :rv AND match_status IS NOT NULL
           AND match_status <> 'absent_from_current_roll'"""), {"rv": rv_id}).scalars())


def _held_by(conn: Connection, rv_id: uuid.UUID, voter_id: uuid.UUID, except_row: int | None = None) -> int | None:
    """row_no of a row (other than except_row) that holds this voter, if any."""
    return conn.execute(text("""
        SELECT row_no FROM app.roll_import_rows
         WHERE roll_version_id = :rv AND matched_voter_id = :v AND id IS DISTINCT FROM :except
           AND match_status = ANY(CAST(:holding AS app.match_status[])) AND review_status <> 'rejected'
         ORDER BY row_no LIMIT 1"""),
        {"rv": rv_id, "v": voter_id, "except": except_row, "holding": list(HOLDING)}).scalar()


def refresh_absent(conn: Connection, rv: dict[str, Any], voter_id: uuid.UUID) -> None:
    held = _held_by(conn, rv["id"], voter_id) is not None
    absent = conn.execute(text("""
        SELECT id, review_status::text AS review FROM app.roll_import_rows
         WHERE roll_version_id = :rv AND match_status = 'absent_from_current_roll' AND matched_voter_id = :v"""),
        {"rv": rv["id"], "v": voter_id}).mappings().first()
    v = conn.execute(text("""
        SELECT part_no, serial_no, epic_no, first_name_en, middle_name_en, last_name_en, gender::text AS gender, age,
               house_no, roll_status::text AS roll_status
          FROM app.voters WHERE id = :v AND deleted_at IS NULL"""), {"v": voter_id}).mappings().first()
    should = (not held and v is not None and v["roll_status"] == "active" and rv["list_type"] != "supplementary"
              and v["part_no"] in _file_parts(conn, rv["id"]))
    if absent is not None:
        want = "accepted" if should else "rejected"
        if absent["review"] != want:
            conn.execute(text("""UPDATE app.roll_import_rows SET review_status = CAST(:w AS app.review_status)
                                  WHERE id = :id"""), {"w": want, "id": absent["id"]})
    elif should:
        conn.execute(text("""
            INSERT INTO app.roll_import_rows
                (tenant_id, roll_version_id, row_no, raw, part_no, serial_no, epic_no, first_name_en, middle_name_en,
                 last_name_en, gender, age, house_no, match_status, matched_voter_id, match_notes, review_status)
            SELECT app.current_tenant_id(), :rv, coalesce(max(row_no), 1) + 1, '{}', :part_no, :serial_no, :epic_no,
                   :first_name_en, :middle_name_en, :last_name_en, CAST(:gender AS app.gender), :age, :house_no,
                   'absent_from_current_roll', :v, 'not in this file', 'accepted'
              FROM app.roll_import_rows WHERE roll_version_id = :rv"""), {**v, "rv": rv["id"], "v": voter_id})


# --- resolve ------------------------------------------------------------------------------------------
def resolve_row(conn: Connection, user: Principal, rv: dict[str, Any], row_id: int, accept: bool,
                voter_id: uuid.UUID | None) -> None:
    _in_review(rv)
    row = conn.execute(text("""
        SELECT id, row_no, match_status::text AS status, matched_voter_id, raw
          FROM app.roll_import_rows WHERE id = :id AND roll_version_id = :rv FOR UPDATE"""),
        {"id": row_id, "rv": rv["id"]}).mappings().first()
    if row is None:
        raise ApiError(404, "not_found", "Row not found.")
    status, before = row["status"], row["matched_voter_id"]
    if status == "absent_from_current_roll":
        raise ApiError(422, "validation_error", "Absent rows follow the matches; resolve the row that has this voter.")
    if voter_id is not None and not accept:
        raise ApiError(422, "validation_error", "Choosing a voter means accept: true.")

    new_status, new_voter, review, sim, note = status, before, "rejected" if not accept else "accepted", None, None
    if voter_id is not None:
        if status not in HOLDING:
            raise ApiError(422, "validation_error", "Only a matched, uncertain or new row can be given a voter.")
        v = conn.execute(text("""SELECT full_name_en FROM app.voters
                                  WHERE id = :v AND local_body_id = :lb AND deleted_at IS NULL"""),
                         {"v": voter_id, "lb": rv["local_body_id"]}).mappings().first()
        if v is None:
            raise ApiError(404, "not_found", "Voter not found in this constituency.")
        r = row_from_raw(row["row_no"], row["raw"])
        new_status, new_voter = "uncertain", voter_id
        sim, note = round(similarity(r.full_name, v["full_name_en"]), 3), "voter chosen by hand"
    elif accept:
        if status is None:
            raise ApiError(422, "validation_error", "An unreadable row cannot be used: fix the file, or skip the row.")
        if status == "new":
            review = "accepted"
        elif before is None:
            raise ApiError(422, "validation_error", "This row has no suggested voter; choose one.")
    elif status == "new":
        review = "accepted"   # "treat it as new": it is
    if new_voter is not None and review == "accepted" and new_status in HOLDING:
        other = _held_by(conn, rv["id"], new_voter, except_row=row["id"])
        if other is not None:
            raise ApiError(409, "voter_taken", f"Row {other} already has this voter.", extra={"row_no": other})

    conn.execute(text("""
        UPDATE app.roll_import_rows
           SET match_status = CAST(:st AS app.match_status), matched_voter_id = :v,
               similarity = coalesce(:sim, similarity),
               match_notes = CASE WHEN CAST(:note AS text) IS NULL THEN match_notes
                                  ELSE concat_ws('; ', match_notes, CAST(:note AS text)) END,
               review_status = CAST(:review AS app.review_status), reviewed_by = :by, reviewed_at = now()
         WHERE id = :id"""), {"st": new_status, "v": new_voter, "sim": sim, "note": note, "review": review,
                              "by": user.user_id, "id": row["id"]})
    for vid in {before, new_voter} - {None}:
        refresh_absent(conn, rv, vid)


# --- apply ---------------------------------------------------------------------------------------------
_VOTER_COLS = ("ward_id", "booth_id", "part_no", "serial_no", "epic_no", "first_name_en", "middle_name_en",
               "last_name_en", "relation_type", "relative_name_en", "gender", "age", "house_no", "address_en",
               "list_type", "roll_status", "deletion_reason")
_CASTS = {"relation_type": "app.relation_type", "gender": "app.gender", "list_type": "app.list_type",
          "roll_status": "app.roll_status"}
_SET = ", ".join(f"{c} = CAST(:{c} AS {_CASTS[c]})" if c in _CASTS else f"{c} = :{c}" for c in _VOTER_COLS)
_UPDATE = text(f"UPDATE app.voters SET {_SET}, age_as_of = :age_as_of, last_roll_version_id = :rv WHERE id = :id")
_INSERT = text(f"""
    INSERT INTO app.voters (id, tenant_id, local_body_id, booth_no, age_as_of, first_roll_version_id,
                            last_roll_version_id, {', '.join(_VOTER_COLS)})
    VALUES (:id, app.current_tenant_id(), :lb, 1, :age_as_of, :rv, :rv,
            {', '.join(f'CAST(:{c} AS {_CASTS[c]})' if c in _CASTS else f':{c}' for c in _VOTER_COLS)})""")
_PARK = text("UPDATE app.voters SET roll_status = 'absent_from_current_roll', deletion_reason = NULL WHERE id = :id")


def _places(conn: Connection, lb: uuid.UUID, parts: set[int]) -> dict[int, tuple[uuid.UUID, uuid.UUID]]:
    """part_no -> (ward, booth); a part not on record gets both (as scripts/import_roll_parts.py makes them)."""
    found = {r[0]: (r[1], r[2]) for r in conn.execute(text("""
        SELECT w.number, w.id, b.id
          FROM app.geo_units lb
          JOIN app.geo_units w ON w.level = 'ward' AND w.path <@ lb.path AND w.number IS NOT NULL
          JOIN LATERAL (SELECT id FROM app.geo_units b WHERE b.parent_id = w.id AND b.level = 'booth'
                         ORDER BY b.number NULLS LAST, b.code LIMIT 1) b ON TRUE
         WHERE lb.id = :lb"""), {"lb": lb}).all()}
    for part in sorted(parts - found.keys()):
        ward, booth = uuid.uuid4(), uuid.uuid4()
        geo = text("""INSERT INTO app.geo_units (id, tenant_id, parent_id, level, code, number, name_mr, name_en)
                      VALUES (:id, app.current_tenant_id(), :parent, CAST(:level AS app.geo_level), :code, :n,
                              :mr, :en)""")
        conn.execute(geo, {"id": ward, "parent": lb, "level": "ward", "code": str(part), "n": part,
                           "mr": f"भाग {part}", "en": f"Part {part}"})
        conn.execute(geo, {"id": booth, "parent": ward, "level": "booth", "code": str(part), "n": 1,
                           "mr": f"भाग {part}", "en": f"Part {part}"})
        found[part] = (ward, booth)
    return found


def _target(r: Row, v: dict[str, Any] | None, place: tuple[uuid.UUID, uuid.UUID], list_type: str) -> dict[str, Any]:
    """The voter's roll fields after this roll. A value the file leaves empty keeps the old one."""
    old = v or {}
    keep = lambda new, col: new if new is not None else old.get(col)  # noqa: E731
    return {
        "ward_id": place[0], "booth_id": place[1], "part_no": r.part_no, "serial_no": r.serial_no,
        "epic_no": keep(r.epic_no, "epic_no"),
        "first_name_en": r.first, "middle_name_en": r.middle, "last_name_en": r.last,
        "relation_type": keep(r.relation_type, "relation_type"), "relative_name_en": keep(r.relative_name,
                                                                                           "relative_name_en"),
        "gender": r.gender, "age": keep(r.age, "age"), "house_no": keep(r.house_no, "house_no"),
        "address_en": keep(r.section_name, "address_en"),
        "list_type": "supplementary" if r.is_supplement or list_type == "supplementary" else list_type,
        "roll_status": "deleted_in_roll" if r.is_deleted else "active",
        # the roll prints no reason: a deleted entry keeps what is on record (usually none)
        "deletion_reason": old.get("deletion_reason") if r.is_deleted else None,
    }


def apply_import(conn: Connection, user: Principal, rv: dict[str, Any]) -> dict[str, int]:
    _in_review(rv)
    pending = conn.execute(text("""SELECT count(*) FROM app.roll_import_rows
                                    WHERE roll_version_id = :rv AND review_status = 'pending'"""),
                           {"rv": rv["id"]}).scalar_one()
    if pending:
        raise ApiError(409, "review_not_finished", f"{pending} rows still wait for review.", extra={"pending": pending})

    rows = conn.execute(text("""
        SELECT row_no, raw, match_status::text AS status, review_status::text AS review, matched_voter_id
          FROM app.roll_import_rows WHERE roll_version_id = :rv ORDER BY row_no"""), {"rv": rv["id"]}).mappings().all()
    voters = {r["id"]: dict(r) for r in conn.execute(text(f"""
        SELECT id, age_as_of, {', '.join(f'{c}::text AS {c}' if c in _CASTS else c for c in _VOTER_COLS)}
          FROM app.voters WHERE local_body_id = :lb AND deleted_at IS NULL"""), {"lb": rv["local_body_id"]}).mappings()}

    updates: list[tuple[int, Row, dict[str, Any]]] = []   # (row_no, row, voter)
    inserts: list[tuple[int, Row]] = []
    absent: list[uuid.UUID] = []
    skipped = 0
    for x in rows:
        st, review, vid = x["status"], x["review"], x["matched_voter_id"]
        if st == "absent_from_current_roll":
            if review == "accepted" and vid in voters:
                absent.append(vid)
            continue
        if st is None or (st == "possible_duplicate" and review == "accepted"):
            skipped += 1
            continue
        r = row_from_raw(x["row_no"], x["raw"])
        if st in ("matched", "uncertain") and review == "accepted":
            if vid in voters:
                updates.append((x["row_no"], r, voters[vid]))
            else:
                skipped += 1   # removed by hand meanwhile: not added back
        elif r.is_deleted:
            skipped += 1   # a deleted entry of someone not on record: nobody to add
        else:
            inserts.append((x["row_no"], r))

    places = _places(conn, rv["local_body_id"], {r.part_no for _, r, _ in updates} | {r.part_no for _, r in inserts})
    published = rv["published_on"] or date.today()
    planned: list[tuple[int, dict[str, Any], dict[str, Any]]] = []   # (row_no, voter, new values)
    unchanged = 0
    for row_no, r, v in updates:
        new = _target(r, v, places[r.part_no], rv["list_type"])
        if all(str(new[c]) == str(v[c]) if new[c] is not None and v[c] is not None else new[c] == v[c]
               for c in _VOTER_COLS):
            unchanged += 1
            continue
        new["age_as_of"] = published if r.age is not None else v["age_as_of"]
        planned.append((row_no, v, new))
    added = [(row_no, {**_target(r, None, places[r.part_no], rv["list_type"]), "id": uuid.uuid4(),
                       "age_as_of": published if r.age is not None else None}) for row_no, r in inserts]

    # EPICs: unique in the workspace
    wanted: dict[str, list[tuple[int, uuid.UUID]]] = {}
    for row_no, v, new in planned:
        if new["epic_no"] and new["epic_no"] != v["epic_no"]:
            wanted.setdefault(new["epic_no"], []).append((row_no, v["id"]))
    for row_no, new in added:
        if new["epic_no"]:
            wanted.setdefault(new["epic_no"], []).append((row_no, new["id"]))
    holders = dict(conn.execute(text("SELECT epic_no, id FROM app.voters WHERE epic_no = ANY(:e) AND deleted_at IS NULL"),
                                {"e": list(wanted)}).all()) if wanted else {}
    clash = sorted(row_no for epic, want in wanted.items() for row_no, vid in want
                   if len(want) > 1 or holders.get(epic) not in (None, vid))
    if clash:
        raise ApiError(409, "epic_in_use", "Another voter already has the EPIC of rows "
                       f"{', '.join(map(str, clash[:20]))}{' ...' if len(clash) > 20 else ''}.", extra={"row_nos": clash})

    # serial slots: (booth, serial) is unique among active voters
    slot = {vid: (str(v["booth_id"]), v["serial_no"]) for vid, v in voters.items() if v["roll_status"] == "active"}
    occupied = {s: vid for vid, s in slot.items()}

    def leave(vid: uuid.UUID) -> None:
        s = slot.pop(vid, None)
        if s is not None and occupied.get(s) == vid:
            del occupied[s]

    ops: list[tuple[Any, dict[str, Any]]] = []
    for vid in absent:
        leave(vid)
    moving = []
    for row_no, v, new in planned:
        params = {**new, "id": v["id"], "rv": rv["id"]}
        if new["roll_status"] != "active":
            leave(v["id"])
            ops.append((_UPDATE, params))
        else:
            moving.append(((str(new["booth_id"]), new["serial_no"]), params, row_no))
    parked: set[uuid.UUID] = set()
    while moving:
        rest = []
        for target, params, row_no in moving:
            if occupied.get(target) in (None, params["id"]):
                leave(params["id"])
                occupied[target], slot[params["id"]] = params["id"], target
                ops.append((_UPDATE, params))
            else:
                rest.append((target, params, row_no))
        if len(rest) == len(moving):
            waiting = {p["id"] for _, p, _ in rest}
            blocked = sorted(n for t, _, n in rest if occupied[t] not in waiting)
            if blocked:   # held by a voter this roll does not move (a supplementary list)
                raise ApiError(409, "serial_in_use", "An active voter keeps the part and serial of rows "
                               f"{', '.join(map(str, blocked[:20]))}.", extra={"row_nos": blocked})
            park = next(p["id"] for _, p, _ in rest if p["id"] not in parked)   # a cycle: park one, go on
            parked.add(park)
            ops.append((_PARK, {"id": park}))
            leave(park)
        moving = rest
    taken_slots = [row_no for row_no, new in added
                   if new["roll_status"] == "active" and (str(new["booth_id"]), new["serial_no"]) in occupied]
    if taken_slots:
        raise ApiError(409, "serial_in_use", "An active voter keeps the part and serial of rows "
                       f"{', '.join(map(str, taken_slots[:20]))}.", extra={"row_nos": taken_slots})

    if absent:
        conn.execute(text("""UPDATE app.voters SET roll_status = 'absent_from_current_roll', deletion_reason = NULL,
                                    last_roll_version_id = :rv
                              WHERE id = ANY(:ids) AND roll_status = 'active'"""), {"ids": absent, "rv": rv["id"]})
    for stmt, params in ops:
        conn.execute(stmt, params)
    if added:
        conn.execute(_INSERT, [{**new, "lb": rv["local_body_id"], "rv": rv["id"]} for _, new in added])

    wards = {places[p][0] for p in _file_parts(conn, rv["id"]) if p in places}
    if wards:
        conn.execute(text("""
            INSERT INTO app.roll_part_versions (tenant_id, ward_id, data_version, published_on, roll_version_id)
            SELECT app.current_tenant_id(), w, 1, :pub, :rv FROM unnest(CAST(:wards AS uuid[])) AS w
            ON CONFLICT (tenant_id, ward_id) DO UPDATE
               SET data_version = app.roll_part_versions.data_version + 1, published_on = EXCLUDED.published_on,
                   roll_version_id = EXCLUDED.roll_version_id, updated_at = now()"""),
                     {"wards": list(wards), "pub": rv["published_on"], "rv": rv["id"]})

    applied = {"updated": len(planned), "unchanged": unchanged, "added": len(added), "marked_absent": len(absent),
               "deleted_in_roll": sum(1 for _, _, new in planned if new["roll_status"] == "deleted_in_roll"),
               "skipped": skipped,
               "new_pairs": find_pairs(conn, rv["local_body_id"])}   # possible duplicates (10.5)
    conn.execute(text("""UPDATE app.roll_versions
                            SET status = 'applied', applied_by = :by, applied_at = now(),
                                stats = stats || CAST(:applied AS jsonb)
                          WHERE id = :id"""), {"by": user.user_id, "id": rv["id"], "applied": json.dumps(applied)})
    return applied


# --- discard ---------------------------------------------------------------------------------------------
def discard_import(conn: Connection, rv: dict[str, Any]) -> None:
    """Uploaded, in review or failed -> discarded (rows are kept for the record). Again: nothing to do."""
    if rv["status"] == "discarded":
        return
    if rv["status"] == "applied":
        raise ApiError(409, "import_closed", "This import is applied; it cannot be discarded.")
    conn.execute(text("UPDATE app.roll_versions SET status = 'discarded' WHERE id = :id"), {"id": rv["id"]})
