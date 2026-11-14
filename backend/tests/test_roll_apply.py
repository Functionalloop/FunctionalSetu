"""Matching Engine, review and apply (10.3): .../rows/{row_id}/resolve, .../apply, .../discard
(app/roll_apply.py). Fake voters only; the roll file and voters are those of test_roll_import.py.
Generic rules: test_endpoint_rules.py."""

from __future__ import annotations

import uuid

import pytest

from conftest import bearer, login
from test_roll_import import ROWS, VOTERS, all_rows, csv_bytes, run_jobs, upload

API = "/api/v1"


@pytest.fixture
def ws(make_workspace, owner_conn):
    ws = make_workspace("apply")
    for serial, epic, first, last, gender, age, rel in VOTERS:
        owner_conn.execute(
            """INSERT INTO app.voters (tenant_id, local_body_id, ward_id, booth_id, part_no, serial_no, epic_no,
                                       first_name_en, last_name_en, gender, age, relative_name_en, house_no,
                                       relation_type, address_en)
               VALUES (%s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s, 'father', 'Ward one')""",
            (ws.tenant, ws.local_body, ws.ward, ws.booths[0], serial, epic, first, last, gender, age, rel,
             f"H-{serial}"))
    return ws


@pytest.fixture
def boss(client, ws):
    return bearer(login(client, ws, "boss").json())


def voter(owner_conn, ws, serial: int | None = None, epic: str | None = None) -> dict:
    cur = owner_conn.execute(
        """SELECT id, serial_no, epic_no, first_name_en, last_name_en, age, roll_status::text AS roll_status,
                  deletion_reason, deleted_at, booth_id, part_no, last_roll_version_id, first_roll_version_id
             FROM app.voters WHERE tenant_id = %s AND (serial_no = %s OR epic_no = %s)
            ORDER BY roll_status, serial_no LIMIT 1""", (ws.tenant, serial, epic))
    return dict(zip([c.name for c in cur.description], cur.fetchone()))


def started(client, boss, ws, data=None) -> tuple[str, dict[int, dict]]:
    """An import of `data` (default: the plan's fake roll) in review; its rows by row_no."""
    imp = upload(client, boss, ws, data or csv_bytes())
    assert imp.status_code == 202, imp.text
    run_jobs()
    iid = imp.json()["id"]
    return iid, {r["row_no"]: r for r in all_rows(client, boss, iid)}


def resolve(client, boss, iid, row: dict, accept: bool, voter_id=None):
    body = {"accept": accept, **({"voter_id": str(voter_id)} if voter_id else {})}
    return client.post(f"{API}/rolls/imports/{iid}/rows/{row['id']}/resolve", headers=boss, json=body)


def review_all(client, boss, iid, rows) -> None:
    """The plan's file: both uncertain rows are right, the repeated row is the same voter, skip the bad row."""
    for no, accept in ((3, True), (4, True), (6, True), (7, False)):
        assert resolve(client, boss, iid, rows[no], accept).status_code == 200


def code(resp) -> str:
    return resp.json()["error"]["code"]


# --- the plan's test --------------------------------------------------------------------------------
def test_apply_keeps_surveys_and_makes_the_missing_voter_not_in_current_roll(client, ws, boss, owner_conn):
    ids = {s: voter(owner_conn, ws, s)["id"] for s in (1, 2, 3, 4)}
    for s, notes in ((2, "met at the market"), (3, "lives upstairs")):
        owner_conn.execute("INSERT INTO app.voter_surveys (voter_id, tenant_id, notes) VALUES (%s, %s, %s)",
                           (ids[s], ws.tenant, notes))
    surveys_before = owner_conn.execute(
        "SELECT voter_id, notes, version FROM app.voter_surveys WHERE tenant_id = %s ORDER BY notes",
        (ws.tenant,)).fetchall()

    iid, rows = started(client, boss, ws)
    review_all(client, boss, iid, rows)
    got = client.post(f"{API}/rolls/imports/{iid}/apply", headers=boss)
    assert got.status_code == 200, got.text
    imp = got.json()
    assert imp["status"] == "applied" and imp["applied_at"] is not None
    assert {k: imp["counts"][k] for k in ("updated", "unchanged", "added", "marked_absent", "deleted_in_roll",
                                          "skipped")} == \
           {"updated": 3, "unchanged": 0, "added": 1, "marked_absent": 1, "deleted_in_roll": 0, "skipped": 2}

    # surveys untouched and still on the same voters (the voter id never changes)
    assert owner_conn.execute("SELECT voter_id, notes, version FROM app.voter_surveys WHERE tenant_id = %s "
                              "ORDER BY notes", (ws.tenant,)).fetchall() == surveys_before
    v2 = voter(owner_conn, ws, 2)
    assert (v2["id"], v2["first_name_en"], v2["last_name_en"], v2["roll_status"]) == (ids[2], "Vinod", "Gawas", "active")
    assert v2["last_roll_version_id"] == uuid.UUID(iid)
    # the missing voter: not in current roll, never dead, never hidden
    v3 = voter(owner_conn, ws, 3)
    assert (v3["id"], v3["roll_status"], v3["deletion_reason"], v3["deleted_at"]) == \
           (ids[3], "absent_from_current_roll", None, None)
    assert owner_conn.execute("""SELECT count(*) FROM app.voters v LEFT JOIN app.voter_surveys s ON s.voter_id = v.id
                                  WHERE v.tenant_id = %s AND (v.deletion_reason = 'dead' OR s.dead_marked
                                        OR v.deleted_at IS NOT NULL)""", (ws.tenant,)).fetchone()[0] == 0
    # the new voter, in part 1's booth
    v5 = voter(owner_conn, ws, 5)
    assert (v5["first_name_en"], v5["epic_no"], v5["roll_status"], v5["booth_id"], v5["first_roll_version_id"]) == \
           ("Kavita", "TST1000099", "active", ws.booths[0], uuid.UUID(iid))
    found = client.get(f"{API}/voters", headers=boss, params={"q": "kavita"}).json()["items"]
    assert [v["id"] for v in found] == [str(v5["id"])]
    # the change is in the voter's history and the part's list version moved on
    kinds = [e["kind"] for e in client.get(f"{API}/voters/{ids[2]}/history", headers=boss).json()["items"]]
    assert "roll_edit" in kinds
    assert owner_conn.execute("SELECT data_version, roll_version_id FROM app.roll_part_versions WHERE ward_id = %s",
                              (ws.ward,)).fetchone() == (1, uuid.UUID(iid))


def test_an_unchanged_voter_gets_no_history_line(client, ws, boss, owner_conn):
    rows = [(1, 1, "TST1000001", "Asha Naik", "Naik", "Ramesh Naik", "Female", 30, "false")]
    iid, _ = started(client, boss, ws, csv_bytes(rows))
    v1 = voter(owner_conn, ws, 1)
    before = owner_conn.execute("SELECT count(*) FROM app.audit_log WHERE entity_id = %s", (str(v1["id"]),)).fetchone()
    # the others are absent: a file of part 1 with one voter
    imp = client.post(f"{API}/rolls/imports/{iid}/apply", headers=boss).json()
    assert (imp["counts"]["unchanged"], imp["counts"]["updated"], imp["counts"]["marked_absent"]) == (1, 0, 3)
    assert owner_conn.execute("SELECT count(*) FROM app.audit_log WHERE entity_id = %s",
                              (str(v1["id"]),)).fetchone() == before
    assert voter(owner_conn, ws, 1)["roll_status"] == "active"


# --- review --------------------------------------------------------------------------------------------
def test_apply_waits_until_every_row_is_reviewed(client, ws, boss, owner_conn):
    iid, rows = started(client, boss, ws)
    got = client.post(f"{API}/rolls/imports/{iid}/apply", headers=boss)
    assert got.status_code == 409 and code(got) == "review_not_finished" and got.json()["error"]["pending"] == 4
    assert voter(owner_conn, ws, 3)["roll_status"] == "active"
    assert client.get(f"{API}/rolls/imports/{iid}", headers=boss).json()["status"] == "review"


def test_resolve_records_who_and_counts_follow(client, ws, boss):
    iid, rows = started(client, boss, ws)
    got = resolve(client, boss, iid, rows[3], True)
    assert got.status_code == 200
    assert (got.json()["review_status"], got.json()["match_status"]) == ("accepted", "uncertain")
    counts = client.get(f"{API}/rolls/imports/{iid}", headers=boss).json()["counts"]
    assert (counts["to_review"], counts["reviewed"]) == (3, 1)


def test_choosing_a_voter_by_hand_takes_them_out_of_absent(client, ws, boss, owner_conn):
    iid, rows = started(client, boss, ws)
    sunita = voter(owner_conn, ws, 3)["id"]
    # the "new" row is really Sunita (absent so far)
    got = resolve(client, boss, iid, rows[5], True, sunita)
    assert got.status_code == 200, got.text
    row = got.json()
    assert (row["match_status"], row["matched_voter_id"], row["review_status"]) == ("uncertain", str(sunita), "accepted")
    assert "voter chosen by hand" in row["match_notes"]
    counts = client.get(f"{API}/rolls/imports/{iid}", headers=boss).json()["counts"]
    assert (counts["absent_from_current_roll"], counts["new"], counts["uncertain"]) == (0, 0, 3)
    # changed my mind: not her after all, the row is a new voter and she is absent again
    assert resolve(client, boss, iid, rows[5], False).json()["review_status"] == "rejected"
    counts = client.get(f"{API}/rolls/imports/{iid}", headers=boss).json()["counts"]
    assert counts["absent_from_current_roll"] == 1


def test_rejecting_a_match_lists_the_voter_absent(client, ws, boss, owner_conn):
    iid, rows = started(client, boss, ws)
    assert resolve(client, boss, iid, rows[4], False).status_code == 200   # Mahesh: not the same man
    absent = all_rows(client, boss, iid, match_status="absent_from_current_roll")
    assert sorted(r["serial_no"] for r in absent) == [3, 4]


def test_a_voter_another_row_has_cannot_be_chosen(client, ws, boss, owner_conn):
    iid, rows = started(client, boss, ws)
    asha = voter(owner_conn, ws, 1)["id"]
    got = resolve(client, boss, iid, rows[4], True, asha)
    assert got.status_code == 409 and code(got) == "voter_taken" and got.json()["error"]["row_no"] == 2


@pytest.mark.parametrize("row_no, accept, voter_choice, status, error", [
    (8, True, None, 422, "validation_error"),      # absent rows follow the matches
    (7, True, None, 422, "validation_error"),      # an unreadable row can only be skipped
    (3, False, "asha", 422, "validation_error"),   # a chosen voter means accept
    (6, True, "asha", 422, "validation_error"),    # a repeated row is not given a voter
    (4, True, "other", 404, "not_found"),          # a voter outside the constituency
])
def test_resolve_refuses(client, ws, boss, owner_conn, make_workspace, row_no, accept, voter_choice, status, error):
    iid, rows = started(client, boss, ws)
    choice = {"asha": voter(owner_conn, ws, 1)["id"], "other": uuid.uuid4(), None: None}[voter_choice]
    got = resolve(client, boss, iid, rows[row_no], accept, choice)
    assert got.status_code == status and code(got) == error


def test_a_row_of_another_import_is_not_found(client, ws, boss, owner_conn):
    iid, rows = started(client, boss, ws)
    other = uuid.uuid4()
    owner_conn.execute("""INSERT INTO app.roll_versions (id, tenant_id, local_body_id, list_type, title, status)
                          VALUES (%s, %s, %s, 'main', 'other', 'review')""", (other, ws.tenant, ws.local_body))
    got = client.post(f"{API}/rolls/imports/{other}/rows/{rows[3]['id']}/resolve", headers=boss, json={"accept": True})
    assert got.status_code == 404


# --- apply: the hard cases ---------------------------------------------------------------------------------
def test_a_rejected_match_with_the_same_epic_cannot_be_added(client, ws, boss, owner_conn):
    iid, rows = started(client, boss, ws)
    for no, accept in ((3, False), (4, True), (6, True), (7, False)):
        resolve(client, boss, iid, rows[no], accept)
    got = client.post(f"{API}/rolls/imports/{iid}/apply", headers=boss)
    assert got.status_code == 409 and code(got) == "epic_in_use" and got.json()["error"]["row_nos"] == [3]
    assert voter(owner_conn, ws, 2)["first_name_en"] == "Prakash"   # nothing applied


def test_serial_numbers_that_swap_and_shift(client, ws, boss, owner_conn):
    """Asha 1 -> 2, Prakash 2 -> 1 (a swap), Sunita 3 -> 4 while Mahesh 4 -> 5 (a chain)."""
    rows = [(1, 2, "TST1000001", "Asha Naik", "Naik", "Ramesh Naik", "Female", 30, "false"),
            (1, 1, "TST1000002", "Prakash Kamat", "Kamat", "Vasant Kamat", "Male", 52, "false"),
            (1, 4, "TST1000003", "Sunita Parab", "Parab", "Mohan Parab", "Female", 41, "false"),
            (1, 5, "", "Mahesh Shirodkar", "Shirodkar", "Dilip Shirodkar", "Male", 36, "false")]
    iid, got_rows = started(client, boss, ws, csv_bytes(rows))
    assert resolve(client, boss, iid, got_rows[5], True).status_code == 200   # Mahesh: alike, accept
    imp = client.post(f"{API}/rolls/imports/{iid}/apply", headers=boss)
    assert imp.status_code == 200, imp.text
    now = dict(owner_conn.execute("SELECT first_name_en, serial_no FROM app.voters WHERE tenant_id = %s "
                                  "AND roll_status = 'active'", (ws.tenant,)).fetchall())
    assert now == {"Asha": 2, "Prakash": 1, "Sunita": 4, "Mahesh": 5}


def test_a_deleted_entry_is_deleted_in_roll_not_dead(client, ws, boss, owner_conn):
    rows = [(1, 3, "TST1000003", "Sunita Parab", "Parab", "Mohan Parab", "Female", 41, "true")]
    iid, _ = started(client, boss, ws, csv_bytes(rows))
    assert client.post(f"{API}/rolls/imports/{iid}/apply", headers=boss).status_code == 200
    v3 = voter(owner_conn, ws, 3)
    assert (v3["roll_status"], v3["deletion_reason"], v3["deleted_at"]) == ("deleted_in_roll", None, None)


def test_an_absent_voter_listed_again_is_back(client, ws, boss, owner_conn):
    owner_conn.execute("UPDATE app.voters SET roll_status = 'absent_from_current_roll' WHERE tenant_id = %s "
                       "AND serial_no = 3", (ws.tenant,))
    rows = [(1, 3, "TST1000003", "Sunita Parab", "Parab", "Mohan Parab", "Female", 41, "false")]
    iid, got = started(client, boss, ws, csv_bytes(rows))
    assert "back in the roll" in got[2]["match_notes"]
    client.post(f"{API}/rolls/imports/{iid}/apply", headers=boss)
    assert voter(owner_conn, ws, 3)["roll_status"] == "active"


def test_a_part_not_on_record_gets_a_ward_and_a_booth(client, ws, boss, owner_conn):
    rows = [(7, 1, "TST7000001", "Ravi Sawant", "Sawant", "", "Male", 40, "false")]
    iid, _ = started(client, boss, ws, csv_bytes(rows))
    assert client.post(f"{API}/rolls/imports/{iid}/apply", headers=boss).status_code == 200
    place = owner_conn.execute(
        """SELECT w.level::text, w.number, b.level::text, b.parent_id = w.id, lb.id
             FROM app.voters v JOIN app.geo_units b ON b.id = v.booth_id JOIN app.geo_units w ON w.id = v.ward_id
             JOIN app.geo_units lb ON lb.id = w.parent_id
            WHERE v.tenant_id = %s AND v.epic_no = 'TST7000001'""", (ws.tenant,)).fetchone()
    assert place == ("ward", 7, "booth", True, ws.local_body)
    assert voter(owner_conn, ws, 1)["roll_status"] == "active"   # part 1 is not in the file: nobody absent


def test_apply_once(client, ws, boss):
    rows = [(1, 1, "TST1000001", "Asha Naik", "Naik", "Ramesh Naik", "Female", 30, "false")]
    iid, _ = started(client, boss, ws, csv_bytes(rows))
    assert client.post(f"{API}/rolls/imports/{iid}/apply", headers=boss).status_code == 200
    again = client.post(f"{API}/rolls/imports/{iid}/apply", headers=boss)
    assert again.status_code == 409 and code(again) == "import_closed"


# --- discard ---------------------------------------------------------------------------------------------
def test_discard(client, ws, boss, owner_conn):
    iid, rows = started(client, boss, ws)
    got = client.post(f"{API}/rolls/imports/{iid}/discard", headers=boss)
    assert got.status_code == 200 and got.json()["status"] == "discarded"
    assert client.post(f"{API}/rolls/imports/{iid}/discard", headers=boss).status_code == 200   # again: fine
    assert code(client.post(f"{API}/rolls/imports/{iid}/apply", headers=boss)) == "import_closed"
    assert code(resolve(client, boss, iid, rows[3], True)) == "import_closed"
    assert voter(owner_conn, ws, 3)["roll_status"] == "active"
    assert upload(client, boss, ws, csv_bytes()).status_code == 202   # the constituency is free again


def test_an_applied_import_cannot_be_discarded(client, ws, boss):
    rows = [(1, 1, "TST1000001", "Asha Naik", "Naik", "Ramesh Naik", "Female", 30, "false")]
    iid, _ = started(client, boss, ws, csv_bytes(rows))
    client.post(f"{API}/rolls/imports/{iid}/apply", headers=boss)
    got = client.post(f"{API}/rolls/imports/{iid}/discard", headers=boss)
    assert got.status_code == 409 and code(got) == "import_closed"
