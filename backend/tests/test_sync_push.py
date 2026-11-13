"""POST /sync/push: retries apply once, stale versions become conflicts, each item has its own result.

Fake data only. Login / phone-state rules: test_endpoint_rules.py.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import bearer, login, phone

API = "/api/v1"


@pytest.fixture
def ws(make_workspace, owner_conn, client, set_device_status):
    w = make_workspace("push", extra_users={"agent1": "booth_agent"})
    owner_conn.execute("INSERT INTO app.user_area_assignments (tenant_id, user_id, geo_unit_id) VALUES (%s, %s, %s)",
                       (w.tenant, w.users["agent1"], w.booths[0]))
    w.v = []
    for i, booth in enumerate([w.booths[0]] * 3 + [w.booths[1]]):
        vid = uuid.uuid4()
        owner_conn.execute("""INSERT INTO app.voters (id, tenant_id, local_body_id, ward_id, booth_id, part_no,
                                  serial_no, gender, first_name_en) VALUES (%s, %s, %s, %s, %s, 1, %s, 'F', 'Fake')""",
                           (vid, w.tenant, w.local_body, w.ward, booth, i + 1))
        w.v.append(vid)  # v[0..2] booth 1, v[3] booth 2

    def phone_user(username, uid):
        t = login(client, w, username, device=phone(uid)).json()
        set_device_status(t["device"]["id"], "approved")
        return bearer(t)

    w.surveyor = phone_user("survey1", "phone-push-0001")
    w.agent = phone_user("agent1", "phone-push-0002")
    w.supervisor = phone_user("sup1", "phone-push-0003")
    return w


def item(voter, base=0, mid=None, **data):
    return {"id": str(mid or uuid.uuid4()), "type": "survey", "entity_id": str(voter), "base_version": base,
            "changed_at": "2026-11-12T10:00:00Z", "data": data}


def push(client, headers, *items):
    r = client.post(f"{API}/sync/push", headers=headers, json={"items": list(items)})
    assert r.status_code == 200, r.text
    return r.json()["results"]


def survey_row(owner_conn, voter):
    return owner_conn.execute("SELECT version, notes, mobile_1 FROM app.voter_surveys WHERE voter_id = %s",
                              (voter,)).fetchone()


def count(owner_conn, sql, *args) -> int:
    return owner_conn.execute(sql, args).fetchone()[0]


def test_same_batch_twice_changes_data_once(client, ws, owner_conn):
    batch = [item(ws.v[0], notes="first visit"), item(ws.v[1], mobile_1="9876543210")]
    first = push(client, ws.surveyor, *batch)
    assert [r["status"] for r in first] == ["applied", "applied"] and not any(r["duplicate"] for r in first)
    assert first[0]["survey"]["version"] == 1
    audit = count(owner_conn, "SELECT count(*) FROM app.audit_log WHERE tenant_id = %s AND entity_type = 'voter_surveys'",
                  ws.tenant)

    again = push(client, ws.surveyor, *batch)
    assert [(r["status"], r["duplicate"]) for r in again] == [("applied", True), ("applied", True)]
    assert survey_row(owner_conn, ws.v[0]) == (1, "first visit", None)
    assert survey_row(owner_conn, ws.v[1])[0] == 1
    assert count(owner_conn, "SELECT count(*) FROM app.audit_log WHERE tenant_id = %s AND entity_type = 'voter_surveys'",
                 ws.tenant) == audit  # nothing written the second time
    assert count(owner_conn, "SELECT count(*) FROM app.sync_mutations WHERE tenant_id = %s", ws.tenant) == 2


def test_parallel_retries_apply_once(client, ws, owner_conn):
    batch = [item(ws.v[0], notes="once"), item(ws.v[1], notes="once too")]
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: push(client, ws.surveyor, *batch), range(6)))
    fresh = [r for resp in responses for r in resp if not r["duplicate"]]
    assert len(fresh) == 2  # each item applied by exactly one request
    assert all(r["status"] == "applied" for resp in responses for r in resp)
    assert survey_row(owner_conn, ws.v[0])[0] == 1 and survey_row(owner_conn, ws.v[1])[0] == 1
    assert count(owner_conn, "SELECT count(*) FROM app.sync_mutations WHERE tenant_id = %s", ws.tenant) == 2


def test_booth_agent_survey_is_rejected(client, ws, owner_conn):
    [r] = push(client, ws.agent, item(ws.v[0], notes="not my job"))
    assert r["status"] == "rejected" and r["error"]["code"] == "forbidden_role"
    assert survey_row(owner_conn, ws.v[0]) is None


def test_each_item_gets_its_own_result(client, ws, owner_conn):
    client.put(f"{API}/voters/{ws.v[2]}/survey", headers=ws.supervisor, json={"version": 0, "notes": "server"})
    results = push(client, ws.surveyor,
                   item(ws.v[0], notes="good"),
                   item(ws.v[1], mobile_1="12345"),          # invalid mobile
                   item(ws.v[3], notes="booth 2"),           # outside the surveyor's area
                   item(ws.v[2], notes="phone"),             # base 0 but the server has version 1
                   item(ws.v[1], notes="still fine"))        # the bad item before did not stop the batch
    assert [r["status"] for r in results] == ["applied", "rejected", "rejected", "conflict", "applied"]
    assert results[1]["error"]["code"] == "validation_error" and "mobile_1" in results[1]["error"]["message"]
    assert results[2]["error"]["code"] == "not_found"
    assert survey_row(owner_conn, ws.v[3]) is None and survey_row(owner_conn, ws.v[2])[1] == "server"


def test_stale_version_becomes_conflict_rows(client, ws, owner_conn):
    h = ws.supervisor
    client.put(f"{API}/voters/{ws.v[0]}/survey", headers=h, json={"version": 0, "notes": "a", "mobile_1": "9876543210"})
    client.put(f"{API}/voters/{ws.v[0]}/survey", headers=h, json={"version": 1, "notes": "b", "mobile_1": "9876543210"})
    [r] = push(client, ws.surveyor, item(ws.v[0], base=1, notes="phone", mobile_1="9876543210"))
    assert r["status"] == "conflict" and r["conflict_fields"] == ["notes"]
    assert r["survey"]["version"] == 2 and r["survey"]["notes"] == "b"  # the server copy
    rows = owner_conn.execute(
        """SELECT field_name, client_value, server_value, client_user_id, server_user_id, status::text
             FROM app.sync_conflicts WHERE entity_id = %s""", (ws.v[0],)).fetchall()
    assert rows == [("notes", "phone", "b", ws.users["survey1"], ws.users["sup1"], "open")]
    assert survey_row(owner_conn, ws.v[0])[:2] == (2, "b")  # nothing overwritten

    [again] = push(client, ws.surveyor, {**item(ws.v[0], base=1, notes="phone", mobile_1="9876543210"),
                                         "id": r["id"]})
    assert again["status"] == "conflict" and again["duplicate"] is True
    assert count(owner_conn, "SELECT count(*) FROM app.sync_conflicts WHERE entity_id = %s", ws.v[0]) == 1


def test_stale_but_identical_is_applied_without_conflict(client, ws, owner_conn):
    client.put(f"{API}/voters/{ws.v[0]}/survey", headers=ws.supervisor, json={"version": 0, "notes": "same"})
    [r] = push(client, ws.surveyor, item(ws.v[0], base=0, notes="same"))
    assert r["status"] == "applied" and r["survey"]["version"] == 1
    assert count(owner_conn, "SELECT count(*) FROM app.sync_conflicts WHERE entity_id = %s", ws.v[0]) == 0


def test_two_edits_of_one_voter_in_one_batch(client, ws, owner_conn):
    results = push(client, ws.surveyor, item(ws.v[0], base=0, notes="one"), item(ws.v[0], base=1, notes="two"))
    assert [r["status"] for r in results] == ["applied", "applied"]
    assert survey_row(owner_conn, ws.v[0])[:2] == (2, "two")


def test_rejected_item_retried_gives_same_result(client, ws):
    bad = item(ws.v[0], mobile_1="12345")
    first, = push(client, ws.surveyor, bad)
    again, = push(client, ws.surveyor, bad)
    assert again["duplicate"] is True and again["status"] == "rejected" and again["error"] == first["error"]


def test_location_and_version_in_data(client, ws, owner_conn):
    [r] = push(client, ws.surveyor, item(ws.v[0], base=0, version=99, notes="x",
                                        location={"lat": 15.6, "lng": 73.8, "accuracy_m": 9}))
    assert r["status"] == "applied" and r["survey"]["version"] == 1 and r["survey"]["lat"] == 15.6


def test_removed_voter_is_rejected(client, ws, owner_conn):
    owner_conn.execute("UPDATE app.voters SET deleted_at = now() WHERE id = %s", (ws.v[0],))
    [r] = push(client, ws.surveyor, item(ws.v[0], notes="x"))
    assert r["status"] == "rejected" and r["error"]["code"] == "not_found"


def test_web_login_without_phone_cannot_push(client, ws):
    h = bearer(login(client, ws, "sup1").json())
    r = client.post(f"{API}/sync/push", headers=h, json={"items": [item(ws.v[0], notes="x")]})
    assert r.status_code == 403 and r.json()["error"]["code"] == "device_required"


def test_batch_limits_and_unknown_type(client, ws):
    assert push(client, ws.surveyor) == []
    too_many = [item(ws.v[0]) for _ in range(501)]
    assert client.post(f"{API}/sync/push", headers=ws.surveyor, json={"items": too_many}).status_code == 422
    odd = {**item(ws.v[0]), "type": "teleport"}
    assert client.post(f"{API}/sync/push", headers=ws.surveyor, json={"items": [odd]}).status_code == 422


def test_pushed_survey_comes_back_in_the_next_pull(client, ws):
    w = client.get(f"{API}/sync/pull", headers=ws.surveyor).json()["watermark"]
    push(client, ws.surveyor, item(ws.v[0], notes="from the phone"))
    pages, cursor = [], None
    while True:
        params = {"cursor": cursor} if cursor else {"since": w}
        pages.append(client.get(f"{API}/sync/pull", headers=ws.surveyor, params=params).json())
        cursor = pages[-1]["next_cursor"]
        if not cursor:
            break
    surveys = [s for p in pages for s in p["surveys"]]
    assert [(s["voter_id"], s["notes"], s["version"]) for s in surveys] == [(str(ws.v[0]), "from the phone", 1)]


@pytest.mark.parametrize("ptype", ["voted", "part_note", "slip_event"])
def test_types_not_built_are_rejected_and_not_recorded(client, ws, owner_conn, ptype):
    it = {**item(ws.v[0]), "type": ptype}
    for _ in range(2):  # a retry gets the same answer, never a stored "duplicate"
        [r] = push(client, ws.surveyor, it)
        assert r["status"] == "rejected" and r["error"]["code"] == "not_implemented" and r["duplicate"] is False
    assert count(owner_conn, "SELECT count(*) FROM app.sync_mutations WHERE tenant_id = %s", ws.tenant) == 0
