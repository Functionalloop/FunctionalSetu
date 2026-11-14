"""Exports (11.2): POST /exports, GET /exports/{id}, GET /exports/{id}/download and the worker's "export" job
(app/export_jobs.py). Fake voters only. Generic rules (401, 403 per role, other workspace and area):
test_endpoint_rules.py."""

from __future__ import annotations

import io
import uuid

import pytest
from openpyxl import load_workbook

from app import export_jobs, worker
from conftest import bearer, login

API = "/api/v1"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# booth, serial, EPIC, first (en), last (en), Marathi first name, gender, age, house, mobile
VOTERS = [
    ("b1", 1, "EXP1000001", "Asha", "Naik", "आशा", "F", 30, "12", "9876500001"),
    ("b1", 2, "EXP1000002", "Ravi", "Naik", "रवी", "M", 34, "12", None),
    ("b1", 3, "EXP1000003", "Sunita", "Parab", None, "F", 52, "3A", "9876500003"),
    ("b1", 4, "EXP1000004", "Meena", "Gawas", None, "F", 61, None, None),
    ("b1", 5, "EXP1000005", "Prakash", "Kamat", None, "M", 45, "3", None),
    ("b2", 1, "EXP1000006", "Kavita", "Shet", None, "F", 23, "7", "9876500006"),
    ("b2", 2, "EXP1000007", "Mohan", "Shet", None, "M", 27, "7", None),
    ("b3", 1, "EXP1000008", "Lata", "Desai", None, "F", 40, "1", "9876500008"),
]


@pytest.fixture
def ws(make_workspace, owner_conn, client):
    """Ward 1 (b1, b2) as make_workspace builds it, plus ward 2 with b3. sup1 has ward 1, sup2 only b3."""
    w = make_workspace("export", extra_users={"sup2": "supervisor"})
    w.ward2, b3 = uuid.uuid4(), uuid.uuid4()
    geo = """INSERT INTO app.geo_units (id, tenant_id, parent_id, level, code, number, name_mr, name_en)
             VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"""
    owner_conn.execute(geo, (w.ward2, w.tenant, w.local_body, "ward", "2", 2, "W2", "Ward 2"))
    owner_conn.execute(geo, (b3, w.tenant, w.ward2, "booth", "2001", 1, "B3", "Booth 3"))
    owner_conn.execute("INSERT INTO app.user_area_assignments (tenant_id, user_id, geo_unit_id) VALUES (%s, %s, %s)",
                       (w.tenant, w.users["sup2"], b3))
    w.b = {"b1": (w.ward, w.booths[0]), "b2": (w.ward, w.booths[1]), "b3": (w.ward2, b3)}
    w.v = {}
    for booth, serial, epic, first, last, first_mr, gender, age, house, mobile in VOTERS:
        vid = owner_conn.execute(
            """INSERT INTO app.voters (tenant_id, local_body_id, ward_id, booth_id, part_no, serial_no, epic_no,
                                       first_name_en, last_name_en, first_name_mr, gender, age, house_no)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (w.tenant, w.local_body, *w.b[booth], int(booth[1]), serial, epic, first, last, first_mr, gender, age, house)).fetchone()[0]
        w.v[epic] = vid
        if mobile:
            owner_conn.execute("INSERT INTO app.voter_surveys (voter_id, tenant_id, mobile_1, is_surveyed) "
                               "VALUES (%s, %s, %s, true)", (vid, w.tenant, mobile))
    w.boss, w.admin, w.sup, w.sup2 = (bearer(login(client, w, u).json()) for u in ("boss", "admin1", "sup1", "sup2"))
    return w


def start(client, h, status=202, **body):
    r = client.post(f"{API}/exports", headers=h, json={"format": "xlsx", "language": "en", **body})
    assert r.status_code == status, r.text
    return r.json()


def run_jobs():
    """Run the queued export jobs (also any other test left queued: harmless)."""
    handlers = {export_jobs.KIND: worker.HANDLERS[export_jobs.KIND]}
    for _ in range(200):
        if not worker.run_one(handlers):
            return
    raise AssertionError("export jobs keep coming")


def finished(client, h, export_id):
    run_jobs()
    r = client.get(f"{API}/exports/{export_id}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def download(client, h, export_id, status=200):
    r = client.get(f"{API}/exports/{export_id}/download", headers=h)
    assert r.status_code == status, r.text
    return r


def sheet_rows(data: bytes, first_heading: str) -> list[tuple]:
    """The data rows under the headings row that starts with `first_heading`, up to a blank row."""
    rows = list(load_workbook(io.BytesIO(data)).active.iter_rows(values_only=True))
    start_at = next(i for i, r in enumerate(rows) if r and r[0] == first_heading)
    width = len([v for v in rows[start_at] if v is not None])   # rows are padded to the widest table
    out = []
    for r in rows[start_at + 1:]:
        if not any(v is not None for v in r):
            break
        out.append(tuple(r[:width]))
    return out


def listed(client, h, **params) -> list[dict]:
    r = client.get(f"{API}/voters", headers=h, params={"limit": 200, **{k: str(v) for k, v in params.items()}})
    assert r.status_code == 200 and r.json()["next_cursor"] is None, r.text
    return r.json()["items"]


# --- the plan's test: an Excel export of a filter = GET /voters with that filter ----------------------
@pytest.mark.parametrize("flt", [{}, {"gender": "F"}, {"booth_id": "b1", "age_min": 30}, {"q": "naik"},
                                 {"has_mobile": True}, {"ward_id": "ward"}])
def test_excel_voter_list_has_the_rows_of_get_voters(client, ws, flt):
    flt = {k: str(ws.b[v][1]) if v in ws.b else str(ws.ward) if v == "ward" else v for k, v in flt.items()}
    e = start(client, ws.sup, kind="voter_list", filter=flt, columns=["part_no", "serial_no", "epic_no", "name"])
    assert e["status"] == "queued" and e["row_count"] is None
    done = finished(client, ws.sup, e["id"])
    want = [(v["part_no"], v["serial_no"], v["epic_no"], v["full_name_en"]) for v in listed(client, ws.sup, **flt)]
    assert done["status"] == "done" and done["row_count"] == len(want) and done["page_count"] is None
    r = download(client, ws.sup, e["id"])
    assert r.headers["content-type"] == XLSX and "attachment" in r.headers["content-disposition"]
    assert sheet_rows(r.content, "Part") == want


def test_supervisor_list_holds_only_own_wards(client, ws):
    e = start(client, ws.sup, kind="voter_list", columns=["epic_no"])
    got = {r[0] for r in sheet_rows(download(client, ws.sup, finished(client, ws.sup, e["id"])["id"]).content, "EPIC")}
    assert got == {epic for booth, _, epic, *_ in VOTERS if booth != "b3"}


def test_mobile_list_and_default_columns(client, ws):
    e = start(client, ws.boss, kind="mobile_list")
    assert finished(client, ws.boss, e["id"])["row_count"] == 4
    rows = sheet_rows(download(client, ws.boss, e["id"]).content, "Part")
    assert [r[-1] for r in rows] == ["9876500001", "9876500003", "9876500006", "9876500008"]
    assert start(client, ws.boss, 422, kind="mobile_list", filter={"has_mobile": False})["error"]["code"] == \
        "validation_error"


def test_group_by_house_orders_houses_naturally(client, ws):
    e = start(client, ws.sup, kind="voter_list", filter={"booth_id": str(ws.booths[0])}, columns=["house_no", "serial_no"],
              options={"group_by_house": True})
    finished(client, ws.sup, e["id"])
    assert sheet_rows(download(client, ws.sup, e["id"]).content, "House No.") == [
        ("3", 5), ("3A", 3), ("12", 1), ("12", 2), (None, 4)]


def test_marathi_pdf_with_houses_and_a_header(client, ws):
    e = start(client, ws.sup, kind="voter_list", format="pdf", language="mr",
              options={"group_by_house": True, "header": "प्रभाग १ – चाचणी", "paper": "legal", "text_size": "large"},
              columns=["serial_no", "name", "gender", "age", "house_no", "mobile", "surveyed", "address"])
    done = finished(client, ws.sup, e["id"])
    assert done["status"] == "done" and done["row_count"] == 7 and done["page_count"] >= 1, done
    r = download(client, ws.sup, e["id"])
    assert r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    assert ".pdf" in r.headers["content-disposition"]


# --- reports --------------------------------------------------------------------------------------
def test_report_exports_equal_the_reports(client, ws, owner_conn):
    progress = client.get(f"{API}/reports/survey-progress", headers=ws.boss).json()
    e = start(client, ws.boss, kind="report")   # survey progress by default
    assert finished(client, ws.boss, e["id"])["status"] == "done"
    rows = sheet_rows(download(client, ws.boss, e["id"]).content, "Village Panchayat")
    assert [r[2:4] for r in rows[:-1]] == [(a["total"], a["done"]) for a in progress["by_area"]]
    assert rows[-1][:4] == ("Total", None, progress["total"], progress["surveyed"])

    demo = client.get(f"{API}/reports/demographics", headers=ws.sup, params={"booth_id": str(ws.booths[1])}).json()
    e = start(client, ws.sup, kind="report", filter={"booth_id": str(ws.booths[1])}, options={"report": "demographics"})
    finished(client, ws.sup, e["id"])
    rows = sheet_rows(download(client, ws.sup, e["id"]).content, "Age")
    assert rows[-1] == ("Total", demo["male"], demo["female"], demo["other"], demo["total"])

    e = start(client, ws.sup, kind="report", options={"report": "colour_tags"}, format="pdf")
    assert finished(client, ws.sup, e["id"])["status"] == "done"


def test_turnout_export(client, ws):
    r = client.post(f"{API}/turnout/marks", headers=ws.boss, json={
        "id": str(uuid.uuid4()), "voter_ids": [str(ws.v["EXP1000001"])], "marked_at": "2026-11-10T03:45:00Z"})
    assert r.status_code == 200, r.text
    e = start(client, ws.boss, kind="turnout")
    finished(client, ws.boss, e["id"])
    data = download(client, ws.boss, e["id"]).content
    assert sheet_rows(data, "Village Panchayat")[-1] == ("Total", None, 8, 1, 12.5)
    assert sheet_rows(data, "Hour") == [("09:00-10:00", 1, 1)]
    pdf = start(client, ws.boss, kind="turnout", format="pdf", language="hi")
    assert finished(client, ws.boss, pdf["id"])["status"] == "done"


# --- checks at the start ---------------------------------------------------------------------------
@pytest.mark.parametrize("body, where", [
    ({"kind": "voter_list", "filter": {"colour": "x"}}, "filter.colour"),
    ({"kind": "voter_list", "filter": {"age_min": -1}}, "filter.age_min"),
    ({"kind": "voter_list", "filter": {"removed": True}}, "filter.removed"),
    ({"kind": "voter_list", "columns": ["name", "password"]}, "columns"),
    ({"kind": "voter_list", "columns": ["name", "name"]}, "columns"),
    ({"kind": "voter_list", "options": {"colour": True}}, "options.colour"),
    ({"kind": "voter_list", "options": {"paper": "a3"}}, "options.paper"),
    ({"kind": "voter_list", "options": {"report": "demographics"}}, "options.report"),
    ({"kind": "report", "columns": ["name"]}, "columns"),
    ({"kind": "report", "filter": {"gender": "F"}}, "filter.gender"),
    ({"kind": "report", "filter": {"booth_id": str(uuid.uuid4())}}, "filter.booth_id"),
    ({"kind": "turnout", "options": {"report": "survey_progress"}}, "options.report"),
    ({"kind": "voter_list", "filter": {"q": "a b c d e f"}}, "q"),
])
def test_bad_requests_are_422(client, ws, body, where):
    err = start(client, ws.sup, 422, **body)["error"]
    assert err["code"] == "validation_error" and where in err["message"], err


def test_an_area_outside_is_404_and_nothing_is_queued(client, ws, owner_conn):
    b3 = str(ws.b["b3"][1])
    for body in ({"kind": "voter_list", "filter": {"booth_id": b3}}, {"kind": "report", "filter": {"ward_id": str(ws.ward2)}},
                 {"kind": "report", "filter": {"booth_id": b3}, "options": {"report": "demographics"}}):
        assert start(client, ws.sup, 404, **body)["error"]["code"] == "not_found"
    assert owner_conn.execute("SELECT count(*) FROM app.exports WHERE tenant_id = %s", (ws.tenant,)).fetchone()[0] == 0


def test_stored_request_is_normalised(client, ws, owner_conn):
    e = start(client, ws.sup, kind="mobile_list", filter={"gender": "F", "age_max": None})
    row = owner_conn.execute("SELECT filter, columns, options, language::text FROM app.exports WHERE id = %s",
                             (e["id"],)).fetchone()
    assert row == ({"gender": "F", "has_mobile": True}, ["part_no", "serial_no", "name", "age", "house_no", "mobile"],
                   {"paper": "a4", "text_size": "normal", "group_by_house": False}, "en")


# --- who sees an export ----------------------------------------------------------------------------
def test_an_export_is_seen_by_its_user_their_admin_and_a_super_admin(client, ws):
    e = start(client, ws.sup2, kind="voter_list")
    finished(client, ws.sup2, e["id"])
    for h in (ws.sup2, ws.admin, ws.boss):
        assert client.get(f"{API}/exports/{e['id']}", headers=h).status_code == 200
        download(client, h, e["id"])
    assert client.get(f"{API}/exports/{e['id']}", headers=ws.sup).status_code == 404
    download(client, ws.sup, e["id"], status=404)


def test_download_before_done_is_409(client, ws):
    e = start(client, ws.sup, kind="voter_list")
    assert download(client, ws.sup, e["id"], status=409).json()["error"]["code"] == "export_not_ready"


# --- jobs that fail --------------------------------------------------------------------------------
def test_area_taken_away_before_the_job_runs_fails_it(client, ws, owner_conn):
    e = start(client, ws.sup2, kind="voter_list", filter={"booth_id": str(ws.b["b3"][1])})
    owner_conn.execute("DELETE FROM app.user_area_assignments WHERE user_id = %s", (ws.users["sup2"],))
    done = finished(client, ws.sup2, e["id"])
    assert done["status"] == "failed" and "no longer in your area" in done["error"], done
    assert download(client, ws.sup2, e["id"], status=409).json()["error"]["code"] == "export_not_ready"


def test_switched_off_user_fails_the_job(client, ws, owner_conn):
    e = start(client, ws.sup, kind="voter_list")
    owner_conn.execute("UPDATE app.users SET is_active = false WHERE id = %s", (ws.users["sup1"],))
    run_jobs()
    row = owner_conn.execute("SELECT status::text, error, file_id FROM app.exports WHERE id = %s", (e["id"],)).fetchone()
    assert row[0] == "failed" and "switched off" in row[1] and row[2] is None


def test_too_many_voters_fails_with_a_plain_message(client, ws, monkeypatch):
    monkeypatch.setattr(export_jobs, "MAX_ROWS", 3)
    e = start(client, ws.sup, kind="voter_list")
    done = finished(client, ws.sup, e["id"])
    assert done["status"] == "failed" and "More than 3 voters" in done["error"]
