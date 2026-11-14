"""Matching Engine, part 1 (plan 10.2): read a roll file and match it to the voters on record.

The worker runs `run_import` for a job of kind "roll_import" (queued by POST /rolls/imports).
Nothing official changes here: every file row (and every voter the file leaves out) becomes a
row of app.roll_import_rows with a match status, and the import waits in "review". Apply and
the review of single rows are 10.3.

File: CSV (UTF-8; comma, semicolon or tab) or Excel .xlsx (first sheet), one header row. The
client's roll part files are the model (part_no, serial_no, epic_no, full_name, surname,
relative_name, relation_type, house_no, age, gender, section_name, is_deleted,
is_supplement_addition); a few other header spellings are accepted (ALIASES). Needed:
part_no, serial_no, gender and a name.

Match statuses (one per row):
  matched                   same EPIC as a voter of this constituency, names alike (>= NAME_SAME),
                            same gender. Accepted automatically.
  uncertain                 same EPIC but the name or gender differs, or no EPIC match and a voter of
                            the same part and gender has a name alike (>= NAME_LIKE). Waits for review.
  possible_duplicate        the file lists a voter already matched by an earlier row (same EPIC twice).
                            A deleted entry of a voter who is listed again elsewhere in the file is
                            accepted automatically (the roll prints both when someone moves).
  new                       nobody on record looks like this row. Accepted automatically.
  absent_from_current_roll  an active voter of a part that is in the file, but not in the file.
                            Never "dead" (SRS). Not made for a supplementary list, which only adds.
  (no status)               the row could not be read (match_notes "unreadable: <reason>"); waits.

Similarity is pg_trgm's (trigram sets per word), computed here so the whole match runs in
one pass in memory: about 31,000 voters per constituency.
Never put row values into messages or logs: the file is real voter data.
"""

from __future__ import annotations

import csv
import io
import json
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import Connection, text

from .routers.files import stored_path
from .worker import Job, JobFailed, register

KIND = "roll_import"
MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 100_000
NAME_SAME = 0.8
NAME_LIKE = 0.5

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_MIME = "text/csv"

ALIASES: dict[str, tuple[str, ...]] = {
    "part_no": ("part_no", "part", "part_number"),
    "serial_no": ("serial_no", "serial", "sr_no", "sl_no", "serial_number"),
    "epic_no": ("epic_no", "epic", "epic_number"),
    "full_name": ("full_name", "name", "elector_name", "voter_name"),
    "first_name": ("first_name",),
    "middle_name": ("middle_name",),
    "last_name": ("surname", "last_name"),
    "relative_name": ("relative_name", "relation_name", "father_husband_name"),
    "relation_type": ("relation_type", "relation"),
    "house_no": ("house_no", "house_number", "house"),
    "age": ("age",),
    "gender": ("gender", "sex"),
    "section_name": ("section_name",),
    "is_deleted": ("is_deleted", "deleted"),
    "is_supplement_addition": ("is_supplement_addition", "supplement"),
}
EPIC_RE = re.compile(r"^[A-Z0-9/]{6,20}$")
GENDER = {"male": "M", "m": "M", "female": "F", "f": "F", "other": "O", "o": "O", "third gender": "O",
          "transgender": "O", "tg": "O"}
RELATION = {"father": "father", "mother": "mother", "husband": "husband", "wife": "wife", "other": "other"}
YES = {"true", "1", "yes", "y"}


# --- the file ---------------------------------------------------------------------------------
def sniff(head: bytes) -> str | None:
    """'xlsx', 'csv', or None for files we do not read (PDF, old .xls, other binary)."""
    if head.startswith(b"PK\x03\x04"):
        return "xlsx"
    if head.startswith(b"%PDF") or head.startswith(b"\xd0\xcf\x11\xe0") or b"\x00" in head[:512]:
        return None
    return "csv"


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v).strip()


def read_table(data: bytes) -> tuple[list[str], list[list[str]]]:
    """Header and rows as text. JobFailed with a plain message when the file cannot be read."""
    kind = sniff(data[:1024])
    if kind is None:
        raise JobFailed("Only CSV or Excel (.xlsx) files can be read. Scanned PDFs come later.")
    if kind == "xlsx":
        import openpyxl  # only the worker needs it
        try:
            book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            lines = [[_cell(v) for v in row] for row in book.worksheets[0].iter_rows(values_only=True)]
            book.close()
        except Exception:
            raise JobFailed("The Excel file cannot be read. Save it again as .xlsx or CSV.") from None
    else:
        try:
            body = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise JobFailed("The CSV file is not UTF-8 text. Save it as \"CSV UTF-8\" or as Excel (.xlsx).") from None
        first = body.split("\n", 1)[0]
        delimiter = max((",", ";", "\t"), key=first.count)
        lines = [[c.strip() for c in row] for row in csv.reader(io.StringIO(body, newline=""), delimiter=delimiter)]
    lines = [row for row in lines if any(row)]
    if not lines:
        raise JobFailed("The file is empty.")
    if len(lines) - 1 > MAX_ROWS:
        raise JobFailed(f"The file has more than {MAX_ROWS:,} rows. Split it by part.")
    return lines[0], lines[1:]


def _key(header: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", header.strip().lower()).strip("_")


def map_columns(header: list[str]) -> dict[str, int]:
    """Our field -> column index. JobFailed naming the missing fields."""
    index = {_key(h): i for i, h in reversed(list(enumerate(header)))}
    cols = {f: index[a] for f, names in ALIASES.items() for a in reversed(names) if a in index}
    missing = [f for f in ("part_no", "serial_no", "gender") if f not in cols]
    if not ({"full_name", "first_name", "last_name"} & cols.keys()):
        missing.append("full_name (or first_name / surname)")
    if missing:
        raise JobFailed(f"The file has no column for: {', '.join(missing)}.")
    return cols


# --- one row ----------------------------------------------------------------------------------
@dataclass
class Row:
    row_no: int
    raw: dict[str, str]
    error: str | None = None
    part_no: int | None = None
    serial_no: int | None = None
    epic_no: str | None = None
    first: str | None = None
    middle: str | None = None
    last: str | None = None
    relative_name: str | None = None
    gender: str | None = None
    age: int | None = None
    house_no: str | None = None
    is_deleted: bool = False
    is_repeated: bool = False
    # the match
    status: str | None = None
    voter_id: uuid.UUID | None = None
    similarity: float | None = None
    notes: list[str] = field(default_factory=list)
    accepted: bool = False

    @property
    def full_name(self) -> str:   # same order as voters.full_name_en
        return " ".join(p for p in (self.last, self.first, self.middle) if p)


def _clean(v: str | None) -> str | None:
    v = (v or "").strip()
    return v if v and v.lower() not in ("null", "none", "-", "nan") else None


def _int(v: str | None) -> int | None:
    v = _clean(v)
    if v is None:
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def split_name(full: str | None, surname: str | None) -> tuple[str | None, str | None, str | None]:
    """'First Middle Surname' -> (first, middle, last); the surname column wins (as import_roll_parts.py)."""
    words = (full or "").split()
    last = surname or None
    if words and last and words[-1].lower() == last.lower():
        words = words[:-1]
    elif words and not last and len(words) > 1:
        last, words = words[-1], words[:-1]
    return (words[0] if words else None), (" ".join(words[1:]) or None), last


def parse_row(row_no: int, header: list[str], values: list[str], cols: dict[str, int]) -> Row:
    raw = {h: (values[i] if i < len(values) else "") for i, h in enumerate(header) if h}
    get = {f: (values[i] if i < len(values) else "") for f, i in cols.items()}
    r = Row(row_no, raw)
    r.part_no, r.serial_no = _int(get.get("part_no")), _int(get.get("serial_no"))
    r.gender = GENDER.get((get.get("gender") or "").strip().lower())
    if "first_name" in cols:
        r.first, r.middle, r.last = (_clean(get.get(f)) for f in ("first_name", "middle_name", "last_name"))
    else:
        r.first, r.middle, r.last = split_name(_clean(get.get("full_name")), _clean(get.get("last_name")))
    epic = re.sub(r"\s", "", get.get("epic_no") or "").upper()
    r.epic_no = epic if EPIC_RE.match(epic) else None
    age = _int(get.get("age"))
    r.age = age if age is not None and 18 <= age <= 125 else None
    r.house_no = _clean(get.get("house_no"))
    r.relative_name = _clean(get.get("relative_name"))
    r.is_deleted = (get.get("is_deleted") or "").strip().lower() in YES
    if r.part_no is None or r.part_no <= 0:
        r.error = "no_part_no"
    elif r.serial_no is None or r.serial_no <= 0:
        r.error = "bad_serial_no"
    elif r.gender is None:
        r.error = "bad_gender"
    elif not (r.first or r.last):
        r.error = "no_name"
    return r


def parse_rows(header: list[str], table: list[list[str]]) -> list[Row]:
    cols = map_columns(header)
    rows = [parse_row(n, header, values, cols) for n, values in enumerate(table, start=2)]
    seen: set[tuple[int, int]] = set()
    for r in rows:   # the roll never prints two entries with one serial in a part
        if r.error is None:
            key = (r.part_no, r.serial_no)
            if key in seen:
                r.error = "same_part_and_serial_as_an_earlier_row"
            seen.add(key)
    return rows


# --- similarity (pg_trgm's) ---------------------------------------------------------------------
_WORD = re.compile(r"[^\W_]+")


def trigrams(s: str | None) -> frozenset[str]:
    out: set[str] = set()
    for w in _WORD.findall((s or "").lower()):
        padded = f"  {w} "
        out.update(padded[i:i + 3] for i in range(len(padded) - 2))
    return frozenset(out)


def _sim(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similarity(a: str | None, b: str | None) -> float:
    return _sim(trigrams(a), trigrams(b))


# --- matching ------------------------------------------------------------------------------------
@dataclass
class Voter:
    id: uuid.UUID
    epic_no: str | None
    part_no: int
    serial_no: int
    first: str | None
    middle: str | None
    last: str | None
    full_name: str
    relative_name: str | None
    gender: str
    age: int | None
    house_no: str | None
    roll_status: str
    grams: frozenset[str] = frozenset()
    rel_grams: frozenset[str] = frozenset()


def _score(r: Row, rg: frozenset[str], rrel: frozenset[str], v: Voter) -> float:
    """Name likeness; the relative's name counts a third when both have one."""
    name = _sim(rg, v.grams)
    if rrel and v.rel_grams:
        return (2 * name + _sim(rrel, v.rel_grams)) / 3
    return name


def _changes(r: Row, v: Voter, name_sim: float) -> list[str]:
    out = []
    if name_sim < 1:
        out.append("name")
    if r.gender != v.gender:
        out.append("gender")
    if r.part_no != v.part_no:
        out.append("part_no")
    if r.serial_no != v.serial_no:
        out.append("serial_no")
    if (r.house_no or "").lower() != (v.house_no or "").lower():
        out.append("house_no")
    if r.age is not None and v.age is not None and abs(r.age - v.age) > 2:
        out.append("age")
    return out


def match(rows: list[Row], voters: list[Voter], list_type: str) -> list[Voter]:
    """Set the match fields of every readable row. Returns the voters to list as absent."""
    for v in voters:
        v.grams, v.rel_grams = trigrams(v.full_name), trigrams(v.relative_name)
    by_epic = {v.epic_no: v for v in voters if v.epic_no}
    taken: dict[uuid.UUID, Row] = {}
    good = [r for r in rows if r.error is None]
    live_epics = defaultdict(int)
    for r in good:
        if r.epic_no and not r.is_deleted:
            live_epics[r.epic_no] += 1
    for r in good:
        r.is_repeated = bool(r.epic_no) and live_epics[r.epic_no] > 1

    # 1. EPIC: live entries first, so a moved voter's deleted entry is the one left over
    for r in sorted((r for r in good if r.epic_no), key=lambda r: r.is_deleted):
        v = by_epic.get(r.epic_no)
        if v is None:
            continue
        if v.id in taken:
            r.status, r.voter_id = "possible_duplicate", v.id
            r.notes.append(f"same EPIC as row {taken[v.id].row_no}")
            if r.is_deleted and not taken[v.id].is_deleted:
                r.accepted = True
                r.notes.append("deleted entry of a voter listed again")
            continue
        taken[v.id] = r
        name_sim = _sim(trigrams(r.full_name), v.grams)
        r.voter_id, r.similarity = v.id, round(name_sim, 3)
        changed = _changes(r, v, name_sim)
        if name_sim >= NAME_SAME and r.gender == v.gender:
            r.status, r.accepted = "matched", True
        else:
            r.status = "uncertain"
            r.notes.append("same EPIC, " + ("name differs" if name_sim < NAME_SAME else "gender differs"))
        if changed:
            r.notes.append("changed: " + ", ".join(changed))
        if v.roll_status != "active" and not r.is_deleted:
            r.notes.append("back in the roll")

    # 2. No EPIC match: the most alike voter of the same part and gender, best pairs first.
    #    Two different EPICs are two different people.
    open_rows = [r for r in good if r.status is None]
    free = defaultdict(list)
    for v in voters:
        if v.id not in taken:
            free[(v.part_no, v.gender)].append(v)
    pairs = []
    for r in open_rows:
        rg, rrel = trigrams(r.full_name), trigrams(r.relative_name)
        for v in free.get((r.part_no, r.gender), ()):
            if r.epic_no and v.epic_no:
                continue
            s = _score(r, rg, rrel, v)
            if s >= NAME_LIKE:
                age_gap = abs(r.age - v.age) if r.age is not None and v.age is not None else 99
                pairs.append((-s, age_gap, r.row_no, v.serial_no, r, v))
    pairs.sort(key=lambda p: p[:4])
    for neg_s, _, _, _, r, v in pairs:
        if r.status is not None or v.id in taken:
            continue
        taken[v.id] = r
        r.status, r.voter_id, r.similarity = "uncertain", v.id, round(-neg_s, 3)
        r.notes.append("no EPIC match, name alike" + ("" if r.epic_no is None else " (EPIC new)"))
        changed = _changes(r, v, _sim(trigrams(r.full_name), v.grams))
        if changed:
            r.notes.append("changed: " + ", ".join(changed))
    for r in open_rows:
        if r.status is None:
            r.status, r.accepted = "new", True

    # 3. Absent: active voters of the parts in the file that no row took
    if list_type == "supplementary":
        return []
    parts = {r.part_no for r in good}
    return [v for v in voters if v.roll_status == "active" and v.part_no in parts and v.id not in taken]


# --- the job --------------------------------------------------------------------------------------
def load_voters(conn: Connection, local_body_id: uuid.UUID) -> list[Voter]:
    rows = conn.execute(text("""
        SELECT id, epic_no, part_no, serial_no, first_name_en, middle_name_en, last_name_en,
               coalesce(nullif(full_name_en, ''), full_name_mr) AS full_name,
               coalesce(relative_name_en, relative_name_mr) AS relative_name,
               gender::text AS gender, age, house_no, roll_status::text AS roll_status
          FROM app.voters
         WHERE local_body_id = :lb AND deleted_at IS NULL
    """), {"lb": local_body_id}).mappings().all()
    return [Voter(id=r["id"], epic_no=r["epic_no"], part_no=r["part_no"], serial_no=r["serial_no"],
                  first=r["first_name_en"], middle=r["middle_name_en"], last=r["last_name_en"],
                  full_name=r["full_name"] or "", relative_name=r["relative_name"], gender=r["gender"],
                  age=r["age"], house_no=r["house_no"], roll_status=r["roll_status"]) for r in rows]


_INSERT = text("""
    INSERT INTO app.roll_import_rows
        (tenant_id, roll_version_id, row_no, raw, part_no, serial_no, epic_no, first_name_en, middle_name_en,
         last_name_en, gender, age, house_no, deletion_reason, is_repeated, match_status, matched_voter_id,
         similarity, match_notes, review_status)
    VALUES (app.current_tenant_id(), :rv, :row_no, CAST(:raw AS jsonb), :part_no, :serial_no, :epic_no, :first,
            :middle, :last, CAST(:gender AS app.gender), :age, :house_no, :deletion_reason, :is_repeated,
            CAST(:status AS app.match_status), :voter_id, :similarity, :notes,
            CAST(:review AS app.review_status))
""")


def import_rows(conn: Connection, roll_version_id: uuid.UUID, local_body_id: uuid.UUID, list_type: str,
                data: bytes) -> dict[str, int]:
    """Read, match and store the rows of one import. Returns its counts."""
    header, table = read_table(data)
    rows = parse_rows(header, table)
    if not any(r.error is None for r in rows):
        raise JobFailed("No voter row could be read: check part_no, serial_no, gender and the name columns.")
    known_parts = set(conn.execute(text("""
        SELECT w.number FROM app.geo_units w JOIN app.geo_units lb ON lb.id = :lb
         WHERE w.level = 'ward' AND w.path <@ lb.path AND w.number IS NOT NULL"""), {"lb": local_body_id}).scalars())
    absent = match(rows, load_voters(conn, local_body_id), list_type)

    params = []
    for r in rows:
        if r.error is not None:
            r.notes = [f"unreadable: {r.error}"]
        elif r.part_no not in known_parts:
            r.notes.append("part not on record")
        params.append({
            "rv": roll_version_id, "row_no": r.row_no, "raw": json.dumps(r.raw, ensure_ascii=False),
            "part_no": r.part_no, "serial_no": r.serial_no, "epic_no": r.epic_no, "first": r.first,
            "middle": r.middle, "last": r.last, "gender": r.gender, "age": r.age, "house_no": r.house_no,
            "deletion_reason": "other" if r.is_deleted else None, "is_repeated": r.is_repeated,
            "status": r.status, "voter_id": r.voter_id, "similarity": r.similarity,
            "notes": "; ".join(r.notes) or None, "review": "accepted" if r.accepted else "pending"})
    next_no = max((r.row_no for r in rows), default=1) + 1
    for i, v in enumerate(sorted(absent, key=lambda v: (v.part_no, v.serial_no))):
        params.append({
            "rv": roll_version_id, "row_no": next_no + i, "raw": "{}", "part_no": v.part_no,
            "serial_no": v.serial_no, "epic_no": v.epic_no, "first": v.first, "middle": v.middle, "last": v.last,
            "gender": v.gender, "age": v.age, "house_no": v.house_no, "deletion_reason": None,
            "is_repeated": False, "status": "absent_from_current_roll", "voter_id": v.id, "similarity": None,
            "notes": "not in this file", "review": "accepted"})
    if params:
        conn.execute(_INSERT, params)

    counts = {k: 0 for k in ("matched", "uncertain", "possible_duplicate", "new", "unreadable")}
    for r in rows:
        counts[r.status or "unreadable"] += 1
    counts["absent_from_current_roll"] = len(absent)
    counts["rows"] = len(rows)
    return counts


def run_import(conn: Connection, job: Job) -> None:
    rv = conn.execute(text("""
        SELECT rv.id, rv.local_body_id, rv.list_type::text AS list_type, rv.status::text AS status, f.storage_path
          FROM app.roll_versions rv JOIN app.files f ON f.id = rv.source_file_id
         WHERE rv.id = :id FOR UPDATE OF rv"""), {"id": job.ref_id}).mappings().first()
    if rv is None or rv["status"] != "uploaded":   # discarded while queued, or done already
        return
    try:
        data = stored_path(rv["storage_path"]).read_bytes()
    except FileNotFoundError:
        raise JobFailed("The uploaded file is missing on the server. Upload it again.") from None
    counts = import_rows(conn, rv["id"], rv["local_body_id"], rv["list_type"], data)
    conn.execute(text("""UPDATE app.roll_versions SET status = 'review', stats = CAST(:stats AS jsonb)
                          WHERE id = :id"""), {"id": rv["id"], "stats": json.dumps(counts)})


def fail_import(conn: Connection, job: Job, message: str) -> None:
    conn.execute(text("""UPDATE app.roll_versions SET status = 'failed'
                          WHERE id = :id AND status IN ('uploaded', 'parsing')"""), {"id": job.ref_id})


register(KIND, run_import, fail_import)
