"""Import the old VoterApp data (VoterappDB) into JANSETU.

    python scripts/import_legacy.py --voters PATH [--dry-run] [--tenant-code naik]
                                    [--errors PATH] [--encoding utf-8-sig]

Reads:
  * docs/legacy/assembly_parts.csv, cast_master.csv, profession_master.csv,
    color.csv, labels.csv   (master lists, in the repo)
  * --voters: the old app's voters table as CSV (kept OUTSIDE the repo)

Writes, in ONE transaction as jansetu_owner (--dry-run rolls it back):
  * workspace "Naik Management Solutions" with default settings
  * constituency (local body), wards, booths and sections
  * castes, professions, colour tags, ui labels, custom-field labels
  * official roll fields  -> app.voters
  * campaign fields       -> app.voter_surveys, app.families
  * one roll_versions row and roll_part_versions per ward

Safe to run twice: a voter that already exists (same EPIC, or same booth +
serial no.) is skipped; areas and masters are looked up before being created.

PRIVACY: this script prints counts only. It never prints names, mobiles or any
row content, not even in error messages. Rows that fail, and rows where a field
had to be dropped, go to --errors (default ../jansetu-private/import_errors.csv,
outside the repo) for you to review.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import subprocess
import uuid
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
LEGACY = ROOT / "docs" / "legacy"
DEFAULT_ERRORS = ROOT.parent / "jansetu-private" / "import_errors.csv"
LOCK_ID = 7_406_002  # pg_advisory_xact_lock key: one import at a time

TENANT_NAME_EN = "Naik Management Solutions"
TENANT_NAME_MR = "नाईक मॅनेजमेंट सोल्युशन्स"
ROLL_TITLE = "Legacy VoterApp import"

REQUIRED_COLUMNS = [
    "id", "assembly_no", "part_no", "srno", "boothid", "draft_srno",
    "l_last_name", "l_first_name", "l_middle_name", "e_last_name", "e_first_name", "e_middle_name",
    "sex", "age", "vcardid", "house_no", "l_address", "e_address", "booth_no",
    "l_boothaddress", "e_boothaddress", "l_newaddress", "e_newaddress", "repeated", "repeated_no",
    "dead", "addresschange", "familyid", "important", "color", "dob", "mobile_no1", "mobile_no2",
    "emailid", "l_cast_name", "e_cast_name", "l_profession_name", "e_profession_name",
    "demands", "society", "flat_no", "extra_info1", "extra_info2", "extra_info3", "extra_info4",
    "extra_info5", "extra_check1", "extra_check2", "assembly_mapping",
]

# Legacy label key -> app.custom_field_key
CUSTOM_FIELDS = {
    "extra_check1": "extra_check_1", "extra_check2": "extra_check_2",
    "extra_info1": "extra_info_1", "extra_info2": "extra_info_2", "extra_info3": "extra_info_3",
    "extra_info4": "extra_info_4", "extra_info5": "extra_info_5",
}
COLOR_HEX = {"green": "#2E8B57", "red": "#C8382E", "yellow": "#E0B000", "white": "#FFFFFF"}

GENDER = {
    "m": "M", "male": "M", "पु": "M", "पु.": "M", "पुरुष": "M", "पू": "M",
    "f": "F", "female": "F", "स्त्री": "F", "स्री": "F", "स्त्रि": "F", "स्त्री.": "F", "म": "F", "महिला": "F",
    "o": "O", "t": "O", "tg": "O", "other": "O", "इतर": "O", "तृतीयपंथी": "O",
}
TRUE = {"1", "y", "yes", "true", "t", "होय", "हो", "dead", "मृत", "✓"}
FALSE = {"", "0", "n", "no", "false", "f", "नाही", "null", "none"}

EPIC_RE = re.compile(r"^[A-Z0-9/]{6,20}$")
MOBILE_RE = re.compile(r"^[6-9][0-9]{9}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAPPING_RE = re.compile(r"^[0-9]+/[0-9]+/[0-9]+$")
LABEL_KEY_RE = re.compile(r"^[a-z0-9_.]{2,80}$")
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S",
                "%d/%m/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


class RowError(Exception):
    """A row that cannot be imported. The message is a fixed reason code, never row content."""


# --------------------------------------------------------------------------- parsing helpers
def clean(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v if v and v.lower() not in ("null", "none", "-") else None


def to_int(v: str | None) -> int | None:
    v = clean(v)
    if v is None:
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def to_date(v: str | None) -> date | None:
    v = clean(v)
    if v is None:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def to_mobile(v: str | None) -> tuple[str | None, bool]:
    """Returns (10-digit mobile or None, was_invalid)."""
    v = clean(v)
    if v is None:
        return None, False
    digits = re.sub(r"\D", "", v)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if MOBILE_RE.match(digits) and digits != "0" * 10:
        return digits, False
    return None, True


class Flags:
    """Parses yes/no columns and counts values it does not recognise."""

    def __init__(self, warnings: Counter):
        self.warnings = warnings

    def __call__(self, v: str | None, field: str, nullable: bool = False) -> bool | None:
        raw = (v or "").strip().lower()
        if raw in TRUE:
            return True
        if raw in FALSE:
            return None if nullable and raw == "" else False
        self.warnings[f"flag_unrecognised:{field}"] += 1
        return None if nullable else False


def read_master(name: str) -> list[dict[str, str]]:
    with open(LEGACY / name, encoding="utf-8-sig", newline="") as f:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


# --------------------------------------------------------------------------- importer
class Importer:
    def __init__(self, conn: psycopg.Connection, tenant_code: str, flags_warn: Counter):
        self.conn = conn
        self.tenant_code = tenant_code
        self.created: Counter = Counter()
        self.warn = flags_warn
        self.flag = Flags(flags_warn)
        self.tenant: uuid.UUID | None = None
        self.local_body: uuid.UUID | None = None
        self.roll: uuid.UUID | None = None
        self.parts: dict[int, dict[str, str]] = {}   # part_no -> assembly_parts row
        self.assembly_no: int | None = None
        self.geo: dict[tuple, uuid.UUID] = {}         # (parent_id, level, code) -> id
        self.geo_next_sort: Counter = Counter()
        self.ward_versioned: set[uuid.UUID] = set()
        self.castes: dict[str, uuid.UUID] = {}        # lowered name (mr or en) -> id
        self.professions: dict[str, uuid.UUID] = {}
        self.colors: dict[str, uuid.UUID] = {}        # lowered code / label -> id
        self.families: dict[str, uuid.UUID] = {}      # legacy key -> id
        self.existing_epic: set[str] = set()
        self.existing_serial: set[tuple[uuid.UUID, int]] = set()
        self.custom_used: Counter = Counter()

    def x(self, query: str, params=None):
        return self.conn.execute(query, params)

    # ---- workspace, masters ------------------------------------------------
    def setup_workspace(self) -> None:
        self.ensure_tenant()
        self.setup_areas()

    def ensure_tenant(self) -> None:
        """Find or create the workspace and load its existing areas into the cache."""
        row = self.x("SELECT id FROM app.tenants WHERE code = %s", (self.tenant_code,)).fetchone()
        if row:
            self.tenant = row[0]
        else:
            self.tenant = uuid.uuid4()
            self.x("INSERT INTO app.tenants (id, code, name_en, name_mr) VALUES (%s, %s, %s, %s)",
                   (self.tenant, self.tenant_code, TENANT_NAME_EN, TENANT_NAME_MR))
            self.x("SELECT app.seed_tenant_defaults(%s)", (self.tenant,))
            self.created["workspace"] += 1

        for r in self.x("SELECT id, parent_id, level::text, code, sort_order FROM app.geo_units WHERE tenant_id = %s",
                        (self.tenant,)):
            self.geo[(r[1], r[2], r[3])] = r[0]
            self.geo_next_sort[r[1]] = max(self.geo_next_sort[r[1]], r[4] + 1)

    def setup_areas(self) -> None:
        """Local body and wards from assembly_parts.csv, plus the legacy roll version."""
        parts = read_master("assembly_parts.csv")
        assembly_nos = {to_int(p["assembly_no"]) for p in parts}
        if len(assembly_nos) != 1:
            raise SystemExit("assembly_parts.csv must describe exactly one assembly / local body.")
        self.assembly_no = assembly_nos.pop()
        self.parts = {to_int(p["part_no"]): p for p in parts}
        first = parts[0]
        self.local_body = self.geo_get_or_create(
            None, "local_body", str(self.assembly_no), None,
            name_mr=first["l_assembly_name"] or first["e_assembly_name"], name_en=first["e_assembly_name"])

        # Wards that the old app had data for; others are created when a voter needs them.
        for part_no, p in self.parts.items():
            if to_int(p["selected"]) == 1:
                self.ward(part_no)

        row = self.x("SELECT id FROM app.roll_versions WHERE tenant_id = %s AND title = %s",
                     (self.tenant, ROLL_TITLE)).fetchone()
        if row:
            self.roll = row[0]
        else:
            self.roll = uuid.uuid4()
            published = max((d for p in parts if (d := to_date(p["date_published"]))), default=None)
            self.x("""INSERT INTO app.roll_versions (id, tenant_id, local_body_id, list_type, title, published_on,
                                                    status, applied_at)
                      VALUES (%s, %s, %s, 'main', %s, %s, 'applied', now())""",
                   (self.roll, self.tenant, self.local_body, ROLL_TITLE, published))
            self.created["roll_version"] += 1

    def load_masters(self) -> None:
        for table, file, cache in (("castes", "cast_master.csv", self.castes),
                                   ("professions", "profession_master.csv", self.professions)):
            col = "cast" if table == "castes" else "profession"
            for i, r in enumerate(read_master(file), start=1):
                mr, en = r[f"l_{col}_name"] or r[f"e_{col}_name"], r[f"e_{col}_name"] or None
                if mr:
                    self.master_get_or_create(table, cache, mr, en, sort_order=i, count=False)
            for r in self.x(f"SELECT id, name_mr, name_en FROM app.{table} WHERE tenant_id = %s", (self.tenant,)):
                cache.setdefault(r[1].lower(), r[0])
                if r[2]:
                    cache.setdefault(r[2].lower(), r[0])

        for i, r in enumerate(read_master("color.csv"), start=1):
            code = r["color"].lower()
            self.x("""INSERT INTO app.color_tags (tenant_id, code, hex, label_mr, label_en, label_hi, sort_order)
                      VALUES (%s, %s, %s, %s, %s, %s, %s)
                      ON CONFLICT (tenant_id, code) DO UPDATE
                        SET label_mr = EXCLUDED.label_mr, label_en = EXCLUDED.label_en, label_hi = EXCLUDED.label_hi""",
                   (self.tenant, code, COLOR_HEX.get(code, "#9E9E9E"), r["local_description"],
                    r["english_description"], r["hindi_description"] or None, i))
        for r in self.x("SELECT id, code, label_mr, label_en FROM app.color_tags WHERE tenant_id = %s", (self.tenant,)):
            for k in (r[1], r[2], r[3]):
                self.colors.setdefault(k.lower(), r[0])

        for r in read_master("labels.csv"):
            key = r["keyy"].lower()
            if key in CUSTOM_FIELDS:
                self.x("""UPDATE app.custom_field_labels SET label_mr = %s, label_en = %s, label_hi = %s
                          WHERE tenant_id = %s AND field_key = %s""",
                       (r["local_label"] or None, r["english_label"] or None, r["hindi_label"] or None,
                        self.tenant, CUSTOM_FIELDS[key]))
            if not LABEL_KEY_RE.match(key) or not r["local_label"] or not r["english_label"]:
                self.created["ui_labels_skipped_bad_key"] += 1
                continue
            cur = self.x("""INSERT INTO app.ui_labels (key, label_mr, label_hi, label_en) VALUES (%s, %s, %s, %s)
                            ON CONFLICT (key) DO NOTHING""",
                         (key, r["local_label"], r["hindi_label"] or None, r["english_label"]))
            self.created["ui_labels"] += cur.rowcount

    def master_get_or_create(self, table: str, cache: dict, mr: str, en: str | None,
                             sort_order: int = 1000, count: bool = True) -> uuid.UUID:
        hit = cache.get(mr.lower()) or (cache.get(en.lower()) if en else None)
        if hit:
            return hit
        row = self.x(f"""INSERT INTO app.{table} (tenant_id, name_mr, name_en, sort_order) VALUES (%s, %s, %s, %s)
                         ON CONFLICT (tenant_id, name_mr) DO UPDATE SET name_mr = EXCLUDED.name_mr
                         RETURNING id, (xmax = 0)""", (self.tenant, mr, en, sort_order)).fetchone()
        cache[mr.lower()] = row[0]
        if en:
            cache.setdefault(en.lower(), row[0])
        if row[1]:
            self.created[f"{table}{'_added_from_voter_file' if count else ''}"] += 1
        return row[0]

    def load_existing_voters(self) -> None:
        for epic, booth, serial in self.x(
                "SELECT epic_no, booth_id, serial_no FROM app.voters WHERE tenant_id = %s", (self.tenant,)):
            if epic:
                self.existing_epic.add(epic)
            self.existing_serial.add((booth, serial))
        for key, fid in self.x("""SELECT legacy_family_key, id FROM app.families
                                  WHERE tenant_id = %s AND legacy_family_key IS NOT NULL""", (self.tenant,)):
            self.families[key] = fid

    # ---- areas -------------------------------------------------------------
    def geo_get_or_create(self, parent, level: str, code: str, number: int | None, *, name_mr: str,
                          name_en: str | None = None, address_mr: str | None = None,
                          address_en: str | None = None) -> uuid.UUID:
        key = (parent, level, code)
        if key in self.geo:
            return self.geo[key]
        gid = uuid.uuid4()
        sort = self.geo_next_sort[parent] or 1
        with self.conn.transaction():
            self.x("""INSERT INTO app.geo_units (id, tenant_id, parent_id, level, code, number, name_mr, name_en,
                                                 address_mr, address_en, sort_order)
                      VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                   (gid, self.tenant, parent, level, code, number, name_mr, name_en, address_mr, address_en, sort))
        self.geo[key] = gid
        self.geo_next_sort[parent] = sort + 1
        self.created[level] += 1
        return gid

    def ward(self, part_no: int) -> uuid.UUID:
        p = self.parts.get(part_no)
        if p is None:
            raise RowError("unknown_ward_part_no")
        wid = self.geo_get_or_create(self.local_body, "ward", str(part_no), part_no,
                                     name_mr=p["l_village"] or p["e_village"] or f"प्रभाग-{part_no}",
                                     name_en=p["e_village"] or None)
        if wid not in self.ward_versioned:
            self.ward_versioned.add(wid)
            dv = to_int(p["dataversion"]) or 0
            self.x("""INSERT INTO app.roll_part_versions (tenant_id, ward_id, data_version, photo_version,
                                                         published_on, roll_version_id)
                      VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                   (self.tenant, wid, dv if dv > 0 else 1, max(to_int(p["photoversion"]) or 0, 0),
                    to_date(p["date_published"]), self.roll))
        return wid

    def booth(self, ward_id: uuid.UUID, row: dict) -> uuid.UUID:
        boothid, booth_no = to_int(row["boothid"]), to_int(row["booth_no"])
        code = boothid if boothid is not None else booth_no
        if code is None:
            raise RowError("no_booth")
        addr_mr, addr_en = clean(row["l_boothaddress"]), clean(row["e_boothaddress"])
        return self.geo_get_or_create(ward_id, "booth", str(code), booth_no,
                                      name_mr=addr_mr or addr_en or f"बूथ {code}", name_en=addr_en,
                                      address_mr=addr_mr, address_en=addr_en)

    def section(self, booth_id: uuid.UUID, row: dict) -> uuid.UUID | None:
        mr, en = clean(row["l_address"]), clean(row["e_address"])
        if not (mr or en):
            return None
        code = "s" + hashlib.sha1(f"{mr or ''}|{en or ''}".encode()).hexdigest()[:12]
        return self.geo_get_or_create(booth_id, "section", code, None, name_mr=mr or en, name_en=en)

    def family(self, key: str, ward_id: uuid.UUID, booth_id: uuid.UUID, house_no: str | None) -> uuid.UUID:
        if key in self.families:
            return self.families[key]
        fid = uuid.uuid4()
        with self.conn.transaction():
            self.x("""INSERT INTO app.families (id, tenant_id, ward_id, booth_id, house_no, source, legacy_family_key)
                      VALUES (%s, %s, %s, %s, %s, 'roll_import', %s)""",
                   (fid, self.tenant, ward_id, booth_id, house_no, key))
        self.families[key] = fid
        self.created["families"] += 1
        return fid

    # ---- one voter ----------------------------------------------------------
    def build(self, row: dict) -> tuple[dict, dict | None, list[str]]:
        """Validate one CSV row. Returns (voter, survey or None, dropped-field reasons). Raises RowError."""
        dropped: list[str] = []

        def drop(reason: str) -> None:
            dropped.append(reason)
            return None

        assembly = to_int(row["assembly_no"])
        if assembly is not None and assembly != self.assembly_no:
            raise RowError("unknown_assembly_no")
        part_no = to_int(row["part_no"])
        if part_no is None:
            raise RowError("no_part_no")
        serial = to_int(row["srno"])
        if serial is None or serial <= 0:
            raise RowError("bad_serial_no")
        gender = GENDER.get((row["sex"] or "").strip().lower())
        if gender is None:
            raise RowError("bad_gender")
        names = {k: clean(row[f"{p}_{n}_name"]) for p, s in (("l", "mr"), ("e", "en"))
                 for n in ("first", "middle", "last") for k in [f"{n}_name_{s}"]}
        if not any(names[k] for k in ("first_name_mr", "last_name_mr", "first_name_en", "last_name_en")):
            raise RowError("no_name")

        epic = clean(row["vcardid"])
        if epic:
            epic = re.sub(r"\s", "", epic).upper()
            if not EPIC_RE.match(epic):
                epic = drop("epic_invalid")
        age = to_int(row["age"])
        if age is not None and not 18 <= age <= 125:
            age = drop("age_out_of_range")
        mapping = clean(row["assembly_mapping"])
        if mapping:
            mapping = re.sub(r"\s", "", mapping)
            if not MAPPING_RE.match(mapping):
                mapping = drop("assembly_mapping_invalid")

        ward_id = self.ward(part_no)
        booth_id = self.booth(ward_id, row)
        section_id = self.section(booth_id, row)
        p = self.parts[part_no]
        repeated = self.flag(row["repeated"], "repeated") or (to_int(row["repeated_no"]) or 0) > 0

        voter = dict(
            id=uuid.uuid4(), tenant_id=self.tenant, local_body_id=self.local_body, ward_id=ward_id,
            booth_id=booth_id, section_id=section_id, part_no=part_no, booth_no=to_int(row["booth_no"]),
            serial_no=serial, draft_serial_no=to_int(row["draft_srno"]), epic_no=epic, **names,
            gender=gender, age=age, age_as_of=to_date(p["date_published"]) if age else None,
            house_no=clean(row["house_no"]), address_mr=clean(row["l_address"]), address_en=clean(row["e_address"]),
            assembly_mapping=mapping, is_repeated_in_roll=repeated,
            first_roll_version_id=self.roll, last_roll_version_id=self.roll, legacy_id=clean(row["id"]),
        )

        # ---- campaign data ----
        m1, bad1 = to_mobile(row["mobile_no1"])
        m2, bad2 = to_mobile(row["mobile_no2"])
        if bad1 or bad2:
            dropped.append("mobile_invalid")
        if m1 is None and m2:
            m1, m2 = m2, None
        if m2 == m1:
            m2 = None
        email = clean(row["emailid"])
        if email and not EMAIL_RE.match(email):
            email = drop("email_invalid")
        dob_raw = clean(row["dob"])
        dob = to_date(dob_raw)
        if dob_raw and (dob is None or not date(1900, 1, 1) <= dob <= date.today()):
            dob = drop("dob_invalid")

        caste = self.lookup_master("castes", self.castes, row["l_cast_name"], row["e_cast_name"])
        profession = self.lookup_master("professions", self.professions,
                                        row["l_profession_name"], row["e_profession_name"])
        color_id = None
        color_raw = clean(row["color"])
        if color_raw:
            color_id = self.colors.get(color_raw.lower())
            if color_id is None:
                dropped.append("color_unknown")

        new_mr, new_en = clean(row["l_newaddress"]), clean(row["e_newaddress"])
        custom = {
            "extra_check_1": self.flag(row["extra_check1"], "extra_check1", nullable=True),
            "extra_check_2": self.flag(row["extra_check2"], "extra_check2", nullable=True),
            **{f"extra_info_{i}": clean(row[f"extra_info{i}"]) for i in range(1, 6)},
        }
        for k, v in custom.items():
            if v is not None:
                self.custom_used[k] += 1
        survey = dict(
            mobile_1=m1, mobile_2=m2, email=email, dob=dob, caste_id=caste, profession_id=profession,
            society=clean(row["society"]), flat_no=clean(row["flat_no"]),
            has_new_address=bool(new_mr or new_en) or bool(self.flag(row["addresschange"], "addresschange")),
            new_address_mr=new_mr, new_address_en=new_en, demands=clean(row["demands"]),
            color_tag_id=color_id, is_important=bool(self.flag(row["important"], "important")),
            dead_marked=bool(self.flag(row["dead"], "dead")), **custom,
        )
        has_campaign_data = any(v not in (None, False) for v in survey.values())
        family_key = clean(row["familyid"])
        if family_key in ("0", None):
            family_key = None
        if not has_campaign_data and family_key is None:
            return voter, None, dropped
        survey.update(voter_id=voter["id"], tenant_id=self.tenant, is_surveyed=has_campaign_data,
                      family_id=self.family(family_key, ward_id, booth_id, voter["house_no"]) if family_key else None)
        return voter, survey, dropped

    def lookup_master(self, table: str, cache: dict, mr_raw: str | None, en_raw: str | None) -> uuid.UUID | None:
        mr, en = clean(mr_raw), clean(en_raw)
        if not (mr or en):
            return None
        return self.master_get_or_create(table, cache, mr or en, en)

    def insert(self, voter: dict, survey: dict | None) -> None:
        cols = list(voter)
        self.x(f"INSERT INTO app.voters ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
               [voter[c] for c in cols])
        if survey:
            cols = list(survey)
            self.x(f"INSERT INTO app.voter_surveys ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                   [survey[c] for c in cols])

    def finish(self) -> None:
        # Family head: the member whose EPIC or old voter id equals the old familyid.
        cur = self.x("""UPDATE app.families f SET head_voter_id = v.id
                        FROM app.voter_surveys s JOIN app.voters v ON v.id = s.voter_id
                        WHERE f.tenant_id = %s AND f.head_voter_id IS NULL AND s.family_id = f.id
                          AND (v.epic_no = f.legacy_family_key OR v.legacy_id = f.legacy_family_key)""",
                     (self.tenant,))
        self.created["family_heads_set"] += cur.rowcount
        for key, n in self.custom_used.items():
            if n:
                self.x("""UPDATE app.custom_field_labels SET is_enabled = true
                          WHERE tenant_id = %s AND field_key = %s AND coalesce(label_mr, label_en) IS NOT NULL""",
                       (self.tenant, key))


# --------------------------------------------------------------------------- main
def connect_owner() -> psycopg.Connection:
    load_dotenv(ROOT / "deploy" / ".env")
    return psycopg.connect(
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("POSTGRES_DB", "jansetu"),
        user="jansetu_owner",
        password=os.environ["JANSETU_OWNER_PASSWORD"],
    )


def db_reason(e: psycopg.Error) -> str:
    # SQLSTATE and constraint name only: the message / detail can contain row values.
    return f"db_{e.sqlstate}_{e.diag.constraint_name or 'no_constraint'}"


def run(args: argparse.Namespace) -> None:
    voters_path = Path(args.voters).resolve()
    errors_path = Path(args.errors).resolve()
    if not voters_path.is_file():
        raise SystemExit("--voters file not found.")
    if errors_path.is_relative_to(ROOT) and subprocess.run(
            ["git", "-C", str(ROOT), "check-ignore", "-q", str(errors_path)]).returncode != 0:
        raise SystemExit("--errors must be outside the repo or git-ignored (it contains voter data).")
    errors_path.parent.mkdir(parents=True, exist_ok=True)

    read = imported = skipped = 0
    errors: Counter = Counter()
    dropped: Counter = Counter()
    warnings: Counter = Counter()

    with connect_owner() as conn, \
            open(voters_path, encoding=args.encoding, newline="") as src, \
            open(errors_path, "w", encoding="utf-8-sig", newline="") as errf:
        reader = csv.DictReader(src)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit(f"voters file is missing columns: {', '.join(missing)}")
        writer = csv.writer(errf)
        writer.writerow(["row_no", "action", "reasons", *reader.fieldnames])

        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
        conn.execute("SET LOCAL app.skip_audit = 'on'")  # bulk import: allowed for jansetu_owner only
        imp = Importer(conn, args.tenant_code, warnings)
        imp.setup_workspace()
        imp.load_masters()
        imp.load_existing_voters()
        seen_epic: set[str] = set()
        seen_serial: set[tuple] = set()

        for row_no, row in enumerate(reader, start=2):  # row 1 is the header
            read += 1
            if None in row or any(v is None for v in row.values()):
                errors["malformed_csv_row"] += 1
                writer.writerow([row_no, "not_imported", "malformed_csv_row"])  # column count unknown: no content
                continue
            try:
                voter, survey, drops = imp.build(row)
                epic, key = voter["epic_no"], (voter["booth_id"], voter["serial_no"])
                if (epic and epic in imp.existing_epic) or key in imp.existing_serial:
                    skipped += 1
                    continue
                if epic and epic in seen_epic:
                    raise RowError("duplicate_epic_in_file")
                if key in seen_serial:
                    raise RowError("duplicate_booth_serial_in_file")
                with conn.transaction():
                    imp.insert(voter, survey)
            except RowError as e:
                reason = str(e)
            except psycopg.Error as e:
                reason = db_reason(e)
            else:
                imported += 1
                if epic:
                    seen_epic.add(epic)
                seen_serial.add(key)
                if drops:
                    dropped.update(drops)
                    writer.writerow([row_no, "imported_field_dropped", ";".join(drops), *row.values()])
                continue
            errors[reason] += 1
            writer.writerow([row_no, "not_imported", reason, *row.values()])

        imp.finish()
        if args.dry_run:
            conn.rollback()
        # otherwise the `with connect_owner()` block commits here

    print_summary(args, read, imported, skipped, errors, dropped, warnings, imp.created, errors_path)


def print_summary(args, read, imported, skipped, errors, dropped, warnings, created, errors_path) -> None:
    def block(title: str, c: Counter) -> None:
        print(f"{title}: {sum(c.values())}")
        for k, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"    {k:<45} {n}")

    print("=" * 60)
    print("DRY RUN - everything rolled back, nothing saved" if args.dry_run else "COMMITTED")
    print("=" * 60)
    print(f"rows read                                       {read}")
    print(f"imported                                        {imported}")
    print(f"skipped (already in database)                   {skipped}")
    block("errors (row not imported)", errors)
    block("fields dropped (row imported without that field)", dropped)
    block("unrecognised yes/no values (treated as no)", warnings)
    block("created", created)
    print(f"bad rows written to: {errors_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--voters", required=True, help="old app voters table as CSV (outside the repo)")
    ap.add_argument("--dry-run", action="store_true", help="do everything, then roll back")
    ap.add_argument("--tenant-code", default="naik", help="workspace code users type at login (default: naik)")
    ap.add_argument("--errors", default=str(DEFAULT_ERRORS), help="where to write bad rows (outside the repo)")
    ap.add_argument("--encoding", default="utf-8-sig", help="voters file encoding (default utf-8-sig)")
    args = ap.parse_args()
    try:
        run(args)
    except SystemExit:
        raise
    except UnicodeDecodeError:
        raise SystemExit("Could not decode the voters file. Try --encoding (e.g. utf-16). Nothing was saved.")
    except psycopg.Error as e:
        raise SystemExit(f"Database error ({db_reason(e)}). Nothing was saved.")
    except Exception as e:  # never let a message with row content reach the terminal
        tb = e.__traceback__
        while tb and tb.tb_next:
            tb = tb.tb_next
        raise SystemExit(f"Import failed: {type(e).__name__} at line {tb.tb_lineno if tb else '?'}. Nothing was saved.")


if __name__ == "__main__":
    main()
