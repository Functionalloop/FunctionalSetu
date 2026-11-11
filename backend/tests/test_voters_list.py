"""GET /voters: search, filters, cursor paging, and area / workspace isolation. Fake data only."""

from __future__ import annotations

import uuid

import pytest

from conftest import bearer, login, phone

API = "/api/v1"


class Roll:
    """A workspace with fake voters in booth 1 and booth 2."""

    def __init__(self, ws, owner_conn):
        self.ws, self.conn, self.ids = ws, owner_conn, {}

    def voter(self, key: str, booth: int, serial: int, *, first="Asha", last="Patil", gender="F", age=30,
              epic=None, house=None, first_mr=None, deleted=False) -> uuid.UUID:
        vid = uuid.uuid4()
        self.conn.execute(
            """INSERT INTO app.voters (id, tenant_id, local_body_id, ward_id, booth_id, part_no, booth_no,
                                       serial_no, epic_no, first_name_en, last_name_en, first_name_mr,
                                       gender, age, house_no, deleted_at)
               VALUES (%s, %s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       CASE WHEN %s THEN now() END)""",
            (vid, self.ws.tenant, self.ws.local_body, self.ws.ward, self.ws.booths[booth - 1], booth, serial,
             epic, first, last, first_mr, gender, age, house, deleted))
        self.ids[key] = vid
        return vid

    def survey(self, key: str, **cols) -> None:
        cols = {"is_surveyed": True, **cols}
        names = ", ".join(cols)
        marks = ", ".join(["%s"] * len(cols))
        self.conn.execute(f"INSERT INTO app.voter_surveys (tenant_id, voter_id, {names}) VALUES (%s, %s, {marks})",
                          (self.ws.tenant, self.ids[key], *cols.values()))

    def color(self, code: str) -> uuid.UUID:
        return self.conn.execute("SELECT id FROM app.color_tags WHERE tenant_id = %s AND code = %s",
                                 (self.ws.tenant, code)).fetchone()[0]


@pytest.fixture
def roll(make_workspace, owner_conn) -> Roll:
    r = Roll(make_workspace("vl", extra_users={"agent1": "booth_agent"}), owner_conn)
    r.voter("a1", 1, 1, first="Asha", last="Patil", epic="TST0000001", house="12A", age=25)
    r.voter("a2", 1, 2, first="Ramesh", last="Naik", gender="M", age=61, house="14")
    r.voter("a3", 1, 3, first="Sunita", last="Gawade", age=40, first_mr="सुनीता")
    r.voter("a4", 1, 12, first="Vijay", last="Patil", gender="M", age=33)
    r.voter("b1", 2, 1, first="Kavita", last="Patil", age=28)
    r.voter("b2", 2, 2, first="Mahesh", last="Desai", gender="M", age=45)
    r.voter("gone", 1, 4, first="Removed", last="Person", deleted=True)
    return r


def token(client, ws, username, set_device_status=None, uid=None):
    if set_device_status is None:
        return login(client, ws, username).json()
    t = login(client, ws, username, device=phone(uid)).json()
    set_device_status(t["device"]["id"], "approved")
    return t


def ids(client, t, **params) -> list[uuid.UUID]:
    r = client.get(f"{API}/voters", headers=bearer(t), params=params)
    assert r.status_code == 200, r.text
    return [uuid.UUID(v["id"]) for v in r.json()["items"]]


def keys(roll, found) -> list[str]:
    back = {v: k for k, v in roll.ids.items()}
    return [back[v] for v in found]


# --- paging -------------------------------------------------------------------------
def test_paging_returns_every_voter_once_in_roll_order(client, roll):
    t = token(client, roll.ws, "admin1")
    seen, cursor, pages = [], None, 0
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        body = client.get(f"{API}/voters", headers=bearer(t), params=params).json()
        seen += [uuid.UUID(v["id"]) for v in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert pages == 3
    assert keys(roll, seen) == ["a1", "a2", "a3", "a4", "b1", "b2"]  # removed voter never listed


def test_bad_cursor_and_limit(client, roll):
    t = token(client, roll.ws, "admin1")
    r = client.get(f"{API}/voters", headers=bearer(t), params={"cursor": "not-a-cursor"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_cursor"
    assert client.get(f"{API}/voters", headers=bearer(t), params={"limit": 201}).status_code == 422


# --- area and workspace isolation ----------------------------------------------------
def test_booth_2_voter_not_listed_for_booth_1_surveyor(client, roll, set_device_status):
    t = token(client, roll.ws, "survey1", set_device_status, "phone-vl-0001")
    assert keys(roll, ids(client, t)) == ["a1", "a2", "a3", "a4"]
    assert ids(client, t, q="kavita") == []
    r = client.get(f"{API}/voters", headers=bearer(t), params={"booth_id": str(roll.ws.booths[1])})
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_other_workspace_sees_none(client, roll, make_workspace):
    other = make_workspace("vl-other")
    t = token(client, other, "boss")
    assert ids(client, t) == []
    r = client.get(f"{API}/voters", headers=bearer(t), params={"ward_id": str(roll.ws.ward)})
    assert r.status_code == 404


def test_unassigned_booth_agent_sees_none(client, roll, set_device_status):
    t = token(client, roll.ws, "agent1", set_device_status, "phone-vl-0002")
    assert ids(client, t) == []


def test_needs_approved_phone(client, roll):
    assert client.get(f"{API}/voters").status_code == 401
    t = login(client, roll.ws, "survey1", device=phone("phone-vl-0003")).json()
    r = client.get(f"{API}/voters", headers=bearer(t))
    assert r.status_code == 403 and r.json()["error"]["code"] == "device_pending"


# --- search ---------------------------------------------------------------------------
@pytest.mark.parametrize("q, expected", [
    ("patil", ["a1", "a4", "b1"]),
    ("PATIL asha", ["a1"]),               # every word must match, any case
    ("tst0000001", ["a1"]),               # EPIC
    ("12a", ["a1"]),                      # house number
    ("सुनीता", ["a3"]),                     # Marathi name
    ("12", ["a1", "a4"]),                 # house 12A, and serial 12
    ("2", ["a1", "a2", "b2"]),            # house 12A contains "2"; serial 2 in both booths
    ("%", []),                            # LIKE wildcards are literal
    ("nobody", []),
])
def test_search(client, roll, q, expected):
    t = token(client, roll.ws, "admin1")
    assert keys(roll, ids(client, t, q=q)) == expected


def test_number_matches_mobile_from_4_digits(client, roll):
    roll.survey("a3", mobile_1="9876501234")
    t = token(client, roll.ws, "admin1")
    assert keys(roll, ids(client, t, q="01234")) == ["a3"]
    assert keys(roll, ids(client, t, q="987")) == []  # 3 digits: serial / name text only


def test_too_many_words(client, roll):
    t = token(client, roll.ws, "admin1")
    r = client.get(f"{API}/voters", headers=bearer(t), params={"q": "a b c d e f"})
    assert r.status_code == 422


# --- filters --------------------------------------------------------------------------
def test_filters(client, roll):
    green, red = roll.color("green"), roll.color("red")
    roll.survey("a1", color_tag_id=green, mobile_1="9000000001")
    roll.survey("a2", color_tag_id=red)
    roll.survey("b2", is_surveyed=False, color_tag_id=green)
    t = token(client, roll.ws, "admin1")

    assert keys(roll, ids(client, t, ward_id=str(roll.ws.ward), booth_id=str(roll.ws.booths[1]))) == ["b1", "b2"]
    assert keys(roll, ids(client, t, gender="M")) == ["a2", "a4", "b2"]
    assert keys(roll, ids(client, t, age_min=30, age_max=45)) == ["a3", "a4", "b2"]
    assert keys(roll, ids(client, t, color_tag_id=str(green))) == ["a1", "b2"]
    assert keys(roll, ids(client, t, survey_status="surveyed")) == ["a1", "a2"]
    assert keys(roll, ids(client, t, survey_status="not_surveyed")) == ["a3", "a4", "b1", "b2"]
    assert keys(roll, ids(client, t, has_mobile="true")) == ["a1"]
    assert len(ids(client, t, has_mobile="false")) == 5
    assert keys(roll, ids(client, t, gender="M", booth_id=str(roll.ws.booths[0]))) == ["a2", "a4"]


def test_item_fields(client, roll):
    roll.survey("a1", mobile_1="9000000001")
    t = token(client, roll.ws, "admin1")
    item = client.get(f"{API}/voters", headers=bearer(t), params={"q": "asha"}).json()["items"][0]
    assert item["full_name_en"] == "Patil Asha" and item["full_name_mr"] is None
    assert item["serial_no"] == 1 and item["booth_id"] == str(roll.ws.booths[0])
    assert item["mobile_1"] == "9000000001" and item["is_surveyed"] is True
    assert item["roll_status"] == "active"


def test_voters_under_switched_off_ward_are_hidden(client, roll):
    roll.conn.execute("UPDATE app.geo_units SET is_active = false WHERE id = %s", (roll.ws.ward,))
    for user in ("admin1", "boss"):
        t = token(client, roll.ws, user)
        assert ids(client, t) == []
        r = client.get(f"{API}/voters/{roll.ids['a1']}", headers=bearer(t))
        assert r.status_code == 404
