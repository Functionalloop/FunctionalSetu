"""Reports (11.1): GET /reports/survey-progress, /colour-tags, /demographics, /turnout. Fake voters only.
Generic rules (401, 403 per role, other workspace and area): test_endpoint_rules.py."""

from __future__ import annotations

import uuid

import pytest

from conftest import bearer, login

API = "/api/v1"

# booth ("b1", "b2" in ward 1; "b3" in ward 2), gender, age, survey (None = no row, else (is_surveyed, tag no.))
VOTERS = [
    ("b1", "F", 22, (True, 0)),
    ("b1", "M", 30, (True, 1)),
    ("b1", "F", 47, (False, None)),   # a survey row that is not a survey (e.g. a mobile sheet made it)
    ("b1", "O", 80, None),
    ("b1", "M", None, None),          # no age on the roll
    ("b2", "F", 60, (True, 0)),
    ("b2", "M", 19, None),
    ("b3", "F", 35, (True, 0)),
    ("b3", "M", 40, None),
]


@pytest.fixture
def ws(make_workspace, owner_conn, client):
    """Ward 1 (booths b1, b2) as make_workspace builds it, plus ward 2 with booth b3 in the same
    constituency. sup1 has ward 1; sup2 has only booth b3 (not its ward). Also a removed voter in b1
    (counted nowhere) and a voter of b2 absent from the current roll (counted, but not in turnout)."""
    w = make_workspace("reports", extra_users={"sup2": "supervisor"})
    w.ward2, b3 = uuid.uuid4(), uuid.uuid4()
    geo = """INSERT INTO app.geo_units (id, tenant_id, parent_id, level, code, number, name_mr, name_en)
             VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"""
    owner_conn.execute(geo, (w.ward2, w.tenant, w.local_body, "ward", "2", 2, "W2", "Ward 2"))
    owner_conn.execute(geo, (b3, w.tenant, w.ward2, "booth", "2001", 1, "B3", "Booth 3"))
    owner_conn.execute("INSERT INTO app.user_area_assignments (tenant_id, user_id, geo_unit_id) VALUES (%s, %s, %s)",
                       (w.tenant, w.users["sup2"], b3))
    w.b = {"b1": (w.ward, w.booths[0]), "b2": (w.ward, w.booths[1]), "b3": (w.ward2, b3)}
    w.tags = [r[0] for r in owner_conn.execute(
        "SELECT id FROM app.color_tags WHERE tenant_id = %s AND is_active ORDER BY sort_order, code LIMIT 2",
        (w.tenant,)).fetchall()]

    def voter(booth, gender, age, serial, **extra):
        cols = ", ".join(extra)
        return owner_conn.execute(
            f"""INSERT INTO app.voters (tenant_id, local_body_id, ward_id, booth_id, part_no, serial_no, gender, age,
                                        first_name_en{', ' + cols if cols else ''})
                VALUES (%s, %s, %s, %s, 1, %s, %s, %s, 'Fake'{', %s' * len(extra)}) RETURNING id""",
            (w.tenant, w.local_body, *w.b[booth], serial, gender, age, *extra.values())).fetchone()[0]

    w.v = []
    for serial, (booth, gender, age, survey) in enumerate(VOTERS, start=1):
        vid = voter(booth, gender, age, serial)
        w.v.append(vid)
        if survey is not None:
            surveyed, tag = survey
            owner_conn.execute("INSERT INTO app.voter_surveys (voter_id, tenant_id, is_surveyed, color_tag_id) "
                               "VALUES (%s, %s, %s, %s)", (vid, w.tenant, surveyed, None if tag is None else w.tags[tag]))
    w.removed = voter("b1", "F", 33, 101)
    owner_conn.execute("INSERT INTO app.voter_surveys (voter_id, tenant_id, is_surveyed, color_tag_id) "
                       "VALUES (%s, %s, true, %s)", (w.removed, w.tenant, w.tags[0]))
    owner_conn.execute("UPDATE app.voters SET deleted_at = now() WHERE id = %s", (w.removed,))
    w.absent = voter("b2", "F", 50, 102, roll_status="absent_from_current_roll")

    w.boss, w.sup, w.sup2 = (bearer(login(client, w, u).json()) for u in ("boss", "sup1", "sup2"))
    return w


def get(client, h, path, status=200, **params):
    r = client.get(f"{API}/reports/{path}", headers=h, params={k: str(v) for k, v in params.items()})
    assert r.status_code == status, r.text
    return r.json()


def voters_listed(client, h, **params) -> int:
    r = client.get(f"{API}/voters", headers=h, params={"limit": 200, **{k: str(v) for k, v in params.items()}})
    assert r.status_code == 200 and r.json()["next_cursor"] is None, r.text
    return len(r.json()["items"])


def area_ids(report) -> list[str]:
    return [a["area_id"] for a in report["by_area"]]


# --- survey progress -------------------------------------------------------------------------------
def test_survey_progress_totals_equal_the_voter_list(client, ws, owner_conn):
    s = get(client, ws.boss, "survey-progress")
    assert (s["total"], s["surveyed"], s["percent"]) == (10, 4, 40.0)   # removed voter left out, absent counted
    assert s["total"] == voters_listed(client, ws.boss)
    assert s["surveyed"] == voters_listed(client, ws.boss, survey_status="surveyed")
    direct = owner_conn.execute("""
        SELECT count(*), count(*) FILTER (WHERE s.is_surveyed) FROM app.voters v
          LEFT JOIN app.voter_surveys s ON s.voter_id = v.id
         WHERE v.tenant_id = %s AND v.deleted_at IS NULL""", (ws.tenant,)).fetchone()
    assert (s["total"], s["surveyed"]) == direct
    for a in s["by_area"]:
        key = "ward_id" if a["level"] == "ward" else "booth_id"
        assert a["total"] == voters_listed(client, ws.boss, **{key: a["area_id"]}), a
        assert a["done"] == voters_listed(client, ws.boss, survey_status="surveyed", **{key: a["area_id"]}), a


def test_survey_progress_by_area_is_each_ward_then_its_booths(client, ws):
    b1, b2, b3 = (str(ws.b[k][1]) for k in ("b1", "b2", "b3"))
    s = get(client, ws.boss, "survey-progress")
    assert area_ids(s) == [str(ws.ward), b1, b2, str(ws.ward2), b3]
    rows = {a["area_id"]: (a["level"], a["parent_id"], a["name"], a["total"], a["done"], a["percent"])
            for a in s["by_area"]}
    assert rows[str(ws.ward)] == ("ward", None, "Ward 1", 8, 3, 37.5)
    assert rows[b1] == ("booth", str(ws.ward), "Booth 1", 5, 2, 40.0)
    assert rows[b2] == ("booth", str(ws.ward), "Booth 2", 3, 1, 33.3)
    assert rows[b3] == ("booth", str(ws.ward2), "Booth 3", 2, 1, 50.0)


def test_supervisor_gets_only_own_wards(client, ws):
    b1, b2, b3 = (str(ws.b[k][1]) for k in ("b1", "b2", "b3"))
    s = get(client, ws.sup, "survey-progress")
    assert (s["total"], s["surveyed"]) == (8, 3) and area_ids(s) == [str(ws.ward), b1, b2]
    assert set(get(client, ws.sup, "colour-tags")["by_area"]) == {str(ws.ward), b1, b2}
    assert get(client, ws.sup, "demographics")["total"] == 8
    assert area_ids(get(client, ws.sup, "turnout")) == [str(ws.ward), b1, b2]
    for path in ("survey-progress", "colour-tags", "demographics", "turnout"):
        assert get(client, ws.sup, path, status=404, ward_id=ws.ward2)["error"]["code"] == "not_found"
    assert get(client, ws.sup, "demographics", status=404, booth_id=b3)["error"]["code"] == "not_found"
    # a supervisor with one booth of ward 2 gets that booth, not the ward
    s2 = get(client, ws.sup2, "survey-progress")
    assert (s2["total"], area_ids(s2)) == (2, [b3])
    assert s2["by_area"][0]["parent_id"] == str(ws.ward2)


def test_ward_id_narrows_to_that_area(client, ws):
    b2 = ws.b["b2"][1]
    s = get(client, ws.boss, "survey-progress", ward_id=ws.ward2)
    assert (s["total"], s["surveyed"], area_ids(s)) == (2, 1, [str(ws.ward2), str(ws.b["b3"][1])])
    one = get(client, ws.sup, "survey-progress", ward_id=b2)   # a booth works too
    assert (one["total"], area_ids(one)) == (3, [str(b2)])


def test_empty_area_gives_zeros(client, ws, owner_conn):
    owner_conn.execute("DELETE FROM app.user_area_assignments WHERE user_id = %s", (ws.users["sup2"],))
    s = get(client, ws.sup2, "survey-progress")
    assert s == {"total": 0, "surveyed": 0, "percent": 0.0, "by_area": []}
    assert get(client, ws.sup2, "turnout") == {"total": 0, "voted": 0, "percent": 0.0, "by_area": [], "by_hour": []}


# --- colour tags -----------------------------------------------------------------------------------
def test_colour_tags_count_each_tag_and_no_tag(client, ws):
    t0, t1 = (str(t) for t in ws.tags)
    c = get(client, ws.boss, "colour-tags")
    assert c["total"] == 10
    assert c["by_tag"] == [{"color_tag_id": t0, "count": 3}, {"color_tag_id": t1, "count": 1},
                           {"color_tag_id": None, "count": 6}]
    assert sum(x["count"] for x in c["by_tag"]) == c["total"]
    assert c["by_area"][str(ws.ward2)] == [{"color_tag_id": t0, "count": 1}, {"color_tag_id": None, "count": 1}]
    b2 = c["by_area"][str(ws.b["b2"][1])]
    assert b2 == [{"color_tag_id": t0, "count": 1}, {"color_tag_id": None, "count": 2}]
    for tag, n in ((t0, 3), (t1, 1)):
        assert voters_listed(client, ws.boss, color_tag_id=tag) == n


# --- demographics ----------------------------------------------------------------------------------
def test_demographics_by_gender_and_age_band(client, ws):
    d = get(client, ws.boss, "demographics")
    assert (d["total"], d["male"], d["female"], d["other"]) == (10, 4, 5, 1)
    assert d["total"] == voters_listed(client, ws.boss)
    assert d["female"] == voters_listed(client, ws.boss, gender="F")
    bands = {b["band"]: (b["male"], b["female"], b["other"]) for b in d["age_bands"]}
    assert list(bands) == ["18-25", "26-35", "36-45", "46-55", "56-65", "66-75", "76+", "unknown"]
    assert bands == {"18-25": (1, 1, 0), "26-35": (1, 1, 0), "36-45": (1, 0, 0), "46-55": (0, 2, 0),
                     "56-65": (0, 1, 0), "66-75": (0, 0, 0), "76+": (0, 0, 1), "unknown": (1, 0, 0)}
    assert bands["18-25"][0] + bands["18-25"][1] == voters_listed(client, ws.boss, age_min=18, age_max=25)


def test_demographics_of_one_booth_has_no_unknown_band_when_every_age_is_known(client, ws):
    d = get(client, ws.sup, "demographics", booth_id=ws.b["b2"][1])
    assert (d["total"], d["male"], d["female"], d["other"]) == (3, 1, 2, 0)
    assert [b["band"] for b in d["age_bands"]][-1] == "76+"


# --- turnout ---------------------------------------------------------------------------------------
def mark(client, h, voter, at):
    r = client.post(f"{API}/turnout/marks", headers=h,
                    json={"id": str(uuid.uuid4()), "voter_ids": [str(voter)], "marked_at": at})
    assert r.status_code == 200 and r.json()["marked"] == [str(voter)], r.text


def test_turnout_by_area_and_indian_hour(client, ws):
    mark(client, ws.boss, ws.v[0], "2026-11-10T03:45:00Z")   # b1, 09:15 Indian time
    mark(client, ws.boss, ws.v[5], "2026-11-10T04:10:00Z")   # b2, 09:40
    mark(client, ws.boss, ws.v[7], "2026-11-10T05:40:00Z")   # b3, 11:10
    mark(client, ws.boss, ws.v[1], "2026-11-10T06:00:00Z")   # b1, 11:30, then undone
    assert client.delete(f"{API}/turnout/marks/{ws.v[1]}", headers=ws.boss).status_code == 204

    t = get(client, ws.boss, "turnout")
    assert (t["total"], t["voted"], t["percent"]) == (9, 3, 33.3)   # the absent voter is not on the current roll
    assert t["by_hour"] == [{"hour": 9, "voted": 2, "cumulative": 2}, {"hour": 10, "voted": 0, "cumulative": 2},
                            {"hour": 11, "voted": 1, "cumulative": 3}]
    rows = {a["area_id"]: (a["total"], a["done"]) for a in t["by_area"]}
    assert rows == {str(ws.ward): (7, 2), str(ws.b["b1"][1]): (5, 1), str(ws.b["b2"][1]): (2, 1),
                    str(ws.ward2): (2, 1), str(ws.b["b3"][1]): (2, 1)}

    summary = client.get(f"{API}/turnout/summary", headers=ws.sup).json()   # the polling-day screen agrees
    s = get(client, ws.sup, "turnout")
    assert (s["total"], s["voted"], s["percent"]) == (summary["total"], summary["voted"], summary["percent"]) == (7, 2, 28.6)
    assert s["by_hour"] == [{"hour": 9, "voted": 2, "cumulative": 2}]
    assert get(client, ws.sup2, "turnout")["by_hour"] == [{"hour": 11, "voted": 1, "cumulative": 1}]


def test_no_marks_gives_no_hours(client, ws):
    t = get(client, ws.boss, "turnout")
    assert (t["voted"], t["by_hour"]) == (0, [])
