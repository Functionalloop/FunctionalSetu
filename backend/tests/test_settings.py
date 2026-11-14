"""Election settings (9.4): GET/PUT /settings/election. Generic rules: test_endpoint_rules.py."""

from __future__ import annotations

import uuid

import pytest

from conftest import bearer, login, phone
from endpoints import PNG_1PX

API = "/api/v1"


def code(resp) -> str:
    return resp.json()["error"]["code"]


@pytest.fixture
def ws(make_workspace):
    return make_workspace()


@pytest.fixture
def admin(client, ws):
    return bearer(login(client, ws, "admin1").json())


ELECTION = {"election_name_en": "Pernem 2027", "election_type": "vidhan_sabha", "polling_date": "2027-02-14",
            "polling_start_time": "07:00:00", "polling_end_time": "18:00:00", "candidate_name_en": "A. Candidate",
            "party_name_en": "Party", "contact_no": "9876500010", "sms_fields": ["election_name", "symbol"]}


def test_admin_saves_the_election_and_candidate_a_supervisor_cannot(client, ws, admin):
    before = client.get(f"{API}/settings/election", headers=admin)
    assert before.status_code == 200 and before.json()["election_name_en"] is None
    r = client.put(f"{API}/settings/election", headers=admin, json=ELECTION)
    assert r.status_code == 200, r.text
    s = r.json()
    assert (s["election_name_en"], s["polling_start_time"], s["polling_end_time"], s["candidate_name_en"]) == (
        "Pernem 2027", "07:00:00", "18:00:00", "A. Candidate")
    assert s["feature_survey"] is True and s["sync_interval_minutes"] == 15  # defaults for what was left out

    sup = bearer(login(client, ws, "sup1").json())
    r = client.put(f"{API}/settings/election", headers=sup, json=ELECTION)
    assert r.status_code == 403 and code(r) == "forbidden_role"


def test_a_field_left_out_is_cleared(client, ws, admin):
    client.put(f"{API}/settings/election", headers=admin, json=ELECTION)
    s = client.put(f"{API}/settings/election", headers=admin, json={"election_name_en": " Only this "}).json()
    assert s["election_name_en"] == "Only this" and s["candidate_name_en"] is None and s["polling_date"] is None


def test_code_of_conduct_hides_the_candidate_from_workers_not_from_the_admin(client, ws, admin):
    client.put(f"{API}/settings/election", headers=admin, json={**ELECTION, "code_of_conduct_mode": True})
    assert client.get(f"{API}/settings/election", headers=admin).json()["candidate_name_en"] == "A. Candidate"
    sup = bearer(login(client, ws, "sup1").json())
    me = client.get(f"{API}/me", headers=sup).json()
    assert me["settings"]["candidate_name_en"] is None and me["settings"]["election_name_en"] == "Pernem 2027"


def test_the_phone_gets_the_change_on_its_next_pull(client, ws, admin, set_device_status):
    t = login(client, ws, "survey1", device=phone("settings-phone")).json()
    set_device_status(t["device"]["id"], "approved")
    w = client.get(f"{API}/sync/pull", headers=bearer(t)).json()["watermark"]
    assert client.get(f"{API}/sync/pull", headers=bearer(t), params={"since": w}).json()["settings"] is None
    client.put(f"{API}/settings/election", headers=admin, json=ELECTION)
    s = client.get(f"{API}/sync/pull", headers=bearer(t), params={"since": w}).json()["settings"]
    assert s["polling_start_time"] == "07:00:00" and s["election_name_en"] == "Pernem 2027"


@pytest.mark.parametrize("change", [{"election_type": "mayor"}, {"sms_fields": ["nickname"]},
                                    {"polling_start_time": "18:00:00", "polling_end_time": "07:00:00"},
                                    {"sync_interval_minutes": 1}, {"contact_no": "123"},
                                    {"candidate_photo_file_id": str(uuid.uuid4())}])
def test_bad_values_are_422(client, ws, admin, change):
    r = client.put(f"{API}/settings/election", headers=admin, json={**ELECTION, **change})
    assert r.status_code == 422, r.text


def test_images_must_be_uploaded_and_of_the_right_kind(client, ws, admin):
    up = client.post(f"{API}/files", headers=admin, data={"kind": "symbol"},
                     files={"file": ("symbol.png", PNG_1PX, "image/png")})
    assert up.status_code == 201, up.text
    fid = up.json()["id"]
    r = client.put(f"{API}/settings/election", headers=admin, json={**ELECTION, "candidate_photo_file_id": fid})
    assert r.status_code == 422  # a symbol is not a candidate photo
    r = client.put(f"{API}/settings/election", headers=admin, json={**ELECTION, "symbol_file_id": fid})
    assert r.status_code == 200 and r.json()["symbol_file_id"] == fid
