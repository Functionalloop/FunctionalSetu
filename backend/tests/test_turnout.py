"""Polling day (8.1): POST /turnout/marks, DELETE /turnout/marks/{voter_id}, GET /turnout/summary,
the push types `voted` / `unvoted` and the pull's `turnout` phase.

Fake data only. Login / role / other-workspace / other-area rules: test_endpoint_rules.py.
"""

from __future__ import annotations

import uuid

import pytest

from conftest import bearer, login, phone

API = "/api/v1"


@pytest.fixture
def ws(make_workspace, owner_conn, client, set_device_status):
    """Booth 1: serials 1-5 (v[0..4]); booth 2: serials 1-2 (v[5], v[6]). agent1 and agent2 have booth 1."""
    w = make_workspace("turn", extra_users={"agent1": "booth_agent", "agent2": "booth_agent"})
    for agent in ("agent1", "agent2"):
        owner_conn.execute("INSERT INTO app.user_area_assignments (tenant_id, user_id, geo_unit_id) "
                           "VALUES (%s, %s, %s)", (w.tenant, w.users[agent], w.booths[0]))
    w.v = []
    for booth, serial in [(w.booths[0], s) for s in range(1, 6)] + [(w.booths[1], s) for s in (1, 2)]:
        vid = uuid.uuid4()
        owner_conn.execute("""INSERT INTO app.voters (id, tenant_id, local_body_id, ward_id, booth_id, part_no,
                                  serial_no, gender, first_name_en) VALUES (%s, %s, %s, %s, %s, 1, %s, 'F', 'Fake')""",
                           (vid, w.tenant, w.local_body, w.ward, booth, serial))
        w.v.append(vid)

    def phone_user(username):
        t = login(client, w, username, device=phone(f"phone-turn-{username}")).json()
        set_device_status(t["device"]["id"], "approved")
        return bearer(t), uuid.UUID(t["device"]["id"])

    (w.agent, w.agent_phone), (w.agent2, _) = phone_user("agent1"), phone_user("agent2")
    (w.surveyor, _), (w.supervisor, _) = phone_user("survey1"), phone_user("sup1")
    return w


def mark(client, headers, rid=None, status=200, **body):
    r = client.post(f"{API}/turnout/marks", headers=headers, json={"id": str(rid or uuid.uuid4()), **body})
    assert r.status_code == status, r.text
    return r.json()


def by_ids(*voters):
    return {"voter_ids": [str(v) for v in voters]}


def row(owner_conn, voter):
    return owner_conn.execute("""SELECT is_voted, marked_by, device_id, source::text, marked_at, cleared_by, cleared_at
                                 FROM app.voter_turnout WHERE voter_id = %s""", (voter,)).fetchone()


def voted(owner_conn, ws) -> set[uuid.UUID]:
    return {r[0] for r in owner_conn.execute("SELECT voter_id FROM app.voter_turnout WHERE tenant_id = %s AND is_voted",
                                             (ws.tenant,)).fetchall()}


# --- POST /turnout/marks --------------------------------------------------------------------------
def test_mark_by_voter_ids_stores_who_which_phone_and_how(client, ws, owner_conn):
    r = mark(client, ws.agent, **by_ids(ws.v[0], ws.v[1]), source="booth_list", marked_at="2026-11-10T09:15:00Z")
    assert r == {"marked": [str(ws.v[0]), str(ws.v[1])], "already": [], "not_found_serials": []}
    is_voted, by, device, source, at, cleared_by, cleared_at = row(owner_conn, ws.v[0])
    assert (is_voted, by, device, source) == (True, ws.users["agent1"], ws.agent_phone, "booth_list")
    assert at.isoformat().startswith("2026-11-10T09:15:00") and cleared_by is None and cleared_at is None


def test_mark_by_serials_skips_one_already_marked_and_reports_missing_serials(client, ws, owner_conn):
    mark(client, ws.agent, **by_ids(ws.v[2]))  # serial 3
    r = mark(client, ws.agent, booth_id=str(ws.booths[0]), serials="1, 3-5, 99", source="bulk_typed")
    assert r["marked"] == [str(v) for v in (ws.v[0], ws.v[3], ws.v[4])]
    assert r["already"] == [str(ws.v[2])] and r["not_found_serials"] == [99]
    assert voted(owner_conn, ws) == {ws.v[0], ws.v[2], ws.v[3], ws.v[4]}  # booth 2's serial 1 untouched
    assert row(owner_conn, ws.v[2])[3] == "single"  # the first mark is kept as it was


def test_same_voter_from_two_phones_leaves_one_mark(client, ws, owner_conn):
    first = mark(client, ws.agent, **by_ids(ws.v[0]))
    second = mark(client, ws.agent2, **by_ids(ws.v[0]))
    assert first["marked"] == [str(ws.v[0])] and second == {"marked": [], "already": [str(ws.v[0])],
                                                             "not_found_serials": []}
    assert owner_conn.execute("SELECT count(*) FROM app.voter_turnout WHERE voter_id = %s", (ws.v[0],)).fetchone()[0] == 1
    assert row(owner_conn, ws.v[0])[1] == ws.users["agent1"]


def test_booth_agent_cannot_mark_another_booth(client, ws, owner_conn):
    assert mark(client, ws.agent, status=404, **by_ids(ws.v[5]))["error"]["code"] == "not_found"
    mark(client, ws.agent, status=404, **by_ids(ws.v[0], ws.v[5]))  # one outside: nothing marked
    mark(client, ws.agent, status=404, booth_id=str(ws.booths[1]), serials="1-2")
    mark(client, ws.agent, status=404, booth_id=str(ws.ward), serials="1")  # a ward is not a booth
    assert voted(owner_conn, ws) == set()
    assert mark(client, ws.supervisor, booth_id=str(ws.booths[1]), serials="1-2")["marked"] == [
        str(ws.v[5]), str(ws.v[6])]  # the supervisor's ward holds both booths


def test_surveyor_gets_403(client, ws, owner_conn):
    r = mark(client, ws.surveyor, status=403, **by_ids(ws.v[0]))
    assert r["error"]["code"] == "forbidden_role"
    assert client.delete(f"{API}/turnout/marks/{ws.v[0]}", headers=ws.surveyor).status_code == 403
    assert client.get(f"{API}/turnout/summary", headers=ws.surveyor).status_code == 403
    assert voted(owner_conn, ws) == set()


@pytest.mark.parametrize("body", [
    {},
    {"voter_ids": ["V"], "booth_id": "B", "serials": "1"},  # both
    {"booth_id": "B"},                                       # booth without serials
    {"booth_id": "B", "serials": "5-3"},
    {"booth_id": "B", "serials": "0"},
    {"booth_id": "B", "serials": "1, two"},
    {"booth_id": "B", "serials": "1-2001"},
    {"voter_ids": ["V"], "source": "admin"},                 # admin is not a client source
])
def test_bad_bodies_are_422(client, ws, owner_conn, body):
    fill = {"V": str(ws.v[0]), "B": str(ws.booths[0])}
    body = {k: ([fill[x] for x in v] if isinstance(v, list) else fill.get(v, v)) for k, v in body.items()}
    assert mark(client, ws.agent, status=422, **body)["error"]["code"] == "validation_error"
    assert voted(owner_conn, ws) == set()


def test_only_voters_on_the_current_roll_can_be_marked(client, ws, owner_conn):
    owner_conn.execute("UPDATE app.voters SET roll_status = 'deleted_in_roll' WHERE id = %s", (ws.v[1],))
    r = mark(client, ws.agent, status=422, **by_ids(ws.v[0], ws.v[1]))
    assert r["error"]["code"] == "validation_error" and str(ws.v[1]) in r["error"]["message"]
    r = mark(client, ws.agent, booth_id=str(ws.booths[0]), serials="1-2")
    assert r["marked"] == [str(ws.v[0])] and r["not_found_serials"] == [2]
    s = client.get(f"{API}/turnout/summary", headers=ws.agent).json()
    assert (s["total"], s["voted"]) == (4, 1)


def test_offline_time_is_kept_and_a_future_time_becomes_now(client, ws, owner_conn):
    mark(client, ws.agent, **by_ids(ws.v[0]), marked_at="2999-01-01T00:00:00Z")
    now = owner_conn.execute("SELECT now()").fetchone()[0]
    assert abs((row(owner_conn, ws.v[0])[4] - now).total_seconds()) < 60


# --- retries and undo --------------------------------------------------------------------------
def test_repeat_request_marks_nothing_again_even_after_an_undo(client, ws, owner_conn):
    rid = uuid.uuid4()
    first = mark(client, ws.agent, rid, **by_ids(ws.v[0], ws.v[1]))
    assert client.delete(f"{API}/turnout/marks/{ws.v[0]}", headers=ws.agent2).status_code == 204
    again = mark(client, ws.agent, rid, **by_ids(ws.v[0], ws.v[1]))
    assert again == first  # the same answer; the undone mark stays undone
    assert voted(owner_conn, ws) == {ws.v[1]}
    # a new request does mark the voter again
    assert mark(client, ws.agent2, **by_ids(ws.v[0]))["marked"] == [str(ws.v[0])]
    is_voted, by, *_, cleared_by, cleared_at = row(owner_conn, ws.v[0])
    assert (is_voted, by, cleared_by, cleared_at) == (True, ws.users["agent2"], None, None)


def test_undo_keeps_the_row_and_says_who(client, ws, owner_conn):
    mark(client, ws.agent, **by_ids(ws.v[0]))
    for _ in range(2):  # nothing to undo the second time: still 204
        assert client.delete(f"{API}/turnout/marks/{ws.v[0]}", headers=ws.agent2).status_code == 204
    is_voted, by, *_, cleared_by, cleared_at = row(owner_conn, ws.v[0])
    assert (is_voted, by, cleared_by) == (False, ws.users["agent1"], ws.users["agent2"]) and cleared_at is not None
    assert client.delete(f"{API}/turnout/marks/{ws.v[1]}", headers=ws.agent).status_code == 204  # never marked
    assert row(owner_conn, ws.v[1]) is None
    assert client.delete(f"{API}/turnout/marks/{ws.v[5]}", headers=ws.agent).status_code == 404  # other booth


def test_marks_and_undo_are_in_the_history(client, ws, owner_conn):
    mark(client, ws.agent, **by_ids(ws.v[0]))
    client.delete(f"{API}/turnout/marks/{ws.v[0]}", headers=ws.agent)
    items = [i for i in client.get(f"{API}/voters/{ws.v[0]}/history", headers=ws.agent).json()["items"]
             if i["kind"] == "voted"]  # the fixture's voter insert is a roll_edit entry
    assert len(items) == 2
    assert items[0]["changes"]["is_voted"] == {"old": True, "new": False}


# --- GET /turnout/summary --------------------------------------------------------------------------
def test_summary_counts_by_booth(client, ws, owner_conn):
    mark(client, ws.supervisor, **by_ids(ws.v[0], ws.v[1], ws.v[2], ws.v[5]))
    client.delete(f"{API}/turnout/marks/{ws.v[2]}", headers=ws.supervisor)  # undone: not counted
    owner_conn.execute("UPDATE app.voters SET deleted_at = now() WHERE id = %s", (ws.v[4],))  # removed: not counted
    s = client.get(f"{API}/turnout/summary", headers=ws.supervisor).json()
    assert (s["total"], s["voted"], s["percent"]) == (6, 3, 50.0)
    assert [(b["booth_id"], b["total"], b["voted"], b["percent"]) for b in s["booths"]] == [
        (str(ws.booths[0]), 4, 2, 50.0), (str(ws.booths[1]), 2, 1, 50.0)]

    one = client.get(f"{API}/turnout/summary", headers=ws.supervisor, params={"booth_id": str(ws.booths[1])}).json()
    assert [b["booth_id"] for b in one["booths"]] == [str(ws.booths[1])] and one["voted"] == 1
    ward = client.get(f"{API}/turnout/summary", headers=ws.supervisor, params={"ward_id": str(ws.ward)}).json()
    assert len(ward["booths"]) == 2

    agent = client.get(f"{API}/turnout/summary", headers=ws.agent).json()  # booth 1 only
    assert [b["booth_id"] for b in agent["booths"]] == [str(ws.booths[0])] and agent["percent"] == 50.0


def test_summary_of_a_booth_where_nobody_voted_is_zero(client, ws):
    client.post(f"{API}/turnout/marks", headers=ws.supervisor, json={"id": str(uuid.uuid4()), **by_ids(ws.v[0])})
    s = client.get(f"{API}/turnout/summary", headers=ws.supervisor, params={"booth_id": str(ws.booths[1])}).json()
    assert s["voted"] == 0 and s["booths"][0]["percent"] == 0.0


# --- push and pull ----------------------------------------------------------------------------
def push(client, headers, ptype, entity, data=None, mid=None):
    it = {"id": str(mid or uuid.uuid4()), "type": ptype, "entity_id": str(entity), "base_version": 0,
          "data": data or {}}
    r = client.post(f"{API}/sync/push", headers=headers, json={"items": [it]})
    assert r.status_code == 200, r.text
    return r.json()["results"][0]


def test_push_voted_returns_the_marks_and_a_retry_applies_once(client, ws, owner_conn):
    rid, mid = uuid.uuid4(), uuid.uuid4()
    data = {"booth_id": str(ws.booths[0]), "serials": "1-2", "source": "bulk_typed"}
    r = push(client, ws.agent, "voted", rid, data, mid)
    assert r["status"] == "applied" and r["duplicate"] is False
    assert [(m["voter_id"], m["is_voted"], m["source"]) for m in r["turnout"]] == [
        (str(ws.v[0]), True, "bulk_typed"), (str(ws.v[1]), True, "bulk_typed")]
    assert row(owner_conn, ws.v[0])[2] == ws.agent_phone

    client.delete(f"{API}/turnout/marks/{ws.v[0]}", headers=ws.agent2)
    again = push(client, ws.agent, "voted", rid, data, mid)  # the same outbox item
    assert again["status"] == "applied" and again["duplicate"] is True
    assert [m["is_voted"] for m in again["turnout"]] == [False, True]  # the marks as they are now
    rebuilt = push(client, ws.agent, "voted", rid, {**data, "id": str(rid)})  # same mark, new outbox id
    assert rebuilt["duplicate"] is False and voted(owner_conn, ws) == {ws.v[1]}


def test_push_unvoted_and_rejections(client, ws, owner_conn):
    push(client, ws.agent, "voted", uuid.uuid4(), by_ids(ws.v[0]))
    r = push(client, ws.agent2, "unvoted", ws.v[0])
    assert r["status"] == "applied" and r["turnout"][0]["is_voted"] is False
    assert push(client, ws.agent, "unvoted", ws.v[1])["turnout"] == []  # never marked

    rejected = [
        push(client, ws.surveyor, "voted", uuid.uuid4(), by_ids(ws.v[0])),
        push(client, ws.surveyor, "unvoted", ws.v[0]),
        push(client, ws.agent, "voted", uuid.uuid4(), by_ids(ws.v[5])),
        push(client, ws.agent, "voted", uuid.uuid4(), {"id": str(uuid.uuid4()), **by_ids(ws.v[1])}),
        push(client, ws.agent, "voted", uuid.uuid4(), {"booth_id": str(ws.booths[0]), "serials": "9-1"}),
    ]
    assert [(x["status"], x["error"]["code"]) for x in rejected] == [
        ("rejected", "forbidden_role"), ("rejected", "forbidden_role"), ("rejected", "not_found"),
        ("rejected", "validation_error"), ("rejected", "validation_error")]
    assert voted(owner_conn, ws) == set()


def pull_all(client, headers, since=None) -> list[dict]:
    pages, cursor = [], None
    while True:
        params = {"cursor": cursor} if cursor else ({"since": since} if since else {})
        r = client.get(f"{API}/sync/pull", headers=headers, params=params)
        assert r.status_code == 200, r.text
        pages.append(r.json())
        cursor = pages[-1]["next_cursor"]
        if not cursor:
            return pages


def marks_in(pages) -> dict[str, bool]:
    return {m["voter_id"]: m["is_voted"] for p in pages for m in p["turnout"]}


def test_pull_sends_marks_to_polling_roles_only(client, ws, owner_conn):
    mark(client, ws.supervisor, **by_ids(ws.v[0], ws.v[1], ws.v[5]))
    client.delete(f"{API}/turnout/marks/{ws.v[1]}", headers=ws.supervisor)

    first = pull_all(client, ws.agent)
    assert marks_in(first) == {str(ws.v[0]): True}  # voted ones of booth 1 only
    assert marks_in(pull_all(client, ws.supervisor)) == {str(ws.v[0]): True, str(ws.v[5]): True}
    assert marks_in(pull_all(client, ws.surveyor)) == {}

    w = first[0]["watermark"]
    client.delete(f"{API}/turnout/marks/{ws.v[0]}", headers=ws.agent2)
    mark(client, ws.agent2, **by_ids(ws.v[2]))
    delta = marks_in(pull_all(client, ws.agent, since=w))
    # the changes come back; an older row may come again (the watermark can sit below it), never another booth's
    assert delta[str(ws.v[0])] is False and delta[str(ws.v[2])] is True
    assert set(delta) <= {str(ws.v[0]), str(ws.v[1]), str(ws.v[2])} and delta.get(str(ws.v[1])) in (None, False)
    assert marks_in(pull_all(client, ws.surveyor, since=w)) == {}
