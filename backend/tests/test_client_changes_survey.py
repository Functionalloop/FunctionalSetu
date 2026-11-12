"""Client changes of 12 Nov (task 5.14): new survey fields, the two new lists, no white colour tag,
the Important voters filter, part notes table and polling time. Fake data only."""

from __future__ import annotations

import uuid

import pytest

from conftest import bearer, login, phone

API = "/api/v1"


@pytest.fixture
def ws(make_workspace, owner_conn):
    w = make_workspace("cc")
    w.voters = []
    for serial in (1, 2, 3):
        vid = uuid.uuid4()
        owner_conn.execute(
            """INSERT INTO app.voters (id, tenant_id, local_body_id, ward_id, booth_id, part_no, serial_no,
                                       first_name_en, last_name_en, gender, age)
               VALUES (%s, %s, %s, %s, %s, 1, %s, 'Asha', 'Patil', 'F', 40)""",
            (vid, w.tenant, w.local_body, w.ward, w.booths[0], serial))
        w.voters.append(vid)

    def first(table: str) -> uuid.UUID:
        return owner_conn.execute(f"SELECT id FROM app.{table} WHERE tenant_id = %s ORDER BY sort_order LIMIT 1",
                                  (w.tenant,)).fetchone()[0]

    w.position, w.influencer_type = first("positions"), first("influencer_types")
    return w


@pytest.fixture
def surveyor(client, ws, set_device_status):
    t = login(client, ws, "survey1", device=phone("phone-cc-0001")).json()
    set_device_status(t["device"]["id"], "approved")
    return bearer(t)


def save(client, ws, headers, voter=0, **body):
    return client.put(f"{API}/voters/{ws.voters[voter]}/survey", headers=headers, json={"version": 0, **body})


# --- lists and colour tags ------------------------------------------------------------
def test_new_workspace_has_no_white_tag_and_has_placeholder_lists(ws, owner_conn):
    codes = [r[0] for r in owner_conn.execute(
        "SELECT code FROM app.color_tags WHERE tenant_id = %s ORDER BY sort_order", (ws.tenant,))]
    assert codes == ["green", "red", "yellow"]
    for table in ("positions", "influencer_types"):
        n = owner_conn.execute(f"SELECT count(*) FROM app.{table} WHERE tenant_id = %s AND is_active",
                               (ws.tenant,)).fetchone()[0]
        assert n >= 5, table


def test_white_tag_of_an_old_workspace_is_switched_off(ws, owner_conn, client, surveyor):
    # A workspace made before 002 still has the white row; 002 switched it off. Saving it is refused.
    white = owner_conn.execute(
        """INSERT INTO app.color_tags (tenant_id, code, hex, label_mr, label_en, is_active)
           VALUES (%s, 'white', '#FFFFFF', 'इतर', 'Other', false) RETURNING id""", (ws.tenant,)).fetchone()[0]
    r = save(client, ws, surveyor, color_tag_id=str(white))
    assert r.status_code == 422 and "color_tag_id" in r.json()["error"]["message"]


def test_pull_sends_the_two_new_lists(client, ws, surveyor):
    lists = client.get(f"{API}/sync/pull", headers=surveyor).json()["lists"]
    assert str(ws.position) in [e["id"] for e in lists["positions"]]
    assert str(ws.influencer_type) in [e["id"] for e in lists["influencer_types"]]
    assert "white" not in [t["code"] for t in lists["color_tags"]]


# --- survey fields --------------------------------------------------------------------
def test_new_fields_round_trip(client, ws, surveyor):
    body = {"is_important": True, "position_id": str(ws.position), "is_influencer": True,
            "influencer_type_id": str(ws.influencer_type), "in_self_help_group": True,
            "self_help_group_name": "Fake Mahila Gat", "ration_card": "PHH"}
    r = save(client, ws, surveyor, **body)
    assert r.status_code == 200, r.text
    assert {k: r.json()[k] for k in body} == body
    detail = client.get(f"{API}/voters/{ws.voters[0]}", headers=surveyor).json()["survey"]
    assert {k: detail[k] for k in body} == body

    # PUT replaces everything: leaving the fields out clears them.
    r = client.put(f"{API}/voters/{ws.voters[0]}/survey", headers=surveyor, json={"version": 1})
    s = r.json()
    assert s["is_important"] is False and s["position_id"] is None and s["ration_card"] is None
    assert s["in_self_help_group"] is False and s["self_help_group_name"] is None


@pytest.mark.parametrize("body", [
    {"position_id": "POS"},                                   # position without "important"
    {"influencer_type_id": "INF"},                            # type without "influencer"
    {"self_help_group_name": "Fake Gat"},                     # group name without "self help group"
    {"ration_card": "APL"},                                   # only AAY, PHH, NPHH
    {"ration_card": "phh"},
    {"in_self_help_group": True, "self_help_group_name": "x" * 201},
])
def test_bad_new_fields_are_422(client, ws, surveyor, body):
    body = {k: (str(ws.position) if v == "POS" else str(ws.influencer_type) if v == "INF" else v)
            for k, v in body.items()}
    r = save(client, ws, surveyor, **body)
    assert r.status_code == 422, r.text


def test_list_entry_of_another_workspace_or_inactive_is_422(client, ws, surveyor, make_workspace, owner_conn):
    other = make_workspace("cc-other")
    foreign = owner_conn.execute("SELECT id FROM app.positions WHERE tenant_id = %s LIMIT 1",
                                 (other.tenant,)).fetchone()[0]
    assert save(client, ws, surveyor, is_important=True, position_id=str(foreign)).status_code == 422
    owner_conn.execute("UPDATE app.influencer_types SET is_active = false WHERE id = %s", (ws.influencer_type,))
    r = save(client, ws, surveyor, is_influencer=True, influencer_type_id=str(ws.influencer_type))
    assert r.status_code == 422


def test_push_takes_the_new_fields(client, ws, surveyor):
    item = {"id": str(uuid.uuid4()), "type": "survey", "entity_id": str(ws.voters[1]), "base_version": 0,
            "data": {"is_important": True, "position_id": str(ws.position), "ration_card": "AAY"}}
    res = client.post(f"{API}/sync/push", headers=surveyor, json={"items": [item]}).json()["results"][0]
    assert res["status"] == "applied", res
    assert res["survey"]["position_id"] == str(ws.position) and res["survey"]["ration_card"] == "AAY"

    bad = {**item, "id": str(uuid.uuid4()), "entity_id": str(ws.voters[2]), "data": {"position_id": str(ws.position)}}
    res = client.post(f"{API}/sync/push", headers=surveyor, json={"items": [bad]}).json()["results"][0]
    assert res["status"] == "rejected" and res["error"]["code"] == "validation_error"


def test_database_refuses_a_position_without_important(ws, owner_conn):
    # The API checks it first; the database keeps it true for imports and scripts too.
    with pytest.raises(Exception, match="check"):
        owner_conn.execute(
            "INSERT INTO app.voter_surveys (tenant_id, voter_id, position_id) VALUES (%s, %s, %s)",
            (ws.tenant, ws.voters[0], ws.position))


# --- Important voters filter ------------------------------------------------------------
def test_important_filter(client, ws, surveyor):
    assert save(client, ws, surveyor, voter=0, is_important=True).status_code == 200
    assert save(client, ws, surveyor, voter=1, is_important=False).status_code == 200

    def found(**params):
        r = client.get(f"{API}/voters", headers=surveyor, params=params)
        assert r.status_code == 200, r.text
        return [uuid.UUID(v["id"]) for v in r.json()["items"]]

    assert found(important="true") == [ws.voters[0]]
    assert found(important="false") == [ws.voters[1], ws.voters[2]]  # voter 3 has no survey at all
    assert len(found()) == 3


# --- part notes and polling time (tables only; their API is tasks 7.11 and 9.4) -------------
def test_part_note_table_versions_and_isolation(ws, owner_conn, app_conn, make_workspace):
    note_id = owner_conn.execute(
        "INSERT INTO app.part_notes (tenant_id, booth_id, note) VALUES (%s, %s, 'Meeting at the temple') "
        "RETURNING id", (ws.tenant, ws.booths[0])).fetchone()[0]
    owner_conn.execute("UPDATE app.part_notes SET note = 'Meeting moved' WHERE id = %s", (note_id,))
    assert owner_conn.execute("SELECT version FROM app.part_notes WHERE id = %s", (note_id,)).fetchone()[0] == 2
    with pytest.raises(Exception):  # one note per part
        owner_conn.execute("INSERT INTO app.part_notes (tenant_id, booth_id) VALUES (%s, %s)",
                           (ws.tenant, ws.booths[0]))

    other = make_workspace("cc-rls")
    app_conn.execute("SELECT app.set_context(%s, %s, NULL)", (other.tenant, other.users["boss"]))
    assert app_conn.execute("SELECT count(*) FROM app.part_notes").fetchone()[0] == 0  # RLS
    app_conn.rollback()


def test_polling_time_in_settings(client, ws, owner_conn):
    owner_conn.execute("UPDATE app.tenant_settings SET polling_start_time = '07:00', polling_end_time = '18:00' "
                       "WHERE tenant_id = %s", (ws.tenant,))
    me = client.get(f"{API}/me", headers=bearer(login(client, ws, "admin1").json())).json()
    assert me["settings"]["polling_start_time"] == "07:00:00" and me["settings"]["polling_end_time"] == "18:00:00"
    with pytest.raises(Exception):  # end before start
        owner_conn.execute("UPDATE app.tenant_settings SET polling_end_time = '06:00' WHERE tenant_id = %s",
                           (ws.tenant,))
