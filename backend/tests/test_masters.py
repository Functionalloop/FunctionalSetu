"""Lists and labels (9.4): castes, professions, influencer types, colour tags, custom fields, message texts.
Generic rules: test_endpoint_rules.py."""

from __future__ import annotations

import pytest

from conftest import bearer, login, phone

API = "/api/v1"


def code(resp) -> str:
    return resp.json()["error"]["code"]


@pytest.fixture
def ws(make_workspace):
    return make_workspace()


@pytest.fixture
def admin(client, ws):
    return bearer(login(client, ws, "admin1").json())


@pytest.fixture
def phone_pull(client, ws, set_device_status):
    """A surveyor's phone after its first download; call it with no argument for a delta pull."""
    t = login(client, ws, "survey1", device=phone("masters-phone")).json()
    set_device_status(t["device"]["id"], "approved")
    h = bearer(t)
    w = client.get(f"{API}/sync/pull", headers=h).json()["watermark"]
    return lambda: client.get(f"{API}/sync/pull", headers=h, params={"since": w}).json()


def test_a_renamed_colour_tag_reaches_the_phone_on_the_next_pull(client, admin, phone_pull):
    tags = client.get(f"{API}/masters/color-tags", headers=admin).json()
    tag = next(t for t in tags if t["is_active"])
    assert phone_pull()["lists"]["color_tags"] == []
    body = {k: tag[k] for k in ("code", "hex", "label_mr", "label_en", "label_hi", "is_default", "sort_order",
                                "is_active")}
    r = client.patch(f"{API}/masters/color-tags/{tag['id']}", headers=admin, json={**body, "label_en": "Supporter"})
    assert r.status_code == 200, r.text
    got = phone_pull()["lists"]["color_tags"]
    assert [(t["id"], t["label_en"]) for t in got] == [(tag["id"], "Supporter")]


@pytest.mark.parametrize("path, key", [("castes", "castes"), ("professions", "professions"),
                                       ("influencer-types", "influencer_types")])
def test_named_lists_add_rename_and_switch_off(client, admin, phone_pull, path, key):
    r = client.post(f"{API}/masters/{path}", headers=admin, json={"name_mr": " नवीन ", "name_en": "New"})
    assert r.status_code == 201, r.text
    e = r.json()
    assert (e["name_mr"], e["name_en"], e["is_active"]) == ("नवीन", "New", True)
    r = client.post(f"{API}/masters/{path}", headers=admin, json={"name_mr": "नवीन"})
    assert r.status_code == 409 and code(r) == "name_taken"

    r = client.patch(f"{API}/masters/{path}/{e['id']}", headers=admin,
                     json={"name_mr": "नवीन", "name_en": "Renamed", "is_active": False, "sort_order": 9})
    assert r.status_code == 200 and (r.json()["name_en"], r.json()["is_active"]) == ("Renamed", False)
    listed = client.get(f"{API}/masters/{path}", headers=admin).json()
    assert any(x["id"] == e["id"] and not x["is_active"] for x in listed)  # inactive entries are listed
    assert [x["id"] for x in phone_pull()["lists"][key]] == [e["id"]]


def test_a_switched_off_caste_is_refused_by_a_new_survey(client, ws, admin, owner_conn):
    caste = client.post(f"{API}/masters/castes", headers=admin, json={"name_mr": "जुनी", "is_active": False}).json()
    vid = owner_conn.execute(
        """INSERT INTO app.voters (tenant_id, local_body_id, ward_id, booth_id, part_no, serial_no, gender, first_name_en)
           VALUES (%s, %s, %s, %s, 1, 1, 'M', 'A') RETURNING id""",
        (ws.tenant, ws.local_body, ws.ward, ws.booths[0])).fetchone()[0]
    r = client.put(f"{API}/voters/{vid}/survey", headers=admin, json={"version": 0, "caste_id": caste["id"]})
    assert r.status_code == 422


def test_one_default_colour_tag(client, admin):
    def add(code_, **kw):
        return client.post(f"{API}/masters/color-tags", headers=admin,
                           json={"code": code_, "hex": "#aabbcc", "label_mr": "x", "label_en": "x", **kw})
    a = add("first_default", is_default=True)
    assert a.status_code == 201 and a.json()["hex"] == "#AABBCC"
    b = add("second_default", is_default=True).json()
    defaults = [t["id"] for t in client.get(f"{API}/masters/color-tags", headers=admin).json() if t["is_default"]]
    assert defaults == [b["id"]]
    r = add("first_default")
    assert r.status_code == 409 and code(r) == "code_taken"
    assert add("off_default", is_default=True, is_active=False).status_code == 422
    assert add("Bad Code").status_code == 422


def test_custom_fields(client, admin, phone_pull):
    fields = client.get(f"{API}/masters/custom-fields", headers=admin).json()
    assert [f["field_key"] for f in fields] == ["extra_check_1", "extra_check_2", "extra_info_1", "extra_info_2",
                                                "extra_info_3", "extra_info_4", "extra_info_5"]
    r = client.patch(f"{API}/masters/custom-fields/extra_info_1", headers=admin, json={"is_enabled": True})
    assert r.status_code == 422  # an enabled field needs a label
    r = client.patch(f"{API}/masters/custom-fields/extra_info_1", headers=admin,
                     json={"is_enabled": True, "label_en": "Bike"})
    assert r.status_code == 200 and r.json() == {"field_key": "extra_info_1", "label_mr": None, "label_en": "Bike",
                                                 "label_hi": None, "is_enabled": True}
    assert [f["field_key"] for f in phone_pull()["lists"]["custom_field_labels"]] == ["extra_info_1"]
    assert client.patch(f"{API}/masters/custom-fields/extra_info_9", headers=admin,
                        json={"is_enabled": False}).status_code == 422


def test_message_templates(client, admin):
    kinds = [t["kind"] for t in client.get(f"{API}/masters/message-templates", headers=admin).json()]
    assert sorted(kinds) == ["birthday", "general", "slip_sms", "slip_whatsapp"]
    r = client.patch(f"{API}/masters/message-templates/birthday", headers=admin,
                     json={"body_en": "Happy birthday {name}!", "body_mr": " "})
    assert r.status_code == 200, r.text
    assert (r.json()["body_en"], r.json()["body_mr"]) == ("Happy birthday {name}!", None)
    assert client.patch(f"{API}/masters/message-templates/poster", headers=admin, json={}).status_code == 422
