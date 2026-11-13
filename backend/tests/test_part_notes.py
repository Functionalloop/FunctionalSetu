"""Part notes (7.11): GET/PUT /booths/{id}/note, push type part_note, the pull's part_notes.

Fake data only. Role / login / other-workspace / other-area rules: test_endpoint_rules.py.
"""

from __future__ import annotations

import uuid

import pytest

from conftest import bearer, login, phone
from test_sync_pull import download

API = "/api/v1"


@pytest.fixture
def ws(make_workspace, owner_conn, client, set_device_status):
    w = make_workspace("notes", extra_users={"agent1": "booth_agent"})
    owner_conn.execute("INSERT INTO app.user_area_assignments (tenant_id, user_id, geo_unit_id) VALUES (%s, %s, %s)",
                       (w.tenant, w.users["agent1"], w.booths[0]))

    def phone_user(username):
        t = login(client, w, username, device=phone(f"phone-notes-{username}")).json()
        set_device_status(t["device"]["id"], "approved")
        return bearer(t)

    w.surveyor, w.agent, w.sup = phone_user("survey1"), phone_user("agent1"), phone_user("sup1")
    w.b1 = w.booths[0]
    return w


def note_url(booth):
    return f"{API}/booths/{booth}/note"


def push(client, headers, booth, base, note):
    r = client.post(f"{API}/sync/push", headers=headers, json={"items": [
        {"id": str(uuid.uuid4()), "type": "part_note", "entity_id": str(booth), "base_version": base,
         "data": {"note": note}}]})
    assert r.status_code == 200, r.text
    return r.json()["results"][0]


def notes(d) -> dict[str, tuple[str, int]]:
    return {r["booth_id"]: (r["note"], r["version"]) for p in d.pages for r in p["part_notes"]}


def test_no_note_yet_reads_as_version_0(client, ws):
    r = client.get(note_url(ws.b1), headers=ws.agent)  # a booth agent reads
    assert r.status_code == 200, r.text
    assert (r.json()["note"], r.json()["version"], r.json()["updated_by"]) == ("", 0, None)


def test_save_then_stale_save_is_409_with_the_server_copy(client, ws, owner_conn):
    first = client.put(note_url(ws.b1), headers=ws.surveyor, json={"note": "Lane 3 dogs", "version": 0})
    assert first.status_code == 200, first.text
    assert (first.json()["note"], first.json()["version"]) == ("Lane 3 dogs", 1)
    assert first.json()["updated_by"] == str(ws.users["survey1"])

    stale = client.put(note_url(ws.b1), headers=ws.sup, json={"note": "Other text", "version": 0})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "version_conflict"
    assert stale.json()["error"]["current"]["note"] == "Lane 3 dogs"

    second = client.put(note_url(ws.b1), headers=ws.sup, json={"note": "Lane 3 dogs; temple on Sunday", "version": 1})
    assert second.json()["version"] == 2
    assert client.get(note_url(ws.b1), headers=ws.agent).json()["note"] == "Lane 3 dogs; temple on Sunday"
    assert owner_conn.execute("SELECT count(*) FROM app.part_notes WHERE booth_id = %s", (ws.b1,)).fetchone()[0] == 1


def test_too_long_is_422(client, ws):
    r = client.put(note_url(ws.b1), headers=ws.surveyor, json={"note": "x" * 2001, "version": 0})
    assert r.status_code == 422
    assert client.put(note_url(ws.b1), headers=ws.surveyor, json={"note": "x" * 2000, "version": 0}).status_code == 200


def test_note_saved_offline_reaches_a_second_phone_on_its_next_sync(client, ws):
    before = download(client, ws.agent)  # the second phone's last full download
    assert notes(before) == {}
    sent = push(client, ws.surveyor, ws.b1, 0, "Meet at the school")  # the first phone's outbox
    assert sent["status"] == "applied" and sent["part_note"]["version"] == 1

    delta = download(client, ws.agent, since=before.first["watermark"])
    assert notes(delta) == {str(ws.b1): ("Meet at the school", 1)}
    assert notes(download(client, ws.sup)) == {str(ws.b1): ("Meet at the school", 1)}  # first download too
    again = download(client, ws.agent, since=delta.first["watermark"])
    assert notes(again) == {}  # nothing new


def test_stale_push_is_a_conflict_not_a_lost_note(client, ws, owner_conn):
    assert push(client, ws.sup, ws.b1, 0, "Supervisor text")["status"] == "applied"
    r = push(client, ws.surveyor, ws.b1, 0, "Phone text")  # written offline on top of no note
    assert r["status"] == "conflict" and r["conflict_fields"] == ["note"]
    assert r["part_note"]["note"] == "Supervisor text"
    assert client.get(note_url(ws.b1), headers=ws.surveyor).json()["note"] == "Supervisor text"  # nothing written
    assert owner_conn.execute("SELECT count(*) FROM app.sync_conflicts WHERE tenant_id = %s",
                              (ws.tenant,)).fetchone()[0] == 0
    same = push(client, ws.surveyor, ws.b1, 0, "Supervisor text")  # stale but the same text
    assert same["status"] == "applied" and same["part_note"]["version"] == 1
    mine = push(client, ws.surveyor, ws.b1, 1, "Phone text")  # "keep mine": on top of the server's version
    assert mine["status"] == "applied" and mine["part_note"]["version"] == 2


def test_booth_agent_and_other_part_cannot_write_by_push(client, ws, owner_conn):
    agent = push(client, ws.agent, ws.b1, 0, "Agent text")
    assert agent["status"] == "rejected" and agent["error"]["code"] == "forbidden_role"
    outside = push(client, ws.surveyor, ws.booths[1], 0, "Other part")  # survey1 works in booth 1 only
    assert outside["status"] == "rejected" and outside["error"]["code"] == "not_found"
    assert owner_conn.execute("SELECT count(*) FROM app.part_notes WHERE tenant_id = %s", (ws.tenant,)).fetchone()[0] == 0
