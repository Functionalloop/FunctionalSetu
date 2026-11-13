"""GET /birthdays (7.8): by day and month from the survey's date of birth, in birthday order.

Fake data only. Role / login / other-workspace / other-area rules: test_endpoint_rules.py.
"""

from __future__ import annotations

import uuid

import pytest

from conftest import bearer, login, phone

API = "/api/v1"

# serial -> date of birth (None = surveyed without a date of birth)
DOBS = {1: "1980-11-13", 2: "1995-11-14", 3: "1970-12-31", 4: "2001-01-02", 5: "1984-02-29", 6: "1990-06-15", 7: None}


@pytest.fixture
def ws(make_workspace, owner_conn, client, set_device_status):
    w = make_workspace("bday")
    w.v = {}
    for serial, dob in DOBS.items():
        vid = uuid.uuid4()
        owner_conn.execute("""INSERT INTO app.voters (id, tenant_id, local_body_id, ward_id, booth_id, part_no,
                                  serial_no, gender, first_name_en)
                              VALUES (%s, %s, %s, %s, %s, 1, %s, 'F', 'Fake')""",
                           (vid, w.tenant, w.local_body, w.ward, w.booths[0], serial))
        owner_conn.execute("INSERT INTO app.voter_surveys (voter_id, tenant_id, dob, mobile_1) VALUES (%s, %s, %s, %s)",
                           (vid, w.tenant, dob, "9876543210" if serial == 1 else None))
        w.v[serial] = vid
    t = login(client, w, "survey1", device=phone("phone-bday-0001")).json()
    set_device_status(t["device"]["id"], "approved")
    w.surveyor = bearer(t)
    return w


def get(client, ws, **params):
    r = client.get(f"{API}/birthdays", headers=ws.surveyor, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def serials(ws, page):
    by_id = {str(v): s for s, v in ws.v.items()}
    return [by_id[i["voter_id"]] for i in page["items"]]


def test_one_day_with_age_and_mobile(client, ws):
    page = get(client, ws, date_from="2026-11-13")
    assert serials(ws, page) == [1]
    [b] = page["items"]
    assert (b["dob"], b["turns"], b["mobile_1"], b["full_name_en"]) == ("1980-11-13", 46, "9876543210", "Fake")


def test_range_over_the_year_end_is_in_birthday_order(client, ws):
    page = get(client, ws, date_from="2026-11-13", date_to="2027-01-05")
    assert serials(ws, page) == [1, 2, 3, 4]  # 13 Nov, 14 Nov, 31 Dec, then 2 Jan
    turns = {i["voter_id"]: i["turns"] for i in page["items"]}
    assert turns[str(ws.v[3])] == 56 and turns[str(ws.v[4])] == 26  # the 2 Jan birthday falls in 2027


def test_29_february_shows_on_28_february_in_other_years(client, ws):
    assert serials(ws, get(client, ws, date_from="2027-02-28")) == [5]
    assert serials(ws, get(client, ws, date_from="2028-02-28")) == []
    assert serials(ws, get(client, ws, date_from="2028-02-29")) == [5]


def test_whole_year_pages_join_up(client, ws):
    whole = serials(ws, get(client, ws, date_from="2026-03-01", date_to="2027-02-28"))
    assert whole == [6, 1, 2, 3, 4, 5]  # from 1 Mar: Jun, Nov, Nov, Dec, Jan, Feb; none without a date
    paged, cursor = [], None
    while True:
        page = get(client, ws, date_from="2026-03-01", date_to="2027-02-28", limit=2, **({"cursor": cursor} if cursor else {}))
        paged += serials(ws, page)
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert paged == whole


def test_part_filter_and_bad_ranges(client, ws):
    assert serials(ws, get(client, ws, date_from="2026-11-13", booth_id=str(ws.booths[0]))) == [1]
    for bad in ({"date_from": "2026-11-13", "date_to": "2026-11-12"}, {"date_from": "2026-11-13", "date_to": "2027-11-14"}):
        r = client.get(f"{API}/birthdays", headers=ws.surveyor, params=bad)
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    r = client.get(f"{API}/birthdays", headers=ws.surveyor, params={"date_from": "2026-11-13", "cursor": "bm9wZQ"})
    assert r.status_code == 400


def test_removed_voter_is_left_out(client, ws, owner_conn):
    owner_conn.execute("UPDATE app.voters SET deleted_at = now() WHERE id = %s", (ws.v[1],))
    assert serials(ws, get(client, ws, date_from="2026-11-13")) == []
