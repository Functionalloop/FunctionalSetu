"""Mobile number sheets (plan 10.5): match a sheet of names and mobiles to voters and store the numbers.

The sheet (CSV or .xlsx, read like a roll file) needs a mobile column and a name or EPIC column;
part, house number and address are used when present. A job (kind "mobile_import") matches it against
the live voters of the uploader's area: their constituency (admin) or the whole workspace (super admin).

Per row:
  skipped       the mobile is not a 10-digit Indian mobile (+91 / 0 in front are dropped)
  matched       EPIC found; or exactly one voter's name is alike (similarity >= NAME_SAME, with the
                sheet's part when given; the house number breaks a tie). The number is stored at once:
                into mobile_1 if empty, else mobile_2 if empty; a number the voter has already is left.
  needs_review  some voters are alike but none for sure (up to 5 candidates, best first), or the voter
                for sure already has two other numbers (a person decides: resolve replaces mobile_2)
  not_found     nobody alike
Storing a number goes through voter_surveys (a row is made if the voter has none, not "surveyed"):
the audit row shows who uploaded the sheet, the survey version rises and phones pull the number.
Numbers are decided in memory and written in two statements; a survey a phone changed meanwhile is
not overwritten (that voter gets the number one by one, if there is room). Real roll: 2,000 rows ~4 s.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from .roll_match import NAME_LIKE, NAME_SAME, _clean, _int, _key, read_table, trigrams, _sim
from .routers.files import stored_path
from .worker import Job, JobFailed, register

KIND = "mobile_import"
MAX_CANDIDATES = 5
MOBILE_RE = re.compile(r"^[6-9][0-9]{9}$")
_WORD = re.compile(r"[^\W_]+")
ALIASES: dict[str, tuple[str, ...]] = {
    "mobile": ("mobile", "mobile_no", "mobile_number", "phone", "phone_no", "phone_number", "contact",
               "contact_no", "whatsapp", "whatsapp_no"),
    "name": ("name", "full_name", "voter_name", "elector_name"),
    "epic_no": ("epic_no", "epic", "epic_number"),
    "part_no": ("part_no", "part", "part_number"),
    "house_no": ("house_no", "house_number", "house"),
    "address": ("address", "address_text", "area", "village"),
}


def normalise_mobile(raw: str | None) -> str | None:
    d = re.sub(r"\D", "", raw or "")
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    elif len(d) == 11 and d.startswith("0"):
        d = d[1:]
    return d if MOBILE_RE.match(d) else None


def _house(v: str | None) -> str:
    return re.sub(r"\s+", "", (v or "").lower())


@dataclass
class SheetRow:
    row_no: int
    mobile_raw: str
    mobile: str | None
    name: str | None = None
    epic_no: str | None = None
    part_no: int | None = None
    house_no: str | None = None
    address: str | None = None
    status: str = "not_found"
    voter_id: uuid.UUID | None = None
    candidates: list[uuid.UUID] = field(default_factory=list)


def read_sheet(data: bytes) -> list[SheetRow]:
    header, table = read_table(data)
    index = {_key(h): i for i, h in reversed(list(enumerate(header)))}
    cols = {f: index[a] for f, names in ALIASES.items() for a in reversed(names) if a in index}
    if "mobile" not in cols:
        raise JobFailed("The sheet has no mobile number column (mobile, phone or contact).")
    if not ({"name", "epic_no"} & cols.keys()):
        raise JobFailed("The sheet needs a name or an EPIC column.")

    def cell(values: list[str], f: str) -> str | None:
        i = cols.get(f)
        return _clean(values[i]) if i is not None and i < len(values) else None

    rows = []
    for n, values in enumerate(table, start=1):
        raw = (cell(values, "mobile") or "")[:30]
        epic = (cell(values, "epic_no") or "").upper().replace(" ", "") or None
        rows.append(SheetRow(row_no=n, mobile_raw=raw, mobile=normalise_mobile(raw), name=cell(values, "name"),
                             epic_no=epic, part_no=_int(cell(values, "part_no")), house_no=cell(values, "house_no"),
                             address=cell(values, "address")))
    if not any(r.mobile for r in rows):
        raise JobFailed("No row has a 10-digit mobile number.")
    return rows


@dataclass
class Voter:
    id: uuid.UUID
    epic_no: str | None
    part_no: int
    house_no: str | None
    name: str
    mobile_1: str | None
    mobile_2: str | None
    has_survey: bool
    grams: frozenset[str] = frozenset()
    old: tuple[str | None, str | None] = (None, None)   # the numbers as loaded


def load_voters(conn: Connection, local_body_id: uuid.UUID | None) -> list[Voter]:
    """Live voters of the constituency (None: of every active constituency of the workspace)."""
    rows = conn.execute(text("""
        SELECT v.id, v.epic_no, v.part_no, v.house_no,
               coalesce(nullif(v.full_name_en, ''), v.full_name_mr, '') AS name, s.mobile_1, s.mobile_2,
               s.voter_id IS NOT NULL AS has_survey
          FROM app.voters v
          JOIN app.geo_units g ON g.tenant_id = v.tenant_id AND g.id = v.local_body_id AND g.is_active
          LEFT JOIN app.voter_surveys s ON s.tenant_id = v.tenant_id AND s.voter_id = v.id
         WHERE v.deleted_at IS NULL AND (CAST(:lb AS uuid) IS NULL OR v.local_body_id = :lb)"""),
                        {"lb": local_body_id}).mappings().all()
    return [Voter(**r, grams=trigrams(r["name"]), old=(r["mobile_1"], r["mobile_2"])) for r in rows]


class Matcher:
    def __init__(self, voters: list[Voter]):
        self.voters = voters
        self.by_epic = {v.epic_no: v for v in voters if v.epic_no}
        self.by_word: dict[str, list[int]] = {}   # word -> positions in `voters` (ints hash fast)
        for i, v in enumerate(voters):
            for w in set(_WORD.findall(v.name.lower())):
                self.by_word.setdefault(w, []).append(i)

    def find(self, r: SheetRow) -> tuple[Voter | None, list[Voter]]:
        """(the voter for sure or None, candidates best first)."""
        if r.epic_no and r.epic_no in self.by_epic:
            return self.by_epic[r.epic_no], []
        words = set(_WORD.findall((r.name or "").lower()))
        if not words:
            return None, []
        hits: Counter[int] = Counter()
        for w in words:
            hits.update(self.by_word.get(w, ()))
        need = min(2, len(words))   # first name and surname both, when the sheet has both
        pool = [self.voters[i] for i, n in hits.items() if n >= need] or [self.voters[i] for i in hits]
        if r.part_no is not None:
            pool = [v for v in pool if v.part_no == r.part_no]
        rg = trigrams(r.name)
        scored = sorted(((s, v) for v in pool if (s := _sim(rg, v.grams)) >= NAME_LIKE),
                        key=lambda sv: (-sv[0], sv[1].part_no, str(sv[1].id)))
        strong = [v for s, v in scored if s >= NAME_SAME]
        if r.house_no and len(strong) > 1:
            strong = [v for v in strong if _house(v.house_no) == _house(r.house_no)] or strong
        sure = strong[0] if len(strong) == 1 else None
        return sure, [v for _, v in scored[:MAX_CANDIDATES]]


def store_mobile(conn: Connection, user_id: uuid.UUID | None, voter_id: uuid.UUID, mobile: str,
                 replace: bool = False) -> str:
    """Put the number on the voter's survey. Returns 'stored', 'has_it' or 'full' (two other numbers;
    with replace=True mobile_2 is replaced instead)."""
    cur = conn.execute(text("SELECT mobile_1, mobile_2 FROM app.voter_surveys WHERE voter_id = :v FOR UPDATE"),
                       {"v": voter_id}).first()
    if cur is None:
        conn.execute(text("""INSERT INTO app.voter_surveys (tenant_id, voter_id, mobile_1, updated_by)
                             VALUES (app.current_tenant_id(), :v, :m, :u)"""), {"v": voter_id, "m": mobile, "u": user_id})
        return "stored"
    if mobile in (cur.mobile_1, cur.mobile_2):
        return "has_it"
    col = "mobile_1" if cur.mobile_1 is None else "mobile_2" if cur.mobile_2 is None or replace else None
    if col is None:
        return "full"
    conn.execute(text(f"UPDATE app.voter_surveys SET {col} = :m, updated_by = :u, updated_device_id = NULL "
                      "WHERE voter_id = :v"), {"v": voter_id, "m": mobile, "u": user_id})
    return "stored"


def match_rows(conn: Connection, user_id: uuid.UUID | None, rows: list[SheetRow], voters: list[Voter]) -> None:
    """Set each row's status, store the sure numbers (decided in memory, written in one go)."""
    matcher = Matcher(voters)
    changed: dict[uuid.UUID, Voter] = {}
    for r in rows:
        if r.mobile is None:
            r.status = "skipped"
            continue
        sure, alike = matcher.find(r)
        r.candidates = [v.id for v in alike]
        if sure is None:
            r.status = "needs_review" if alike else "not_found"
            continue
        if r.mobile not in (sure.mobile_1, sure.mobile_2):
            if sure.mobile_1 is None:
                sure.mobile_1 = r.mobile
            elif sure.mobile_2 is None:
                sure.mobile_2 = r.mobile
            else:
                r.status, r.candidates = "needs_review", [sure.id]
                continue
            changed[sure.id] = sure
        r.status, r.voter_id = "matched", sure.id
    _write(conn, user_id, list(changed.values()))


def _write(conn: Connection, user_id: uuid.UUID | None, voters: list[Voter]) -> None:
    """New numbers of many voters in two statements. A survey a phone changed since the voters were
    loaded is not overwritten: those voters go one by one through store_mobile."""
    new = [v for v in voters if not v.has_survey]
    old = [v for v in voters if v.has_survey]
    done: set[uuid.UUID] = set()
    if new:
        done |= set(conn.execute(text("""
            INSERT INTO app.voter_surveys (tenant_id, voter_id, mobile_1, mobile_2, updated_by)
            SELECT app.current_tenant_id(), v, m1, m2, :u
              FROM unnest(CAST(:v AS uuid[]), CAST(:m1 AS text[]), CAST(:m2 AS text[])) AS x(v, m1, m2)
            ON CONFLICT (voter_id) DO NOTHING RETURNING voter_id"""),
            {"u": user_id, "v": [v.id for v in new], "m1": [v.mobile_1 for v in new],
             "m2": [v.mobile_2 for v in new]}).scalars())
    if old:
        done |= set(conn.execute(text("""
            UPDATE app.voter_surveys s SET mobile_1 = x.m1, mobile_2 = x.m2, updated_by = :u, updated_device_id = NULL
              FROM unnest(CAST(:v AS uuid[]), CAST(:m1 AS text[]), CAST(:m2 AS text[]),
                          CAST(:o1 AS text[]), CAST(:o2 AS text[])) AS x(v, m1, m2, o1, o2)
             WHERE s.voter_id = x.v AND s.mobile_1 IS NOT DISTINCT FROM x.o1 AND s.mobile_2 IS NOT DISTINCT FROM x.o2
            RETURNING s.voter_id"""),
            {"u": user_id, "v": [v.id for v in old], "m1": [v.mobile_1 for v in old],
             "m2": [v.mobile_2 for v in old], "o1": [v.old[0] for v in old], "o2": [v.old[1] for v in old]}).scalars())
    for v in voters:
        if v.id not in done:   # changed meanwhile: add the sheet's numbers to what is there now, if room
            for m in (v.mobile_1, v.mobile_2):
                if m and m not in v.old:
                    store_mobile(conn, user_id, v.id, m)


_INSERT = text("""
    INSERT INTO app.mobile_import_rows (tenant_id, batch_id, row_no, name, mobile, address_text, status,
                                        matched_voter_id, candidate_voter_ids)
    VALUES (app.current_tenant_id(), :batch, :row_no, :name, :mobile, :address, CAST(:status AS app.mobile_match_status),
            :voter_id, CAST(:candidates AS uuid[]))""")


def recount(conn: Connection, batch_id: uuid.UUID) -> None:
    conn.execute(text("""
        UPDATE app.mobile_import_batches b
           SET matched_count = c.matched, review_count = c.review, not_found_count = c.not_found
          FROM (SELECT count(*) FILTER (WHERE status = 'matched') AS matched,
                       count(*) FILTER (WHERE status = 'needs_review') AS review,
                       count(*) FILTER (WHERE status = 'not_found') AS not_found
                  FROM app.mobile_import_rows WHERE batch_id = :b) c
         WHERE b.id = :b"""), {"b": batch_id})


def import_sheet(conn: Connection, batch_id: uuid.UUID, user_id: uuid.UUID | None, local_body_id: uuid.UUID | None,
                 data: bytes) -> None:
    rows = read_sheet(data)
    match_rows(conn, user_id, rows, load_voters(conn, local_body_id))
    conn.execute(_INSERT, [{"batch": batch_id, "row_no": r.row_no, "name": r.name, "mobile": r.mobile or r.mobile_raw,
                            "address": r.address, "status": r.status, "voter_id": r.voter_id,
                            "candidates": [str(c) for c in r.candidates]} for r in rows])
    recount(conn, batch_id)


def run_import(conn: Connection, job: Job) -> None:
    b = conn.execute(text("""
        SELECT b.id, b.status::text AS status, f.storage_path FROM app.mobile_import_batches b
          JOIN app.files f ON f.id = b.file_id WHERE b.id = :id FOR UPDATE OF b"""), {"id": job.ref_id}).mappings().first()
    if b is None or b["status"] != "queued":
        return
    try:
        data = stored_path(b["storage_path"]).read_bytes()
    except FileNotFoundError:
        raise JobFailed("The uploaded file is missing on the server. Upload it again.") from None
    lb = job.payload.get("local_body_id")
    import_sheet(conn, b["id"], job.created_by, uuid.UUID(lb) if lb else None, data)
    conn.execute(text("UPDATE app.mobile_import_batches SET status = 'done', finished_at = now() WHERE id = :id"),
                 {"id": b["id"]})


def fail_import(conn: Connection, job: Job, message: str) -> None:
    conn.execute(text("""UPDATE app.mobile_import_batches SET status = 'failed', error = :e, finished_at = now()
                          WHERE id = :id AND status IN ('queued', 'running')"""), {"id": job.ref_id, "e": message})


register(KIND, run_import, fail_import)
