"""Matching Engine, roll import (10.2): POST/GET /rolls/imports, GET .../{id}, .../rows, and the
worker job that reads and matches the file (app/roll_match.py). Fake voters only.
Generic rules (403 for admins on upload, other workspace / constituency 404): test_endpoint_rules.py."""

from __future__ import annotations

import csv
import io
import uuid

import openpyxl
import pytest

from app import roll_match, worker
from conftest import bearer, login

API = "/api/v1"
HEADER = ["id", "part_no", "serial_no", "epic_no", "full_name", "surname", "relative_name", "relation_type",
          "house_no", "age", "gender", "section_name", "is_deleted", "is_supplement_addition"]

# On record, part 1 (booth 1 of the test workspace): fake people.
VOTERS = [  # serial, EPIC, first, last, gender, age, relative
    (1, "TST1000001", "Asha", "Naik", "F", 30, "Ramesh Naik"),
    (2, "TST1000002", "Prakash", "Kamat", "M", 52, "Vasant Kamat"),
    (3, "TST1000003", "Sunita", "Parab", "F", 41, "Mohan Parab"),
    (4, None, "Mahesh", "Shirodkar", "M", 36, "Dilip Shirodkar"),
]
# The new roll: one row of each kind.
ROWS = [  # part, serial, EPIC, full name, surname, relative, gender, age, deleted
    (1, 1, "TST1000001", "Asha Naik", "Naik", "Ramesh Naik", "Female", 31, "false"),        # matched
    (1, 2, "TST1000002", "Vinod Gawas", "Gawas", "Suresh Gawas", "Male", 52, "false"),       # uncertain: name
    (1, 4, "", "Mahesh Shirodkar", "Shirodkar", "Dilip Shirodkar", "Male", 37, "false"),     # uncertain: alike
    (1, 5, "TST1000099", "Kavita Desai", "Desai", "Anil Desai", "Female", 19, "false"),      # new
    (1, 6, "TST1000001", "Asha Naik", "Naik", "Ramesh Naik", "Female", 31, "false"),        # possible duplicate
    (1, 7, "TST1000077", "Nobody Known", "Known", "", "Unknown", 40, "false"),              # unreadable gender
]                                                                                           # Sunita: absent


def csv_bytes(rows=ROWS, header=HEADER) -> bytes:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(header)
    for i, (part, serial, epic, full, sur, rel, gender, age, deleted) in enumerate(rows, start=1):
        w.writerow([i, part, serial, epic, full, sur, rel, "father", f"H-{serial}", age, gender, "Ward one",
                    deleted, "false"])
    return out.getvalue().encode("utf-8")


def xlsx_bytes(rows=ROWS) -> bytes:
    book = openpyxl.Workbook()
    sheet = book.active
    for line in csv.reader(io.StringIO(csv_bytes(rows).decode())):
        sheet.append([int(c) if c.isdigit() else c for c in line])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


@pytest.fixture
def ws(make_workspace, owner_conn):
    ws = make_workspace("roll")
    for serial, epic, first, last, gender, age, rel in VOTERS:
        owner_conn.execute(
            """INSERT INTO app.voters (tenant_id, local_body_id, ward_id, booth_id, part_no, serial_no, epic_no,
                                       first_name_en, last_name_en, gender, age, relative_name_en, house_no)
               VALUES (%s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (ws.tenant, ws.local_body, ws.ward, ws.booths[0], serial, epic, first, last, gender, age, rel,
             f"H-{serial}"))
    return ws


@pytest.fixture
def boss(client, ws):
    return bearer(login(client, ws, "boss").json())


def upload(client, headers, ws, data: bytes, name="roll.csv", list_type="main", lb=None):
    return client.post(f"{API}/rolls/imports", headers=headers,
                       data={"local_body_id": str(lb or ws.local_body), "list_type": list_type,
                             "title": "Draft roll 2027", "published_on": "2026-11-10"},
                       files={"file": (name, data, "application/octet-stream")})


def run_jobs() -> None:
    while worker.run_one({roll_match.KIND: worker.HANDLERS[roll_match.KIND]}):
        pass


def all_rows(client, headers, import_id, **query) -> list[dict]:
    items, cursor = [], None
    while True:
        params = {**query, "limit": 2, **({"cursor": cursor} if cursor else {})}
        page = client.get(f"{API}/rolls/imports/{import_id}/rows", headers=headers, params=params).json()
        items += page["items"]
        cursor = page["next_cursor"]
        if not cursor:
            return items


def voter_ids(owner_conn, ws) -> dict[int, uuid.UUID]:
    return dict(owner_conn.execute("SELECT serial_no, id FROM app.voters WHERE tenant_id = %s", (ws.tenant,)).fetchall())


def roll_state(owner_conn, ws):
    return owner_conn.execute("""SELECT serial_no, epic_no, first_name_en, last_name_en, roll_status::text, updated_at
                                   FROM app.voters WHERE tenant_id = %s ORDER BY serial_no""", (ws.tenant,)).fetchall()


# --- the plan's test --------------------------------------------------------------------------
@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_a_fake_roll_gives_each_match_status(client, ws, boss, owner_conn, fmt):
    before = roll_state(owner_conn, ws)
    data, name = (csv_bytes(), "roll.csv") if fmt == "csv" else (xlsx_bytes(), "roll.xlsx")
    started = upload(client, boss, ws, data, name)
    assert started.status_code == 202, started.text
    imp = started.json()
    assert (imp["status"], imp["title"], imp["list_type"], imp["published_on"]) == \
           ("uploaded", "Draft roll 2027", "main", "2026-11-10")
    assert imp["imported_by"]["username"] == "boss" and imp["counts"]["rows"] == 0

    run_jobs()
    imp = client.get(f"{API}/rolls/imports/{imp['id']}", headers=boss).json()
    assert imp["status"] == "review" and imp["error"] is None
    assert imp["counts"] == {"matched": 1, "uncertain": 2, "possible_duplicate": 1, "new": 1, "unreadable": 1,
                             "absent_from_current_roll": 1, "rows": 6, "to_review": 4, "reviewed": 0}

    rows = all_rows(client, boss, imp["id"])
    ids = voter_ids(owner_conn, ws)
    by_no = {r["row_no"]: r for r in rows}
    assert [r["row_no"] for r in rows] == list(range(2, 9))   # file rows 2-7, then the absent voter
    got = {n: (r["match_status"], r["matched_voter_id"], r["review_status"]) for n, r in by_no.items()}
    assert got == {
        2: ("matched", str(ids[1]), "accepted"),
        3: ("uncertain", str(ids[2]), "pending"),
        4: ("uncertain", str(ids[4]), "pending"),
        5: ("new", None, "accepted"),
        6: ("possible_duplicate", str(ids[1]), "pending"),
        7: (None, None, "pending"),
        8: ("absent_from_current_roll", str(ids[3]), "accepted"),
    }
    assert by_no[2]["similarity"] == 1.0 and by_no[2]["match_notes"] is None
    assert by_no[3]["similarity"] < roll_match.NAME_SAME and "same EPIC, name differs" in by_no[3]["match_notes"]
    assert "changed: name" in by_no[3]["match_notes"]
    assert by_no[4]["match_notes"] == "no EPIC match, name alike" and by_no[4]["similarity"] == 1.0
    assert "same EPIC as row 2" in by_no[6]["match_notes"]
    assert by_no[7]["match_notes"] == "unreadable: bad_gender"
    assert (by_no[8]["serial_no"], by_no[8]["epic_no"], by_no[8]["first_name_en"]) == (3, "TST1000003", "Sunita")
    assert (by_no[5]["first_name_en"], by_no[5]["last_name_en"], by_no[5]["gender"], by_no[5]["age"]) == \
           ("Kavita", "Desai", "F", 19)

    assert roll_state(owner_conn, ws) == before   # nothing official changes before apply (10.3)


def test_rows_by_status_and_waiting_for_review(client, ws, boss):
    imp = upload(client, boss, ws, csv_bytes()).json()
    run_jobs()
    uncertain = all_rows(client, boss, imp["id"], match_status="uncertain")
    assert [r["row_no"] for r in uncertain] == [3, 4]
    pending = all_rows(client, boss, imp["id"], pending_only="true")
    assert [r["row_no"] for r in pending] == [3, 4, 6, 7]
    bad = client.get(f"{API}/rolls/imports/{imp['id']}/rows", headers=boss, params={"cursor": "nonsense"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_cursor"


def test_an_admin_reads_imports_of_own_constituency(client, ws, boss):
    imp = upload(client, boss, ws, csv_bytes()).json()
    run_jobs()
    admin = bearer(login(client, ws, "admin1").json())
    listed = client.get(f"{API}/rolls/imports", headers=admin).json()["items"]
    assert [i["id"] for i in listed] == [imp["id"]]
    assert client.get(f"{API}/rolls/imports/{imp['id']}", headers=admin).json()["counts"]["new"] == 1
    assert upload(client, admin, ws, csv_bytes()).status_code == 403


def test_list_is_newest_first_and_pages(client, ws, boss, owner_conn):
    made = []
    for _ in range(3):
        made.append(upload(client, boss, ws, csv_bytes()).json()["id"])
        run_jobs()
        # an import in review blocks the next one: mark it applied, as 10.3 will
        owner_conn.execute("UPDATE app.roll_versions SET status = 'applied' WHERE id = %s", (made[-1],))
    seen, cursor = [], None
    while True:
        page = client.get(f"{API}/rolls/imports", headers=boss,
                          params={"limit": 2, **({"cursor": cursor} if cursor else {})}).json()
        seen += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == made[::-1]


# --- the upload ---------------------------------------------------------------------------------
def test_one_open_import_per_constituency(client, ws, boss):
    assert upload(client, boss, ws, csv_bytes()).status_code == 202
    again = upload(client, boss, ws, csv_bytes())
    assert again.status_code == 409 and again.json()["error"]["code"] == "import_in_progress"


@pytest.mark.parametrize("data, code", [
    (b"%PDF-1.7 scanned roll", "unsupported_file"),
    (b"\xd0\xcf\x11\xe0 old excel", "unsupported_file"),
    (b"", "unsupported_file"),
    (b"a" * (roll_match.MAX_BYTES + 1), "file_too_large"),
])
def test_files_that_are_not_read_are_refused(client, ws, boss, owner_conn, data, code):
    got = upload(client, boss, ws, data)
    assert got.status_code == 422 and got.json()["error"]["code"] == code
    assert owner_conn.execute("SELECT count(*) FROM app.roll_versions WHERE tenant_id = %s",
                              (ws.tenant,)).fetchone()[0] == 0


def test_the_import_belongs_to_a_constituency(client, ws, boss):
    ward = upload(client, boss, ws, csv_bytes(), lb=ws.ward)
    assert ward.status_code == 422
    unknown = upload(client, boss, ws, csv_bytes(), lb=uuid.uuid4())
    assert unknown.status_code == 404


# --- the job ------------------------------------------------------------------------------------
def test_a_file_without_the_needed_columns_fails_with_a_message(client, ws, boss):
    no_gender = [h if h != "gender" else "colour" for h in HEADER]
    imp = upload(client, boss, ws, csv_bytes(header=no_gender)).json()
    run_jobs()
    got = client.get(f"{API}/rolls/imports/{imp['id']}", headers=boss).json()
    assert got["status"] == "failed" and got["error"] == "The file has no column for: gender."
    assert got["counts"]["rows"] == 0
    assert upload(client, boss, ws, csv_bytes()).status_code == 202   # a failed import is not open


def test_text_that_is_not_utf8_fails_with_a_message(client, ws, boss):
    imp = upload(client, boss, ws, "part_no,serial_no,gender,full_name\n1,1,M,Ráju\n".encode("latin-1")).json()
    run_jobs()
    got = client.get(f"{API}/rolls/imports/{imp['id']}", headers=boss).json()
    assert got["status"] == "failed" and "UTF-8" in got["error"]


def test_a_supplementary_list_leaves_nobody_absent(client, ws, boss):
    imp = upload(client, boss, ws, csv_bytes(ROWS[3:4]), list_type="supplementary").json()
    run_jobs()
    counts = client.get(f"{API}/rolls/imports/{imp['id']}", headers=boss).json()["counts"]
    assert (counts["new"], counts["absent_from_current_roll"], counts["rows"]) == (1, 0, 1)


def test_absent_only_in_the_parts_the_file_has(client, ws, boss):
    """A file of part 2 only says nothing about the voters of part 1."""
    imp = upload(client, boss, ws, csv_bytes([(2, 1, "TST2000001", "Ravi Sawant", "Sawant", "", "Male", 40,
                                               "false")])).json()
    run_jobs()
    rows = all_rows(client, boss, imp["id"])
    assert [(r["match_status"], r["match_notes"]) for r in rows] == [("new", "part not on record")]


def test_a_moved_voters_deleted_entry_needs_no_review(client, ws, boss):
    rows = [(1, 9, "TST1000003", "Sunita Parab", "Parab", "Mohan Parab", "Female", 41, "true"),
            (1, 12, "TST1000003", "Sunita Parab", "Parab", "Mohan Parab", "Female", 41, "false")]
    imp = upload(client, boss, ws, csv_bytes(rows)).json()
    run_jobs()
    got = {r["row_no"]: r for r in all_rows(client, boss, imp["id"])}
    assert (got[3]["match_status"], got[3]["review_status"]) == ("matched", "accepted")   # the live entry
    assert (got[2]["match_status"], got[2]["review_status"]) == ("possible_duplicate", "accepted")
    assert "deleted entry of a voter listed again" in got[2]["match_notes"]


def test_parsing_shows_while_the_job_runs(client, ws, boss, owner_conn):
    imp = upload(client, boss, ws, csv_bytes()).json()
    owner_conn.execute("UPDATE app.jobs SET status = 'running', locked_until = now() + interval '1 min' "
                       "WHERE ref_id = %s", (imp["id"],))
    assert client.get(f"{API}/rolls/imports/{imp['id']}", headers=boss).json()["status"] == "parsing"
    owner_conn.execute("UPDATE app.jobs SET status = 'queued', locked_until = NULL WHERE ref_id = %s", (imp["id"],))


def test_a_discarded_import_is_not_read(client, ws, boss, owner_conn):
    imp = upload(client, boss, ws, csv_bytes()).json()
    owner_conn.execute("UPDATE app.roll_versions SET status = 'discarded' WHERE id = %s", (imp["id"],))
    run_jobs()
    assert owner_conn.execute("SELECT count(*) FROM app.roll_import_rows WHERE roll_version_id = %s",
                              (imp["id"],)).fetchone()[0] == 0


# --- pieces -------------------------------------------------------------------------------------
@pytest.mark.parametrize("a, b", [("Asha Naik", "Asha Naik"), ("Naik Asha", "Nayak Asha"),
                                  ("Prakash Kamat", "Vinod Gawas"), ("Shirodkar Mahesh", "Shirodkar Mahes"),
                                  ("", "Asha")])
def test_similarity_is_pg_trgm_similarity(owner_conn, a, b):
    db = owner_conn.execute("SELECT similarity(%s, %s)", (a, b)).fetchone()[0]
    assert roll_match.similarity(a, b) == pytest.approx(db, abs=1e-6)


def test_other_header_spellings_and_delimiters():
    header, table = roll_match.read_table("Part;Sr No;EPIC;First Name;Middle Name;Last Name;Sex\n"
                                          "3;14;tst 1234567;Ganesh;Dattaram;Kerkar;M\n".encode())
    (row,) = roll_match.parse_rows(header, table)
    assert (row.error, row.part_no, row.serial_no, row.epic_no, row.first, row.middle, row.last, row.gender) == \
           (None, 3, 14, "TST1234567", "Ganesh", "Dattaram", "Kerkar", "M")


def test_two_entries_with_one_serial_in_a_part_are_unreadable():
    header, table = roll_match.read_table(b"part_no,serial_no,gender,full_name\n1,1,M,A B\n1,1,F,C D\n")
    rows = roll_match.parse_rows(header, table)
    assert [r.error for r in rows] == [None, "same_part_and_serial_as_an_earlier_row"]
