"""One-voter corrections (10.4): POST /voters, PATCH /voters/{id}/roll, .../remove, .../restore,
GET /voters/{id}/roll-edits (app/routers/roll_edits.py). Fake voters only.
Generic rules (401, 403 per role, other workspace): test_endpoint_rules.py."""

from __future__ import annotations

import uuid

import pytest

from conftest import bearer, login
from test_sync_pull import download

API = "/api/v1"


@pytest.fixture
def ws(make_workspace, owner_conn):
    ws = make_workspace("edits")
    ws.voters = {}
    for serial, epic, first in ((1, "EDT1000001", "Asha"), (2, "EDT1000002", "Ravi"), (3, None, "Meena")):
        ws.voters[serial] = owner_conn.execute(
            """INSERT INTO app.voters (tenant_id, local_body_id, ward_id, booth_id, part_no, booth_no, serial_no,
                                       epic_no, first_name_en, last_name_en, gender, age, house_no)
               VALUES (%s, %s, %s, %s, 1, 1, %s, %s, %s, 'Testkar', 'F', 40, 'H-1') RETURNING id""",
            (ws.tenant, ws.local_body, ws.ward, ws.booths[0], serial, epic, first)).fetchone()[0]
    return ws


@pytest.fixture
def boss(client, ws):
    return bearer(login(client, ws, "boss").json())


@pytest.fixture
def admin(client, ws):
    return bearer(login(client, ws, "admin1").json())


def code(resp) -> str:
    return resp.json()["error"]["code"]


def edits(owner_conn, voter_id) -> list[tuple]:
    return owner_conn.execute("""SELECT action::text, reason, reference, old_values, new_values
                                   FROM app.voter_roll_edits WHERE voter_id = %s ORDER BY id""",
                              (voter_id,)).fetchall()


def search(client, h, q: str, **params) -> list[str]:
    r = client.get(f"{API}/voters", headers=h, params={"q": q, **params})
    assert r.status_code == 200, r.text
    return [v["id"] for v in r.json()["items"]]


def remove(client, h, vid, reason="duplicate", reference=None):
    return client.post(f"{API}/voters/{vid}/remove", headers=h, json={"reason": reason, "reference": reference})


def restore(client, h, vid, reason="other"):
    return client.post(f"{API}/voters/{vid}/restore", headers=h, json={"reason": reason})


def correct(client, h, vid, fields: dict, reason="typing_mistake", reference=None):
    return client.patch(f"{API}/voters/{vid}/roll", headers=h,
                        json={"fields": fields, "reason": reason, "reference": reference})


def new_voter(ws, **over) -> dict:
    return {"booth_id": str(ws.booths[1]), "serial_no": 7, "gender": "M", "first_name_en": "  Kiran ",
            "last_name_en": "Naik", "age": 30, "reason": "supplementary_list", "reference": " List 2 ", **over}


# --- the plan's test ---------------------------------------------------------------------------------
def test_removed_voter_is_hidden_and_comes_back_with_restore(client, ws, boss, owner_conn):
    vid = ws.voters[1]
    owner_conn.execute("INSERT INTO app.voter_surveys (voter_id, tenant_id, notes) VALUES (%s, %s, 'kept')",
                       (vid, ws.tenant))
    assert search(client, boss, "asha") == [str(vid)]

    r = remove(client, boss, vid, reference="Form 7 no. 12")
    assert r.status_code == 200, r.text
    assert r.json()["deleted_at"] is not None and r.json()["survey"]["notes"] == "kept"
    assert search(client, boss, "asha") == []
    assert client.get(f"{API}/voters/{vid}", headers=boss).status_code == 404
    assert search(client, boss, "asha", removed=True) == [str(vid)]

    r = restore(client, boss, vid)
    assert r.status_code == 200, r.text
    assert r.json()["deleted_at"] is None and r.json()["survey"]["notes"] == "kept"
    assert search(client, boss, "asha") == [str(vid)]
    assert search(client, boss, "asha", removed=True) == []
    rows = edits(owner_conn, vid)
    assert [(a, why, ref) for a, why, ref, _, _ in rows] == [("remove", "duplicate", "Form 7 no. 12"),
                                                             ("restore", "other", None)]
    assert rows[0][3] == {"deleted_at": None} and rows[1][4] == {"deleted_at": None}


def test_an_admin_cannot_change_the_roll_but_can_read_the_edits(client, ws, boss, admin, owner_conn):
    vid = ws.voters[2]
    before = owner_conn.execute("SELECT house_no, deleted_at FROM app.voters WHERE id = %s", (vid,)).fetchone()
    for r in (correct(client, admin, vid, {"house_no": "H-9"}), remove(client, admin, vid),
              restore(client, admin, vid),
              client.post(f"{API}/voters", headers=admin, json=new_voter(ws))):
        assert r.status_code == 403 and code(r) == "forbidden_role"
    assert owner_conn.execute("SELECT house_no, deleted_at FROM app.voters WHERE id = %s", (vid,)).fetchone() == before
    assert edits(owner_conn, vid) == []

    assert correct(client, boss, vid, {"house_no": "H-9"}).status_code == 200
    r = client.get(f"{API}/voters/{vid}/roll-edits", headers=admin)
    assert r.status_code == 200
    [e] = r.json()["items"]
    assert e["action"] == "correct" and e["reason"] == "typing_mistake"
    assert e["old_values"] == {"house_no": "H-1"} and e["new_values"] == {"house_no": "H-9"}
    assert e["edited_by"]["username"] == "boss"


# --- add ------------------------------------------------------------------------------------------------
def test_add_takes_the_place_from_the_booth(client, ws, boss, owner_conn):
    r = client.post(f"{API}/voters", headers=boss, json=new_voter(ws))
    assert r.status_code == 201, r.text
    v = r.json()
    assert (v["booth_id"], v["ward_id"], v["local_body_id"]) == (str(ws.booths[1]), str(ws.ward), str(ws.local_body))
    assert (v["part_no"], v["booth_no"], v["serial_no"], v["roll_status"]) == (1, 2, 7, "active")
    assert v["first_name_en"] == "Kiran" and v["list_type"] == "main" and v["survey"] is None
    [(action, reason, ref, old, new)] = edits(owner_conn, uuid.UUID(v["id"]))
    assert (action, reason, ref, old) == ("add", "supplementary_list", "List 2", None)
    assert new["first_name_en"] == "Kiran" and new["part_no"] == 1
    hist = client.get(f"{API}/voters/{v['id']}/history", headers=boss).json()["items"]
    assert [h["kind"] for h in hist] == ["roll_edit"]


@pytest.mark.parametrize("over, status, err", [
    ({"serial_no": 1, "booth_id": "B0"}, 409, "serial_in_use"),
    ({"epic_no": "EDT1000002"}, 409, "epic_in_use"),
    ({"booth_id": "WARD"}, 422, "validation_error"),
    ({"booth_id": str(uuid.uuid4())}, 404, "not_found"),
    ({"first_name_en": " ", "last_name_en": None}, 422, "validation_error"),
    ({"reason": None}, 422, "validation_error"),
    ({"age": 12}, 422, "validation_error"),
])
def test_add_refuses(client, ws, boss, owner_conn, over, status, err):
    over = {k: {"B0": str(ws.booths[0]), "WARD": str(ws.ward)}.get(v, v) if isinstance(v, str) else v
            for k, v in over.items()}
    r = client.post(f"{API}/voters", headers=boss, json=new_voter(ws, **over))
    assert r.status_code == status and code(r) == err, r.text
    if err in ("serial_in_use", "epic_in_use"):
        assert r.json()["error"]["voter_id"] in {str(ws.voters[1]), str(ws.voters[2])}
    assert owner_conn.execute("SELECT count(*) FROM app.voters WHERE tenant_id = %s", (ws.tenant,)).fetchone()[0] == 3


def test_add_in_another_workspace_booth_is_404(client, ws, boss, make_workspace):
    other = make_workspace("edits-b")
    r = client.post(f"{API}/voters", headers=boss, json=new_voter(ws, booth_id=str(other.booths[0])))
    assert r.status_code == 404


# --- correct --------------------------------------------------------------------------------------------
def test_correct_changes_only_the_fields_sent(client, ws, boss, owner_conn):
    vid = ws.voters[3]
    r = correct(client, boss, vid, {"first_name_en": "Meenakshi ", "age": 41, "house_no": "H-1"},
                reference="12 Nov list")
    assert r.status_code == 200, r.text
    v = r.json()
    assert (v["first_name_en"], v["age"], v["house_no"], v["last_name_en"]) == ("Meenakshi", 41, "H-1", "Testkar")
    [(_, _, ref, old, new)] = edits(owner_conn, vid)
    assert ref == "12 Nov list"
    assert old == {"first_name_en": "Meena", "age": 40} and new == {"first_name_en": "Meenakshi", "age": 41}

    again = correct(client, boss, vid, {"first_name_en": "Meenakshi", "age": 41})
    assert again.status_code == 200 and len(edits(owner_conn, vid)) == 1   # nothing changed: no edit


def test_correct_moves_the_voter_to_another_part(client, ws, boss):
    r = correct(client, boss, ws.voters[1], {"booth_id": str(ws.booths[1]), "serial_no": 1}, reason="booth_changed")
    assert r.status_code == 200, r.text
    assert (r.json()["booth_id"], r.json()["booth_no"]) == (str(ws.booths[1]), 2)
    r = correct(client, boss, ws.voters[2], {"booth_id": str(ws.booths[1]), "serial_no": 1}, reason="booth_changed")
    assert r.status_code == 409 and code(r) == "serial_in_use"


@pytest.mark.parametrize("fields, field", [
    ({"age": 10}, "age"), ({"epic_no": "bad epic"}, "epic_no"), ({"gender": "X"}, "gender"),
])
def test_correct_checks_each_value(client, ws, boss, fields, field):
    r = correct(client, boss, ws.voters[1], fields)
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["loc"] == ["body", "fields", field]


@pytest.mark.parametrize("fields", [{}, {"is_surveyed": True}, {"first_name_en": None, "last_name_en": None}])
def test_correct_refuses_bad_requests(client, ws, boss, fields, owner_conn):
    r = correct(client, boss, ws.voters[1], fields)
    assert r.status_code == 422 and code(r) == "validation_error"
    assert edits(owner_conn, ws.voters[1]) == []


def test_correct_epic_of_another_voter_is_409(client, ws, boss):
    r = correct(client, boss, ws.voters[3], {"epic_no": "EDT1000001"})
    assert r.status_code == 409 and code(r) == "epic_in_use" and r.json()["error"]["voter_id"] == str(ws.voters[1])


def test_a_removed_voter_is_restored_before_a_correction(client, ws, boss):
    remove(client, boss, ws.voters[1])
    assert correct(client, boss, ws.voters[1], {"house_no": "X"}).status_code == 404


# --- remove and restore -------------------------------------------------------------------------------
def test_remove_and_restore_twice_write_one_edit_each(client, ws, boss, owner_conn):
    vid = ws.voters[2]
    assert restore(client, boss, vid).status_code == 200   # live voter: nothing to do
    assert remove(client, boss, vid).status_code == 200
    assert remove(client, boss, vid).status_code == 200
    assert restore(client, boss, vid).status_code == 200
    assert restore(client, boss, vid).status_code == 200
    assert [e[0] for e in edits(owner_conn, vid)] == ["remove", "restore"]


def test_restore_into_a_taken_serial_or_epic_is_409(client, ws, boss, owner_conn):
    vid = ws.voters[1]
    remove(client, boss, vid)
    r = client.post(f"{API}/voters", headers=boss,
                    json=new_voter(ws, booth_id=str(ws.booths[0]), serial_no=1, epic_no="EDT1000001"))
    assert r.status_code == 201, r.text
    newcomer = r.json()["id"]
    r = restore(client, boss, vid)
    assert r.status_code == 409 and code(r) == "epic_in_use" and r.json()["error"]["voter_id"] == newcomer
    assert owner_conn.execute("SELECT deleted_at IS NOT NULL FROM app.voters WHERE id = %s", (vid,)).fetchone()[0]
    assert correct(client, boss, newcomer, {"epic_no": "EDT1000009"}).status_code == 200
    r = restore(client, boss, vid)
    assert r.status_code == 409 and code(r) == "serial_in_use"


def test_removed_list_is_for_admins_only(client, ws, boss, admin, set_device_status):
    remove(client, boss, ws.voters[3])
    assert search(client, admin, "meena", removed=True) == [str(ws.voters[3])]
    sup = bearer(login(client, ws, "sup1").json())
    r = client.get(f"{API}/voters", headers=sup, params={"removed": True})
    assert r.status_code == 403 and code(r) == "forbidden_role"


def test_roll_edits_of_a_removed_voter_page_newest_first(client, ws, boss):
    vid = ws.voters[1]
    for house in ("A", "B", "C"):
        correct(client, boss, vid, {"house_no": house})
    remove(client, boss, vid)
    r = client.get(f"{API}/voters/{vid}/roll-edits", headers=boss, params={"limit": 3})
    page = r.json()
    assert [e["action"] for e in page["items"]] == ["remove", "correct", "correct"]
    assert page["items"][1]["new_values"] == {"house_no": "C"}
    r = client.get(f"{API}/voters/{vid}/roll-edits", headers=boss, params={"limit": 3, "cursor": page["next_cursor"]})
    assert [e["new_values"] for e in r.json()["items"]] == [{"house_no": "A"}] and r.json()["next_cursor"] is None


# --- phones -----------------------------------------------------------------------------------------------
def test_phones_drop_a_removed_voter_and_get_it_back_with_its_survey(client, ws, boss, owner_conn):
    vid = ws.voters[1]
    owner_conn.execute("INSERT INTO app.voter_surveys (voter_id, tenant_id, notes) VALUES (%s, %s, 'kept')",
                       (vid, ws.tenant))
    sup = bearer(login(client, ws, "sup1").json())
    w = download(client, sup).first["watermark"]
    remove(client, boss, vid)
    d = download(client, sup, since=w)
    [v] = [v for p in d.pages for v in p["voters"]]
    assert v["id"] == str(vid) and v["deleted_at"] is not None

    w = d.first["watermark"]
    restore(client, boss, vid)
    d = download(client, sup, since=w)
    [v] = [v for p in d.pages for v in p["voters"]]
    assert v["deleted_at"] is None
    assert [s["notes"] for p in d.pages for s in p["surveys"]] == ["kept"]   # unchanged survey comes again
