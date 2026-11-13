"""Voter slips (7.7): POST /voters/{id}/slip-events and push type `slip_event`.

Fake data only. Role / login / other-workspace / other-area rules: test_endpoint_rules.py.
"""

from __future__ import annotations

import uuid

import pytest

from conftest import bearer, login, phone

API = "/api/v1"


@pytest.fixture
def ws(make_workspace, owner_conn, client, set_device_status):
    w = make_workspace("slip", extra_users={"agent1": "booth_agent"})
    w.v = []
    for i in range(2):
        vid = uuid.uuid4()
        owner_conn.execute("""INSERT INTO app.voters (id, tenant_id, local_body_id, ward_id, booth_id, part_no,
                                  serial_no, gender, first_name_en)
                              VALUES (%s, %s, %s, %s, %s, 1, %s, 'F', 'Fake')""",
                           (vid, w.tenant, w.local_body, w.ward, w.booths[0], i + 1))
        w.v.append(vid)
    owner_conn.execute("INSERT INTO app.user_area_assignments (tenant_id, user_id, geo_unit_id) VALUES (%s, %s, %s)",
                       (w.tenant, w.users["agent1"], w.booths[0]))

    def phone_user(username):
        t = login(client, w, username, device=phone(f"phone-slip-{username}")).json()
        set_device_status(t["device"]["id"], "approved")
        return bearer(t), uuid.UUID(t["device"]["id"])

    (w.surveyor, w.surveyor_phone), (w.agent, _) = phone_user("survey1"), phone_user("agent1")
    return w


def event(eid=None, channel="whatsapp", at="2026-11-13T10:00:00Z"):
    return {"id": str(eid or uuid.uuid4()), "channel": channel, "at": at}


def push(client, headers, voter, data, mid=None):
    it = {"id": str(mid or uuid.uuid4()), "type": "slip_event", "entity_id": str(voter), "base_version": 0, "data": data}
    r = client.post(f"{API}/sync/push", headers=headers, json={"items": [it]})
    assert r.status_code == 200, r.text
    return r.json()["results"][0]


def rows(owner_conn, ws):
    return owner_conn.execute("SELECT voter_id, channel::text, created_by, device_id, created_at, client_mutation_id "
                              "FROM app.slip_events WHERE tenant_id = %s ORDER BY created_at", (ws.tenant,)).fetchall()


def test_event_is_stored_with_who_which_phone_and_when(client, ws, owner_conn):
    e = event()
    r = client.post(f"{API}/voters/{ws.v[0]}/slip-events", headers=ws.surveyor, json=e)
    assert r.status_code == 204, r.text
    [(voter, channel, by, device, at, mid)] = rows(owner_conn, ws)
    assert (voter, channel, by, device, str(mid)) == (ws.v[0], "whatsapp", ws.users["survey1"], ws.surveyor_phone,
                                                     e["id"])
    assert at.isoformat().startswith("2026-11-13T10:00:00")  # the phone's time of sharing


def test_shared_offline_and_pushed_twice_is_stored_once(client, ws, owner_conn):
    e, mid = event(), uuid.uuid4()
    first = push(client, ws.surveyor, ws.v[0], e, mid=mid)
    assert first["status"] == "applied" and first["duplicate"] is False
    again = push(client, ws.surveyor, ws.v[0], e, mid=mid)  # retry of the same outbox item
    assert again["status"] == "applied" and again["duplicate"] is True
    rebuilt = push(client, ws.surveyor, ws.v[0], e)  # same event under a new outbox id
    assert rebuilt["status"] == "applied"
    assert client.post(f"{API}/voters/{ws.v[0]}/slip-events", headers=ws.surveyor, json=e).status_code == 204
    assert len(rows(owner_conn, ws)) == 1


def test_booth_agent_shares_slips_too(client, ws, owner_conn):
    assert push(client, ws.agent, ws.v[1], event(channel="sms"))["status"] == "applied"
    assert [r[1] for r in rows(owner_conn, ws)] == ["sms"]


def test_id_of_another_voters_event_is_409_and_rejected_in_push(client, ws):
    e = event()
    assert client.post(f"{API}/voters/{ws.v[0]}/slip-events", headers=ws.surveyor, json=e).status_code == 204
    r = client.post(f"{API}/voters/{ws.v[1]}/slip-events", headers=ws.surveyor, json=e)
    assert r.status_code == 409 and r.json()["error"]["code"] == "id_in_use"
    p = push(client, ws.surveyor, ws.v[1], e)
    assert p["status"] == "rejected" and p["error"]["code"] == "id_in_use"


def test_time_from_the_future_is_cut_to_now_and_bad_channel_is_refused(client, ws, owner_conn):
    assert client.post(f"{API}/voters/{ws.v[0]}/slip-events", headers=ws.surveyor,
                       json=event(at="2099-01-01T00:00:00Z")).status_code == 204
    assert rows(owner_conn, ws)[0][4].year < 2099
    bad = push(client, ws.surveyor, ws.v[0], event(channel="pigeon"))
    assert bad["status"] == "rejected" and bad["error"]["code"] == "validation_error"


def test_shows_in_information_updation(client, ws):
    push(client, ws.surveyor, ws.v[0], event())
    items = client.get(f"{API}/voters/{ws.v[0]}/history", headers=ws.surveyor).json()["items"]
    [h] = [i for i in items if i["kind"] == "slip"]
    assert (h["kind"], h["action"], h["by"]["username"]) == ("slip", "whatsapp", "survey1")
