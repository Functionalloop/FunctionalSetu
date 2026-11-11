"""GET /voters/{id} and PUT /voters/{id}/survey: versions, conflicts and the survey fields.

Role and isolation rules for both routes are in test_endpoint_rules.py; fake data only.
"""

from __future__ import annotations

import uuid

import pytest

from conftest import bearer, login, phone

API = "/api/v1"


@pytest.fixture
def ws(make_workspace, owner_conn):
    w = make_workspace("sv", extra_users={"agent1": "booth_agent"})
    w.voter = uuid.uuid4()
    owner_conn.execute(
        """INSERT INTO app.voters (id, tenant_id, local_body_id, ward_id, booth_id, part_no, serial_no, epic_no,
                                   first_name_en, last_name_en, gender, age, house_no)
           VALUES (%s, %s, %s, %s, %s, 1, 7, 'TST0000007', 'Asha', 'Patil', 'F', 40, '3B')""",
        (w.voter, w.tenant, w.local_body, w.ward, w.booths[0]))
    owner_conn.execute(
        "INSERT INTO app.user_area_assignments (tenant_id, user_id, geo_unit_id) VALUES (%s, %s, %s)",
        (w.tenant, w.users["agent1"], w.booths[0]))
    w.green = owner_conn.execute("SELECT id FROM app.color_tags WHERE tenant_id = %s AND code = 'green'",
                                 (w.tenant,)).fetchone()[0]
    return w


@pytest.fixture
def surveyor(client, ws, set_device_status):
    t = login(client, ws, "survey1", device=phone("phone-sv-0001")).json()
    set_device_status(t["device"]["id"], "approved")
    return bearer(t)


def save(client, ws, headers, **body):
    return client.put(f"{API}/voters/{ws.voter}/survey", headers=headers, json=body)


def test_detail_before_and_after_first_save(client, ws, surveyor):
    v = client.get(f"{API}/voters/{ws.voter}", headers=surveyor).json()
    assert v["survey"] is None and v["is_surveyed"] is False
    assert v["first_name_en"] == "Asha" and v["serial_no"] == 7 and v["list_type"] == "main"

    r = save(client, ws, surveyor, version=0, mobile_1="9876543210", color_tag_id=str(ws.green), notes="Met at home")
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["version"] == 1 and s["is_surveyed"] is True and s["surveyed_at"]
    assert s["updated_by"] == str(ws.users["survey1"])

    v = client.get(f"{API}/voters/{ws.voter}", headers=surveyor).json()
    assert v["survey"]["notes"] == "Met at home" and v["mobile_1"] == "9876543210" and v["is_surveyed"] is True


def test_two_saves_with_same_version_give_200_and_409(client, ws, surveyor):
    assert save(client, ws, surveyor, version=0, notes="first").status_code == 200
    a = save(client, ws, surveyor, version=1, notes="phone A")
    b = save(client, ws, surveyor, version=1, notes="phone B")
    assert a.status_code == 200 and a.json()["version"] == 2
    assert b.status_code == 409
    err = b.json()["error"]
    assert err["code"] == "version_conflict"
    assert err["current"]["version"] == 2 and err["current"]["notes"] == "phone A"  # the server copy
    assert save(client, ws, surveyor, version=2, notes="phone B again").json()["version"] == 3


@pytest.mark.parametrize("version", [0, 1])
def test_parallel_saves_with_same_version_one_wins(client, ws, surveyor, version):
    from concurrent.futures import ThreadPoolExecutor
    if version == 1:
        assert save(client, ws, surveyor, version=0, notes="start").status_code == 200
    with ThreadPoolExecutor(max_workers=6) as pool:
        codes = sorted(pool.map(lambda i: save(client, ws, surveyor, version=version, notes=f"p{i}").status_code,
                                range(6)))
    assert codes == [200] + [409] * 5
    final = client.get(f"{API}/voters/{ws.voter}", headers=surveyor).json()["survey"]
    assert final["version"] == version + 1


def test_two_first_saves_give_200_and_409(client, ws, surveyor):
    assert save(client, ws, surveyor, version=0, notes="A").status_code == 200
    r = save(client, ws, surveyor, version=0, notes="B")
    assert r.status_code == 409 and r.json()["error"]["current"]["notes"] == "A"


def test_version_for_a_survey_that_does_not_exist(client, ws, surveyor):
    r = save(client, ws, surveyor, version=3, notes="x")
    assert r.status_code == 409 and r.json()["error"]["current"] is None


def test_put_replaces_fields_and_keeps_first_survey_time(client, ws, surveyor):
    first = save(client, ws, surveyor, version=0, mobile_1="9876543210", mobile_2="9123456789", notes="n").json()
    second = save(client, ws, surveyor, version=1, notes="only notes").json()
    assert second["mobile_1"] is None and second["mobile_2"] is None and second["notes"] == "only notes"
    assert second["surveyed_at"] == first["surveyed_at"]


def test_notes_limit_2000(client, ws, surveyor):
    assert save(client, ws, surveyor, version=0, notes="न" * 2000).status_code == 200
    r = save(client, ws, surveyor, version=1, notes="x" * 2001)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("body", [
    {"mobile_1": "12345"},
    {"mobile_1": "5876543210"},
    {"mobile_2": "9876543210"},                          # mobile_2 without mobile_1
    {"new_address_en": "Moved to Goa"},                   # address without the residence check
    {"dob": "2999-01-01"},
    {"location": {"lat": 91, "lng": 73}},
    {"caste_id": str(uuid.uuid4())},                       # not in this workspace's lists
])
def test_bad_input_is_422(client, ws, surveyor, body):
    r = save(client, ws, surveyor, version=0, **body)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "validation_error"


def test_colour_tag_of_another_workspace_is_422(client, ws, surveyor, make_workspace, owner_conn):
    other = make_workspace("sv-other")
    their_green = owner_conn.execute("SELECT id FROM app.color_tags WHERE tenant_id = %s AND code = 'green'",
                                     (other.tenant,)).fetchone()[0]
    assert save(client, ws, surveyor, version=0, color_tag_id=str(their_green)).status_code == 422


def test_residence_check_and_location(client, ws, surveyor):
    s = save(client, ws, surveyor, version=0, has_new_address=True, new_address_en="Mapusa",
             location={"lat": 15.6, "lng": 73.8, "accuracy_m": 12}).json()
    assert s["has_new_address"] is True and s["new_address_en"] == "Mapusa"
    assert (s["lat"], s["lng"], s["location_accuracy_m"]) == (15.6, 73.8, 12) and s["location_captured_at"]

    kept = save(client, ws, surveyor, version=1, has_new_address=True, new_address_en="Mapusa").json()
    assert (kept["lat"], kept["lng"]) == (15.6, 73.8)  # no location sent: previous one kept
    assert kept["location_captured_at"] == s["location_captured_at"]


def test_custom_fields_round_trip(client, ws, surveyor):
    s = save(client, ws, surveyor, version=0, extra_check_1=True, extra_info_3="Shop owner", dob="1984-05-02",
             caste_id=None).json()
    assert s["extra_check_1"] is True and s["extra_info_3"] == "Shop owner" and s["dob"] == "1984-05-02"


def test_booth_agent_reads_but_cannot_save(client, ws, set_device_status, owner_conn):
    t = login(client, ws, "agent1", device=phone("phone-sv-0002")).json()
    set_device_status(t["device"]["id"], "approved")
    assert client.get(f"{API}/voters/{ws.voter}", headers=bearer(t)).status_code == 200
    r = save(client, ws, bearer(t), version=0, notes="should not save")
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden_role"
    assert owner_conn.execute("SELECT count(*) FROM app.voter_surveys WHERE voter_id = %s",
                              (ws.voter,)).fetchone()[0] == 0


def test_save_is_in_the_audit_log(client, ws, surveyor, owner_conn):
    save(client, ws, surveyor, version=0, notes="audited")
    save(client, ws, surveyor, version=1, notes="audited again")
    rows = owner_conn.execute(
        """SELECT action, actor_user_id FROM app.audit_log
            WHERE tenant_id = %s AND entity_type = 'voter_surveys' AND entity_id = %s ORDER BY id""",
        (ws.tenant, str(ws.voter))).fetchall()
    assert [r[0] for r in rows] == ["insert", "update"]
    assert {r[1] for r in rows} == {ws.users["survey1"]}  # who saved it, from the request's context


def test_removed_voter_is_404(client, ws, surveyor, owner_conn):
    owner_conn.execute("UPDATE app.voters SET deleted_at = now() WHERE id = %s", (ws.voter,))
    assert client.get(f"{API}/voters/{ws.voter}", headers=surveyor).status_code == 404
    assert save(client, ws, surveyor, version=0).status_code == 404
