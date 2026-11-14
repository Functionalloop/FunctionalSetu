"""Team and logs (9.5): announcements, problem reports, activity log, worker activity, worker locations.
An admin sees their own constituency's team; a super admin the workspace. Generic rules: test_endpoint_rules.py."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from conftest import bearer, login, phone

API = "/api/v1"
IST = ZoneInfo("Asia/Kolkata")


def code(resp) -> str:
    return resp.json()["error"]["code"]


@pytest.fixture
def ws(make_workspace):
    return make_workspace(extra_users={"agent1": "booth_agent"})


@pytest.fixture
def admin(client, ws):
    return bearer(login(client, ws, "admin1").json())


@pytest.fixture
def boss(client, ws):
    return bearer(login(client, ws, "boss").json())


@pytest.fixture
def worker(client, ws, set_device_status):
    """Approved phone headers for a user of the workspace."""
    def make(username: str) -> dict:
        t = login(client, ws, username, device=phone(f"logs-{username}")).json()
        set_device_status(t["device"]["id"], "approved")
        return bearer(t)
    return make


@pytest.fixture
def far(owner_conn, ws):
    """A second constituency with its own surveyor (outside admin1's team)."""
    lb, ward, booth, uid = (uuid.uuid4() for _ in range(4))
    geo = """INSERT INTO app.geo_units (id, tenant_id, parent_id, level, code, number, name_mr)
             VALUES (%s, %s, %s, %s, %s, %s, 'X')"""
    owner_conn.execute(geo, (lb, ws.tenant, None, "local_body", "2", None))
    owner_conn.execute(geo, (ward, ws.tenant, lb, "ward", "1", 1))
    owner_conn.execute(geo, (booth, ws.tenant, ward, "booth", "2001", 1))
    owner_conn.execute("""INSERT INTO app.users (id, tenant_id, username, full_name_en, role, local_body_id,
                                                 password_hash) VALUES (%s, %s, 'far1', 'Far', 'surveyor', %s, 'x')""",
                       (uid, ws.tenant, lb))
    return {"lb": lb, "booth": booth, "user": uid}


def voter(owner_conn, ws, booth=None, lb=None, ward=None) -> uuid.UUID:
    return owner_conn.execute(
        """INSERT INTO app.voters (tenant_id, local_body_id, ward_id, booth_id, part_no, serial_no, gender,
                                   first_name_en) VALUES (%s, %s, %s, %s, 1, %s, 'F', 'A') RETURNING id""",
        (ws.tenant, lb or ws.local_body, ward or ws.ward, booth or ws.booths[0],
         uuid.uuid4().int % 100000)).fetchone()[0]


def today() -> str:
    return datetime.now(IST).date().isoformat()


def span() -> dict:
    d = datetime.now(IST).date()
    return {"date_from": (d - timedelta(days=1)).isoformat(), "date_to": (d + timedelta(days=1)).isoformat()}


# --- announcements -----------------------------------------------------------------------------
def test_announcement_reaches_its_area_only(client, ws, admin, worker, owner_conn):
    owner_conn.execute("INSERT INTO app.user_area_assignments (tenant_id, user_id, geo_unit_id) VALUES (%s, %s, %s)",
                       (ws.tenant, ws.users["agent1"], ws.booths[1]))
    s1, a1 = worker("survey1"), worker("agent1")
    r = client.post(f"{API}/announcements", headers=admin,
                    json={"body": " Meeting at 5 ", "audience_geo_id": str(ws.booths[0])})
    assert r.status_code == 201, r.text
    a = r.json()
    assert (a["body"], a["created_by"]["username"], a["is_read"]) == ("Meeting at 5", "admin1", False)

    def seen(h):
        return [x["id"] for x in client.get(f"{API}/announcements", headers=h).json()["items"]]
    assert a["id"] in seen(s1) and a["id"] not in seen(a1)

    assert client.delete(f"{API}/announcements/{a['id']}", headers=admin).status_code == 204
    assert a["id"] not in seen(s1)
    assert client.delete(f"{API}/announcements/{a['id']}", headers=admin).status_code == 404


def test_an_admins_everyone_is_their_constituency(client, ws, admin, boss, far):
    r = client.post(f"{API}/announcements", headers=admin, json={"body": "All of you"})
    assert r.status_code == 201 and r.json()["audience_geo_id"] == str(ws.local_body)
    r = client.post(f"{API}/announcements", headers=boss, json={"body": "Whole workspace"})
    assert r.status_code == 201 and r.json()["audience_geo_id"] is None
    # the super admin's notice for everyone is not the admin's to remove
    assert client.delete(f"{API}/announcements/{r.json()['id']}", headers=admin).status_code == 404
    assert client.delete(f"{API}/announcements/{r.json()['id']}", headers=boss).status_code == 204

    r = client.post(f"{API}/announcements", headers=admin, json={"body": "x", "audience_geo_id": str(far["booth"])})
    assert r.status_code == 404
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    r = client.post(f"{API}/announcements", headers=admin, json={"body": "x", "expires_at": past})
    assert r.status_code == 422


# --- problem reports ---------------------------------------------------------------------------
def test_problem_reports_of_the_admins_team(client, ws, admin, boss, worker, far, owner_conn):
    s1 = worker("survey1")
    for i in range(3):
        assert client.post(f"{API}/problem-reports", headers=s1,
                           json={"body": f"Problem {i}", "app_version_code": 2, "phone_model": "M35"}).status_code == 204
    owner_conn.execute("INSERT INTO app.problem_reports (tenant_id, user_id, body) VALUES (%s, %s, 'far')",
                       (ws.tenant, far["user"]))
    seen, cursor = [], None
    while True:
        r = client.get(f"{API}/problem-reports", headers=admin, params={"limit": 2, **({"cursor": cursor} if cursor else {})})
        assert r.status_code == 200, r.text
        seen += r.json()["items"]
        cursor = r.json()["next_cursor"]
        if not cursor:
            break
    assert [p["body"] for p in seen] == ["Problem 2", "Problem 1", "Problem 0"]  # newest first; not far1's
    assert seen[0]["user"]["username"] == "survey1" and seen[0]["phone_model"] == "M35"
    assert len(client.get(f"{API}/problem-reports", headers=boss).json()["items"]) == 4
    assert client.get(f"{API}/problem-reports", headers=admin, params={"status": "done"}).json()["items"] == []


# --- activity log ------------------------------------------------------------------------------
def test_activity_log_shows_who_changed_what_and_never_password_hashes(client, ws, admin, worker, owner_conn):
    vid = voter(owner_conn, ws)
    s1 = worker("survey1")
    assert client.put(f"{API}/voters/{vid}/survey", headers=s1, json={"version": 0, "notes": "hello"}).status_code == 200
    made = client.post(f"{API}/users", headers=admin, json={"username": "logged1", "full_name_en": "Logged",
                                                            "role": "surveyor"}).json()["user"]
    client.post(f"{API}/users/{made['id']}/reset-password", headers=admin)

    r = client.get(f"{API}/audit-log", headers=admin, params={"entity_type": "voter_surveys", "entity_id": str(vid)})
    assert r.status_code == 200, r.text
    [e] = r.json()["items"]
    assert (e["action"], e["actor"]["username"], e["new_values"]["notes"]) == ("insert", "survey1", "hello")

    entries = client.get(f"{API}/audit-log", headers=admin, params={"entity_type": "users",
                                                                     "entity_id": made["id"]}).json()["items"]
    assert [x["action"] for x in entries] == ["update", "insert"]
    for x in entries:
        for values in (x["old_values"] or {}, x["new_values"] or {}):
            assert "password_hash" not in values

    mine = client.get(f"{API}/audit-log", headers=admin,
                      params={"actor_user_id": str(ws.users["survey1"]), "date_from": today(), "date_to": today()})
    assert {x["actor"]["username"] for x in mine.json()["items"]} == {"survey1"}


def test_activity_log_isolation_and_paging(client, ws, admin, boss, far, owner_conn, worker):
    # a change by a user of another constituency: the super admin sees it, the admin does not
    fv = voter(owner_conn, ws, booth=far["booth"], lb=far["lb"],
               ward=owner_conn.execute("SELECT parent_id FROM app.geo_units WHERE id = %s",
                                       (far["booth"],)).fetchone()[0])
    owner_conn.execute("UPDATE app.users SET password_hash = %s, must_change_password = false WHERE id = %s",
                       (owner_conn.execute("SELECT password_hash FROM app.users WHERE id = %s",
                                           (ws.users["sup1"],)).fetchone()[0], far["user"]))
    owner_conn.execute("INSERT INTO app.user_area_assignments (tenant_id, user_id, geo_unit_id) VALUES (%s, %s, %s)",
                       (ws.tenant, far["user"], far["booth"]))
    fh = worker("far1")
    assert client.put(f"{API}/voters/{fv}/survey", headers=fh, json={"version": 0}).status_code == 200
    q = {"entity_type": "voter_surveys", "entity_id": str(fv)}
    assert client.get(f"{API}/audit-log", headers=admin, params=q).json()["items"] == []
    assert len(client.get(f"{API}/audit-log", headers=boss, params=q).json()["items"]) == 1
    assert client.get(f"{API}/audit-log", headers=admin, params={"actor_user_id": str(far["user"])}).status_code == 404

    ids, cursor = [], None
    for _ in range(3):
        r = client.get(f"{API}/audit-log", headers=boss, params={"limit": 3, **({"cursor": cursor} if cursor else {})})
        ids += [x["id"] for x in r.json()["items"]]
        cursor = r.json()["next_cursor"]
    assert ids == sorted(set(ids), reverse=True) and len(ids) == 9


# --- worker activity and locations ---------------------------------------------------------------
def test_worker_activity_per_day(client, ws, admin, worker, owner_conn):
    v1, v2 = voter(owner_conn, ws), voter(owner_conn, ws)
    s1, a1 = worker("survey1"), worker("sup1")
    client.put(f"{API}/voters/{v1}/survey", headers=s1, json={"version": 0, "mobile_1": "9876500011"})
    client.put(f"{API}/voters/{v1}/survey", headers=s1, json={"version": 1, "mobile_1": "9876500011", "notes": "x"})
    client.put(f"{API}/voters/{v2}/survey", headers=s1, json={"version": 0})
    now = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert client.post(f"{API}/voters/{v2}/visits", headers=s1,
                       json={"id": str(uuid.uuid4()), "outcome": "met", "visited_at": now.isoformat()}).status_code == 201
    assert client.post(f"{API}/turnout/marks", headers=a1, json={"id": str(uuid.uuid4()),
                                                                  "voter_ids": [str(v1)]}).status_code == 200

    r = client.get(f"{API}/reports/worker-activity", headers=admin, params=span())
    assert r.status_code == 200, r.text
    rows = {x["user"]["username"]: x for x in r.json()["rows"]}
    assert set(rows) == {"survey1", "sup1"}
    s = rows["survey1"]
    assert (s["day"], s["surveys"], s["mobiles_collected"], s["visits"], s["voted_marks"]) == (today(), 2, 1, 1, 0)
    assert rows["sup1"]["voted_marks"] == 1

    one = client.get(f"{API}/reports/worker-activity", headers=admin,
                     params={**span(), "user_id": str(ws.users["sup1"])}).json()["rows"]
    assert [x["user"]["username"] for x in one] == ["sup1"]


def test_worker_activity_and_locations_refuse_bad_ranges_and_outsiders(client, ws, admin, far):
    for path in ("/reports/worker-activity", "/worker-locations"):
        r = client.get(f"{API}{path}", headers=admin, params={"date_from": "2026-11-10", "date_to": "2026-11-01"})
        assert r.status_code == 422
        r = client.get(f"{API}{path}", headers=admin, params={"date_from": "2026-01-01", "date_to": "2026-12-31"})
        assert r.status_code == 422
        r = client.get(f"{API}{path}", headers=admin, params={**span(), "user_id": str(far["user"])})
        assert r.status_code == 404


def test_worker_locations(client, ws, admin, worker, owner_conn):
    v1, v2, v3 = voter(owner_conn, ws), voter(owner_conn, ws), voter(owner_conn, ws)
    s1 = worker("survey1")
    client.put(f"{API}/voters/{v1}/survey", headers=s1,
               json={"version": 0, "location": {"lat": 15.7, "lng": 73.8, "accuracy_m": 12}})
    client.put(f"{API}/voters/{v2}/survey", headers=s1, json={"version": 0})  # no location: not listed
    at = datetime.now(timezone.utc) - timedelta(minutes=1)
    client.post(f"{API}/voters/{v3}/visits", headers=s1, json={"id": str(uuid.uuid4()), "outcome": "not_home",
                                                               "visited_at": at.isoformat(),
                                                               "location": {"lat": 15.71, "lng": 73.81}})
    items, cursor = [], None
    while True:
        r = client.get(f"{API}/worker-locations", headers=admin,
                       params={**span(), "limit": 1, **({"cursor": cursor} if cursor else {})})
        assert r.status_code == 200, r.text
        items += r.json()["items"]
        cursor = r.json()["next_cursor"]
        if not cursor:
            break
    assert sorted((x["kind"], x["voter_id"]) for x in items) == sorted([("survey", str(v1)), ("visit", str(v3))])
    survey = next(x for x in items if x["kind"] == "survey")
    assert (survey["lat"], survey["lng"], survey["accuracy_m"], survey["user"]["username"]) == (15.7, 73.8, 12, "survey1")
    assert items[0]["at"] >= items[1]["at"]
