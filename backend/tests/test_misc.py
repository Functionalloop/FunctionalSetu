"""More menu (7.9): terms, announcements, problem reports.

Fake data only. Role / login / other-workspace / other-area rules: test_endpoint_rules.py.
"""

from __future__ import annotations

import uuid

import pytest

from conftest import bearer, login, phone

API = "/api/v1"
TERMS_VERSION = 9001  # global table: a number no real terms text will use; removed after each test


@pytest.fixture
def ws(make_workspace, client, set_device_status):
    w = make_workspace("misc", extra_users={"agent1": "booth_agent"})

    def phone_user(username):
        t = login(client, w, username, device=phone(f"phone-misc-{username}")).json()
        set_device_status(t["device"]["id"], "approved")
        return bearer(t), t

    (w.surveyor, w.surveyor_login), (w.sup, _) = phone_user("survey1"), phone_user("sup1")
    w.boss = bearer(login(client, w, "boss").json())
    return w


@pytest.fixture
def terms(owner_conn):
    owner_conn.execute("INSERT INTO app.terms_versions (version, body_mr, body_en) VALUES (%s, 'अटी', 'Fake terms')",
                       (TERMS_VERSION,))
    yield TERMS_VERSION
    owner_conn.execute("UPDATE app.users SET terms_version = NULL WHERE terms_version = %s", (TERMS_VERSION,))
    owner_conn.execute("DELETE FROM app.terms_versions WHERE version = %s", (TERMS_VERSION,))


# --- terms -------------------------------------------------------------------------------------
def test_no_terms_yet_is_404_for_reading_and_accepting(client, ws):
    r = client.get(f"{API}/terms/current")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert client.post(f"{API}/terms/accept", headers=ws.surveyor, json={"version": 1}).status_code == 404


def test_terms_read_without_login_and_accepted(client, ws, terms):
    t = client.get(f"{API}/terms/current").json()
    assert (t["version"], t["body_en"]) == (terms, "Fake terms")
    assert client.get(f"{API}/me", headers=ws.surveyor).json()["user"]["terms_version"] is None

    stale = client.post(f"{API}/terms/accept", headers=ws.surveyor, json={"version": terms - 1})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "terms_changed"
    assert client.post(f"{API}/terms/accept", headers=ws.surveyor, json={"version": terms}).status_code == 204
    assert client.get(f"{API}/me", headers=ws.surveyor).json()["user"]["terms_version"] == terms


def test_terms_accepted_while_the_phone_waits(client, ws, terms):
    t = login(client, ws, "agent1", device=phone("phone-misc-waiting")).json()  # phone not approved
    assert client.post(f"{API}/terms/accept", headers=bearer(t), json={"version": terms}).status_code == 204


# --- announcements ------------------------------------------------------------------------------
def _announce(owner_conn, ws, body, area=None, expires="NULL", deleted="NULL"):
    aid = uuid.uuid4()
    owner_conn.execute(f"""INSERT INTO app.announcements (id, tenant_id, body, audience_geo_id, created_by,
                                   expires_at, deleted_at)
                           VALUES (%s, %s, %s, %s, %s, {expires}, {deleted})""",
                       (aid, ws.tenant, body, area, ws.users["boss"]))
    return aid


def _bodies(client, headers, **params):
    r = client.get(f"{API}/announcements", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return [a["body"] for a in r.json()["items"]], r.json()


def test_who_sees_which_announcement(client, ws, owner_conn):
    _announce(owner_conn, ws, "all")
    _announce(owner_conn, ws, "ward", ws.ward)
    _announce(owner_conn, ws, "booth 1", ws.booths[0])
    _announce(owner_conn, ws, "booth 2", ws.booths[1])
    _announce(owner_conn, ws, "expired", expires="now() - interval '1 day'")
    _announce(owner_conn, ws, "deleted", deleted="now()")

    surveyor, _ = _bodies(client, ws.surveyor)  # booth 1 only
    assert sorted(surveyor) == ["all", "booth 1", "ward"]  # the ward's notice reaches its booths
    supervisor, _ = _bodies(client, ws.sup)  # the whole ward
    assert sorted(supervisor) == ["all", "booth 1", "booth 2", "ward"]
    boss, page = _bodies(client, ws.boss)
    assert sorted(boss) == ["all", "booth 1", "booth 2", "ward"]
    assert page["items"][0]["created_by"]["username"] == "boss"


def test_read_flag_and_paging_newest_first(client, ws, owner_conn):
    ids = [_announce(owner_conn, ws, f"n{i}") for i in range(5)]
    whole, _ = _bodies(client, ws.surveyor)
    assert whole == ["n4", "n3", "n2", "n1", "n0"]
    paged, cursor = [], None
    while True:
        bodies, page = _bodies(client, ws.surveyor, limit=2, **({"cursor": cursor} if cursor else {}))
        paged += bodies
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert paged == whole

    for _ in range(2):  # reading again is fine
        assert client.post(f"{API}/announcements/{ids[0]}/read", headers=ws.surveyor).status_code == 204
    flags = {a["body"]: a["is_read"] for a in client.get(f"{API}/announcements", headers=ws.surveyor).json()["items"]}
    assert flags == {"n4": False, "n3": False, "n2": False, "n1": False, "n0": True}
    other = {a["body"]: a["is_read"] for a in client.get(f"{API}/announcements", headers=ws.sup).json()["items"]}
    assert other["n0"] is False  # read flags are per user


def test_expired_announcement_cannot_be_marked_read(client, ws, owner_conn):
    old = _announce(owner_conn, ws, "expired", expires="now() - interval '1 day'")
    assert client.post(f"{API}/announcements/{old}/read", headers=ws.surveyor).status_code == 404


# --- problem reports ----------------------------------------------------------------------------
def test_problem_report_keeps_who_phone_and_version(client, ws, owner_conn):
    r = client.post(f"{API}/problem-reports", headers=ws.surveyor,
                    json={"body": "  Search is slow  ", "app_version_code": 3, "phone_model": "Fake Phone"})
    assert r.status_code == 204, r.text
    row = owner_conn.execute("SELECT user_id, device_id, body, app_version_code, phone_model, status "
                             "FROM app.problem_reports WHERE tenant_id = %s", (ws.tenant,)).fetchone()
    assert row == (ws.users["survey1"], uuid.UUID(ws.surveyor_login["device"]["id"]), "Search is slow", 3,
                   "Fake Phone", "open")
    blank = client.post(f"{API}/problem-reports", headers=ws.surveyor, json={"body": "   "})
    assert blank.status_code == 422
