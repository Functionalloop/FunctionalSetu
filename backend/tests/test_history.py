"""GET /voters/{id}/history (7.6, Information Updation): every change, newest first, with who and what.

Fake data only. Role / login / other-workspace / other-area rules: test_endpoint_rules.py.
"""

from __future__ import annotations

import uuid

import pytest

from conftest import bearer, login, phone

API = "/api/v1"


@pytest.fixture
def ws(make_workspace, owner_conn, client, set_device_status):
    w = make_workspace("hist")
    w.voter = uuid.uuid4()
    with owner_conn.transaction():  # like a roll import, which skips the audit
        owner_conn.execute("SET LOCAL app.skip_audit = 'on'")
        owner_conn.execute("""INSERT INTO app.voters (id, tenant_id, local_body_id, ward_id, booth_id, part_no,
                                  serial_no, gender, first_name_en, house_no)
                              VALUES (%s, %s, %s, %s, %s, 1, 1, 'F', 'Fake', '12')""",
                           (w.voter, w.tenant, w.local_body, w.ward, w.booths[0]))
    w.green, w.green_label = owner_conn.execute(
        "SELECT id, label_en FROM app.color_tags WHERE tenant_id = %s AND code = 'green'", (w.tenant,)).fetchone()

    def phone_user(username):
        t = login(client, w, username, device=phone(f"phone-hist-{username}")).json()
        set_device_status(t["device"]["id"], "approved")
        return bearer(t)

    w.surveyor, w.supervisor = phone_user("survey1"), phone_user("sup1")
    return w


def history(client, ws, headers=None, **params):
    r = client.get(f"{API}/voters/{ws.voter}/history", headers=headers or ws.surveyor, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def save(client, ws, version, **body):
    r = client.put(f"{API}/voters/{ws.voter}/survey", headers=ws.surveyor, json={"version": version, **body})
    assert r.status_code == 200, r.text


def test_survey_save_appears_with_user_time_and_changed_fields(client, ws):
    assert history(client, ws) == {"items": [], "next_cursor": None}
    save(client, ws, 0, mobile_1="9876543210", color_tag_id=str(ws.green), notes="Met at home")
    save(client, ws, 1, mobile_1="9876543210", color_tag_id=str(ws.green), notes="Called again")

    second, first = history(client, ws)["items"]
    assert second["kind"] == first["kind"] == "survey"
    assert (second["action"], first["action"]) == ("update", "insert")
    assert second["at"] > first["at"]
    assert second["by"]["username"] == "survey1" and second["by"]["role"] == "surveyor"
    assert second["changes"] == {"notes": {"old": "Met at home", "new": "Called again"}}  # only what changed

    c = first["changes"]
    assert c["mobile_1"] == {"old": None, "new": "9876543210"}
    assert c["color_tag_id"] == {"old": None, "new": str(ws.green), "new_label": ws.green_label}
    assert c["notes"]["new"] == "Met at home"
    for bookkeeping in ("version", "updated_by", "tenant_id", "voter_id", "sync_xid", "is_surveyed", "is_important"):
        assert bookkeeping not in c
    assert "has_new_address" not in c  # false on a first save = nothing to say


def test_kutumb_visit_voted_roll_edit_and_slip_are_listed(client, ws, owner_conn):
    fid = uuid.uuid4()
    assert client.post(f"{API}/families", headers=ws.surveyor,
                       json={"id": str(fid), "booth_id": str(ws.booths[0]), "label": "Fake Kutumb"}).status_code == 201
    assert client.put(f"{API}/voters/{ws.voter}/family", headers=ws.surveyor,
                      json={"family_id": str(fid)}).status_code == 200
    assert client.post(f"{API}/voters/{ws.voter}/visits", headers=ws.surveyor, json={
        "id": str(uuid.uuid4()), "outcome": "revisit", "visited_at": "2026-11-13T10:00:00Z",
        "revisit_at": "2026-11-14T10:00:00Z", "note": "Come in the evening"}).status_code == 201
    sup = ws.users["sup1"]
    with owner_conn.transaction():  # voted marks and roll edits have no API yet (steps 9 and 11)
        owner_conn.execute("SELECT app.set_context(%s, %s, NULL)", (ws.tenant, sup))
        owner_conn.execute("INSERT INTO app.voter_turnout (voter_id, tenant_id, marked_by) VALUES (%s, %s, %s)",
                           (ws.voter, ws.tenant, sup))
        owner_conn.execute("UPDATE app.voters SET house_no = '12A' WHERE id = %s", (ws.voter,))
        owner_conn.execute("INSERT INTO app.slip_events (tenant_id, voter_id, channel, created_by) "
                           "VALUES (%s, %s, 'whatsapp', %s)", (ws.tenant, ws.voter, sup))

    items = history(client, ws, ws.supervisor)["items"]
    by_kind = {i["kind"]: i for i in items}
    assert sorted(by_kind) == ["family", "roll_edit", "slip", "visit", "voted"]
    assert len(items) == 5

    fam = by_kind["family"]
    assert fam["by"]["username"] == "survey1"
    assert fam["changes"]["family_id"] == {"old": None, "new": str(fid), "new_label": "Fake Kutumb"}
    visit = by_kind["visit"]
    assert visit["at"].startswith("2026-11-13T10:00:00")  # the visit's own time
    assert visit["changes"]["outcome"]["new"] == "revisit"
    assert visit["changes"]["note"]["new"] == "Come in the evening" and visit["changes"]["revisit_at"]["new"]
    assert by_kind["voted"]["changes"]["is_voted"] == {"old": None, "new": True}
    assert "marked_by" not in by_kind["voted"]["changes"] and by_kind["voted"]["by"]["username"] == "sup1"
    assert by_kind["roll_edit"]["changes"] == {"house_no": {"old": "12", "new": "12A"}}
    assert by_kind["slip"]["action"] == "whatsapp" and by_kind["slip"]["changes"] == {}

    # taken out of the Kutumb: old label, new null
    client.put(f"{API}/voters/{ws.voter}/family", headers=ws.surveyor, json={"leave_family": True})
    out = history(client, ws, limit=1)["items"][0]
    assert out["kind"] == "family" and out["action"] == "update"
    assert out["changes"]["family_id"] == {"old": str(fid), "new": None, "old_label": "Fake Kutumb"}


def test_pages_join_up_without_gaps_or_repeats(client, ws, owner_conn):
    save(client, ws, 0, notes="n0")
    for v in range(1, 5):
        save(client, ws, v, notes=f"n{v}")
    sup = ws.users["sup1"]
    with owner_conn.transaction():  # several entries with the same time: the key breaks the tie
        owner_conn.execute("SELECT app.set_context(%s, %s, NULL)", (ws.tenant, sup))
        for ch in ("pdf", "sms", "print"):
            owner_conn.execute("INSERT INTO app.slip_events (tenant_id, voter_id, channel, created_by) "
                               "VALUES (%s, %s, %s, %s)", (ws.tenant, ws.voter, ch, sup))

    whole = history(client, ws)["items"]
    assert len(whole) == 8
    assert [i["at"] for i in whole] == sorted((i["at"] for i in whole), reverse=True)
    paged, cursor = [], None
    while True:
        page = history(client, ws, limit=3, **({"cursor": cursor} if cursor else {}))
        paged += page["items"]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert paged == whole


def test_bad_cursor_is_400(client, ws):
    r = client.get(f"{API}/voters/{ws.voter}/history", headers=ws.surveyor, params={"cursor": "bm9wZQ"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_cursor"


def test_unknown_voter_is_404(client, ws):
    r = client.get(f"{API}/voters/{uuid.uuid4()}/history", headers=ws.surveyor)
    assert r.status_code == 404
