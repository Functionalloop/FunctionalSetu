"""Data quality and mobile number sheets (10.5): app/duplicates.py, app/mobile_match.py,
app/routers/data_quality.py. Fake voters and fake numbers only.
Generic rules (401, 403 per role, other workspace and area): test_endpoint_rules.py."""

from __future__ import annotations

import csv
import io
import uuid

import pytest
from sqlalchemy import text

from app import mobile_match, worker
from app.db import transaction
from app.duplicates import find_pairs
from conftest import bearer, login

API = "/api/v1"

# serial, booth index, EPIC, first, last, gender, age, relative, house, repeated in roll
VOTERS = [
    (1, 0, "DQT1000001", "Asha", "Naik", "F", 30, "Ramesh Naik", "H-1", False),
    (2, 1, "DQT1000002", "Asha", "Naik", "F", 31, "Ramesh Naik", "H-9", False),     # pair with 1
    (3, 0, "DQT1000003", "Prakash", "Kamat", "M", 52, "Vasant Kamat", "H-2", False),
    (4, 0, None, "Sunita", "Parab", "F", 41, "Mohan Parab", "H-3", False),
    (5, 0, "DQT1000005", "Sunil", "Parab", "M", 45, "Mohan Parab", "H-3", False),
    (6, 1, "DQT1000006", "Prakash", "Kamat", "M", 70, "Vasant Kamat", "H-5", False),  # too old to pair with 3
    (7, 0, "DQT1000007", "Ravi", "Gawas", "M", 25, "Sitaram Gawas", "H-4", True),
    (8, 1, "DQT1000008", "Ravi", "Gawas", "M", None, "Sitaram Gawas", "H-8", True),  # pair with 7 (roll flag)
]


@pytest.fixture
def ws(make_workspace, owner_conn):
    ws = make_workspace("quality")
    ws.v = {}
    for serial, booth, epic, first, last, gender, age, rel, house, repeated in VOTERS:
        ws.v[serial] = owner_conn.execute(
            """INSERT INTO app.voters (tenant_id, local_body_id, ward_id, booth_id, part_no, serial_no, epic_no,
                                       first_name_en, last_name_en, gender, age, relative_name_en, house_no,
                                       is_repeated_in_roll)
               VALUES (%s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (ws.tenant, ws.local_body, ws.ward, ws.booths[booth], serial, epic, first, last, gender, age, rel, house,
             repeated)).fetchone()[0]
    return ws


@pytest.fixture
def paired(ws):
    with transaction(ws.tenant) as conn:
        assert find_pairs(conn, ws.local_body) == 2
    return ws


@pytest.fixture
def boss(client, ws):
    return bearer(login(client, ws, "boss").json())


@pytest.fixture
def admin(client, ws):
    return bearer(login(client, ws, "admin1").json())


@pytest.fixture
def sup(client, ws):
    return bearer(login(client, ws, "sup1").json())


def code(resp) -> str:
    return resp.json()["error"]["code"]


def pairs(client, h, **params) -> list[dict]:
    r = client.get(f"{API}/data-quality/duplicates", headers=h, params=params)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def summary(client, h, **params) -> dict:
    r = client.get(f"{API}/data-quality/summary", headers=h, params=params)
    assert r.status_code == 200, r.text
    return r.json()


# --- pairs ---------------------------------------------------------------------------------------------
def test_pairs_are_same_name_relative_gender_and_close_age(client, paired, sup):
    found = {tuple(sorted((p["voter_a"]["serial_no"], p["voter_b"]["serial_no"]))): p["source"]
             for p in pairs(client, sup)}
    assert found == {(1, 2): "fuzzy_match", (7, 8): "roll_flag"}
    with transaction(paired.tenant) as conn:
        assert find_pairs(conn, paired.local_body) == 0   # stored once


def test_summary_counts(client, paired, boss, sup, owner_conn):
    s = summary(client, sup)
    assert s == {"voters": 8, "no_mobile": 8, "no_dob": 8, "possible_duplicates": 2, "repeated_in_roll": 2,
                 "shifted": 0, "doubtful_dead": 0}
    v = paired.v
    assert client.put(f"{API}/voters/{v[4]}/survey", headers=sup,
                      json={"version": 0, "mobile_1": "9876500010", "dob": "1985-01-02", "has_new_address": True,
                            "new_address_en": "Mapusa"}).status_code == 200
    r = client.post(f"{API}/voters/{v[5]}/visits", headers=sup,
                    json={"id": str(uuid.uuid4()), "outcome": "shifted", "visited_at": "2026-11-13T10:00:00Z"})
    assert r.status_code == 201, r.text
    owner_conn.execute("INSERT INTO app.voter_surveys (voter_id, tenant_id, dead_marked) VALUES (%s, %s, true)",
                       (v[3], paired.tenant))
    s = summary(client, sup)
    assert (s["no_mobile"], s["no_dob"], s["shifted"], s["doubtful_dead"]) == (7, 7, 2, 1)
    s = summary(client, boss, ward_id=str(paired.ward))
    assert s["voters"] == 8 and s["possible_duplicates"] == 2


def test_source_filter_and_bad_source(client, paired, sup):
    assert [p["source"] for p in pairs(client, sup, source="roll_flag")] == ["roll_flag"]
    r = client.get(f"{API}/data-quality/duplicates", headers=sup, params={"source": "guess"})
    assert r.status_code == 422


def _pair(client, h, serials: tuple[int, int]) -> dict:
    [p] = [p for p in pairs(client, h, unchecked_only=False)
           if {p["voter_a"]["serial_no"], p["voter_b"]["serial_no"]} == set(serials)]
    return p


def resolve(client, h, pair_id, same: bool, keep=None):
    body = {"same_person": same, **({"keep_voter_id": str(keep)} if keep else {})}
    return client.post(f"{API}/data-quality/duplicates/{pair_id}/resolve", headers=h, json=body)


def test_a_supervisor_marks_same_person_and_the_super_admin_hides_one(client, paired, sup, boss, owner_conn):
    p = _pair(client, sup, (1, 2))
    v = paired.v
    r = resolve(client, sup, p["id"], True)
    assert r.status_code == 200 and r.json()["status"] == "same_person"
    assert owner_conn.execute("SELECT count(*) FROM app.voters WHERE id = ANY(%s) AND deleted_at IS NOT NULL",
                              ([v[1], v[2]],)).fetchone()[0] == 0
    r = resolve(client, sup, p["id"], True, keep=v[1])
    assert r.status_code == 403 and code(r) == "forbidden_role"

    r = resolve(client, boss, p["id"], True, keep=v[1])
    assert r.status_code == 200, r.text
    assert r.json()["voter_b"]["deleted_at"] is not None or r.json()["voter_a"]["deleted_at"] is not None
    hidden = owner_conn.execute("SELECT id FROM app.voters WHERE id = ANY(%s) AND deleted_at IS NOT NULL",
                                ([v[1], v[2]],)).fetchall()
    assert hidden == [(v[2],)]
    assert owner_conn.execute("SELECT action::text, reason, reference FROM app.voter_roll_edits WHERE voter_id = %s",
                              (v[2],)).fetchall() == [("remove", "duplicate", f"duplicate pair {p['id']}")]
    assert [x["source"] for x in pairs(client, boss)] == ["roll_flag"]   # unchecked only, the other is gone
    assert summary(client, boss)["possible_duplicates"] == 1 and summary(client, boss)["voters"] == 7


@pytest.mark.parametrize("same, keep_serial", [(False, 1), (True, 3)])
def test_resolve_refuses_a_bad_keep(client, paired, boss, same, keep_serial):
    p = _pair(client, boss, (1, 2))
    r = resolve(client, boss, p["id"], same, keep=paired.v[keep_serial])
    assert r.status_code == 422 and code(r) == "validation_error"


def test_different_people_leaves_the_list(client, paired, sup):
    p = _pair(client, sup, (7, 8))
    assert resolve(client, sup, p["id"], False).json()["status"] == "different_people"
    assert [x["source"] for x in pairs(client, sup)] == ["fuzzy_match"]
    assert _pair(client, sup, (7, 8))["status"] == "different_people"


def test_a_voter_added_by_hand_is_paired(client, paired, boss):
    r = client.post(f"{API}/voters", headers=boss,
                    json={"booth_id": str(paired.booths[1]), "serial_no": 30, "gender": "M", "first_name_en": "Prakash",
                          "last_name_en": "Kamat", "relative_name_en": "Vasant Kamat", "age": 53,
                          "reason": "supplementary_list"})
    assert r.status_code == 201, r.text
    assert _pair(client, boss, (3, 30))["source"] == "fuzzy_match"


def test_pairs_page_by_cursor(client, paired, boss):
    r = client.get(f"{API}/data-quality/duplicates", headers=boss, params={"limit": 1})
    first = r.json()
    r = client.get(f"{API}/data-quality/duplicates", headers=boss, params={"limit": 1, "cursor": first["next_cursor"]})
    assert len(first["items"]) == len(r.json()["items"]) == 1 and r.json()["next_cursor"] is None
    assert first["items"][0]["id"] != r.json()["items"][0]["id"]


# --- mobile number sheets ------------------------------------------------------------------------------
SHEET = [  # name, mobile, EPIC, house
    ("Kamat Prakash", "+91 98765 00001", "DQT1000003", ""),   # matched by EPIC (two voters have this name)
    ("Sunita Parab", "09876500002", "", ""),                  # matched by name (Sunil is only alike)
    ("Asha Naik", "9876500003", "", ""),                      # two Asha Naiks: to review
    ("Asha Naik", "9876500004", "", "H-9"),                   # the house number decides
    ("Nobody Here", "9876500005", "", ""),                    # not found
    ("Ravi Gawas", "12345", "", ""),                          # not a mobile: skipped
]


def sheet_bytes(rows=SHEET, header=("Name", "Mobile No", "EPIC", "House No")) -> bytes:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(header)
    w.writerows(rows)
    return out.getvalue().encode("utf-8")


def run_jobs() -> None:
    while worker.run_one({mobile_match.KIND: worker.HANDLERS[mobile_match.KIND]}):
        pass


def upload(client, h, data: bytes, name="numbers.csv"):
    return client.post(f"{API}/mobile-imports", headers=h, files={"file": (name, data, "application/octet-stream")})


def sheet(client, h, data=None) -> dict:
    r = upload(client, h, data or sheet_bytes())
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "queued" and r.json()["rows"] == []
    run_jobs()
    r = client.get(f"{API}/mobile-imports/{r.json()['id']}", headers=h)
    assert r.status_code == 200
    return r.json()


def mobiles(owner_conn, voter_id) -> tuple:
    return owner_conn.execute("SELECT mobile_1, mobile_2, is_surveyed FROM app.voter_surveys WHERE voter_id = %s",
                              (voter_id,)).fetchone()


def test_sheet_matches_and_stores_the_sure_numbers(client, ws, admin, owner_conn):
    s = sheet(client, admin)
    assert s["status"] == "done" and s["error"] is None
    assert (s["matched_count"], s["review_count"], s["not_found_count"]) == (3, 1, 1)
    rows = {r["row_no"]: r for r in s["rows"]}
    assert [r["status"] for r in s["rows"]][:2] == ["needs_review", "not_found"]   # to review first
    v = ws.v
    assert rows[1]["matched_voter_id"] == str(v[3]) and rows[1]["mobile"] == "9876500001"
    assert rows[2]["matched_voter_id"] == str(v[4])
    assert set(rows[3]["candidate_voter_ids"]) == {str(v[1]), str(v[2])}
    assert rows[4]["matched_voter_id"] == str(v[2])
    assert (rows[5]["status"], rows[6]["status"]) == ("not_found", "skipped")
    assert mobiles(owner_conn, v[3]) == ("9876500001", None, False)   # a survey row, not "surveyed"
    assert mobiles(owner_conn, v[2]) == ("9876500004", None, False)
    assert mobiles(owner_conn, v[1]) is None
    actor = owner_conn.execute("""SELECT actor_user_id FROM app.audit_log WHERE entity_type = 'voter_surveys'
                                    AND entity_id = %s""", (str(v[3]),)).fetchone()[0]
    assert actor == ws.users["admin1"]


def test_resolve_rows(client, ws, admin, owner_conn):
    s = sheet(client, admin)
    rows = {r["row_no"]: r for r in s["rows"]}
    url = f"{API}/mobile-imports/{s['id']}/rows"
    r = client.post(f"{url}/{rows[3]['id']}/resolve", headers=admin, json={"voter_id": str(ws.v[1])})
    assert r.status_code == 200, r.text
    assert (r.json()["matched_count"], r.json()["review_count"]) == (4, 0)
    assert mobiles(owner_conn, ws.v[1])[0] == "9876500003"
    r = client.post(f"{url}/{rows[5]['id']}/resolve", headers=admin, json={"voter_id": None})
    assert r.status_code == 200 and r.json()["not_found_count"] == 0
    assert {x["row_no"]: x["status"] for x in r.json()["rows"]}[5] == "skipped"
    again = client.post(f"{url}/{rows[3]['id']}/resolve", headers=admin, json={"voter_id": None})
    assert again.status_code == 409 and code(again) == "row_resolved"
    other = client.post(f"{url}/{rows[1]['id']}/resolve", headers=admin, json={"voter_id": None})
    assert other.status_code == 409


def test_second_number_then_review_when_both_are_taken(client, ws, admin, owner_conn):
    sheet(client, admin)   # voter 3 gets ...01
    s = sheet(client, admin, sheet_bytes([("Prakash Kamat", "9876500006", "DQT1000003", ""),
                                          ("Prakash Kamat", "9876500001", "DQT1000003", ""),    # has it already
                                          ("Prakash Kamat", "9876500007", "DQT1000003", "")]))
    assert mobiles(owner_conn, ws.v[3])[:2] == ("9876500001", "9876500006")
    rows = {r["row_no"]: r for r in s["rows"]}
    assert (rows[1]["status"], rows[2]["status"], rows[3]["status"]) == ("matched", "matched", "needs_review")
    assert rows[3]["candidate_voter_ids"] == [str(ws.v[3])]
    r = client.post(f"{API}/mobile-imports/{s['id']}/rows/{rows[3]['id']}/resolve", headers=admin,
                    json={"voter_id": str(ws.v[3])})
    assert r.status_code == 200
    assert mobiles(owner_conn, ws.v[3])[:2] == ("9876500001", "9876500007")   # a person chose: mobile_2 replaced


def test_a_number_saved_meanwhile_is_kept(ws, owner_conn):
    """A phone saves a survey between loading the voters and writing the sheet's numbers."""
    with transaction(ws.tenant, ws.users["admin1"]) as conn:
        voters = mobile_match.load_voters(conn, ws.local_body)
        conn.execute(text("""INSERT INTO app.voter_surveys (tenant_id, voter_id, mobile_1)
                             VALUES (app.current_tenant_id(), :v, '9876500099')"""), {"v": ws.v[3]})
        row = mobile_match.SheetRow(row_no=1, mobile_raw="9876500001", mobile="9876500001", epic_no="DQT1000003")
        mobile_match.match_rows(conn, ws.users["admin1"], [row], voters)
    assert row.status == "matched"
    assert mobiles(owner_conn, ws.v[3])[:2] == ("9876500099", "9876500001")


def test_resolve_with_an_unknown_voter_is_404(client, ws, admin):
    s = sheet(client, admin)
    row = next(r for r in s["rows"] if r["status"] == "needs_review")
    r = client.post(f"{API}/mobile-imports/{s['id']}/rows/{row['id']}/resolve", headers=admin,
                    json={"voter_id": str(uuid.uuid4())})
    assert r.status_code == 404


def test_a_sheet_is_seen_by_the_uploaders_team(client, ws, admin, boss):
    mine = sheet(client, admin)
    assert client.get(f"{API}/mobile-imports/{mine['id']}", headers=boss).status_code == 200
    theirs = sheet(client, boss)
    assert client.get(f"{API}/mobile-imports/{theirs['id']}", headers=admin).status_code == 404

    def listed(h, **params):
        return client.get(f"{API}/mobile-imports", headers=h, params=params).json()
    assert [s["id"] for s in listed(admin)["items"]] == [mine["id"]]
    page = listed(boss, limit=1)
    assert [s["id"] for s in page["items"]] == [theirs["id"]] and page["items"][0]["rows"] == []
    assert [s["id"] for s in listed(boss, limit=1, cursor=page["next_cursor"])["items"]] == [mine["id"]]


@pytest.mark.parametrize("data, error", [
    (sheet_bytes(header=("Name", "Phone number", "EPIC", "House")), None),
    (sheet_bytes(header=("Name", "Notes", "EPIC", "House")), "The sheet has no mobile number column"),
    (sheet_bytes(rows=[("Asha Naik", "12345", "", "")]), "No row has a 10-digit mobile number"),
])
def test_sheet_columns(client, ws, admin, data, error):
    s = sheet(client, admin, data)
    if error is None:
        assert s["status"] == "done" and s["matched_count"] == 3
    else:
        assert s["status"] == "failed" and s["error"].startswith(error) and s["rows"] == []


def test_upload_refuses_pdf_and_a_switched_off_feature(client, ws, admin, owner_conn):
    r = upload(client, admin, b"%PDF-1.4 ...", "numbers.pdf")
    assert r.status_code == 422 and code(r) == "unsupported_file"
    owner_conn.execute("UPDATE app.tenant_settings SET feature_mobile_import = false WHERE tenant_id = %s", (ws.tenant,))
    r = upload(client, admin, sheet_bytes())
    assert r.status_code == 403 and code(r) == "feature_off"
