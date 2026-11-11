"""Import official electoral-roll part files (S05A02P01..P51_*.csv) into JANSETU.

    python scripts/import_roll_parts.py --parts "DIR/S05A02P*.csv" [--dry-run]
                                        [--tenant-code naik] [--errors PATH]

Format: one CSV per roll part, header
  id,ward_id,part_no,serial_no,section_no,section_name,epic_no,full_name,surname,
  relative_name,relation_type,house_no,age,gender,polling_booth,is_deleted,
  is_supplement_addition,voted,is_dead,is_important,color_code,contact_ref,dob,...

Area mapping (Vidhan Sabha roll):
  constituency (local body)  = assembly no. from the file name (S05A02 -> AC 2), --ac-name
  ward                       = roll part (part_no)     -- one ward per part, for assignments
  booth                      = the part's polling station (polling_booth)
  section                    = section_no / section_name

Official roll fields go to app.voters only. These files carry no campaign data
(mobile, caste, DOB, colour, family are empty), so no voter_surveys rows are made.
Masters (castes, professions, colours, labels) come from docs/legacy/*.csv.

Same guarantees as import_legacy.py: one transaction, --dry-run rolls back,
re-runs skip voters already present (EPIC, or booth + serial), counts only on
screen, bad rows to --errors (outside the repo or git-ignored).
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import re
import subprocess
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

import psycopg

from import_legacy import ROOT, EPIC_RE, Importer, RowError, clean, connect_owner, db_reason, to_int

LOCK_ID = 7_406_002  # same key as import_legacy: never two imports at once
FILE_RE = re.compile(r"S(\d{2})A(\d{2})P(\d{2,3})", re.IGNORECASE)
REQUIRED = ["id", "part_no", "serial_no", "section_no", "section_name", "epic_no", "full_name", "surname",
            "relative_name", "relation_type", "house_no", "age", "gender", "polling_booth",
            "is_deleted", "is_supplement_addition", "updated_at"]
GENDER = {"male": "M", "m": "M", "female": "F", "f": "F", "other": "O", "o": "O", "third gender": "O"}
RELATION = {"father": "father", "mother": "mother", "husband": "husband", "wife": "wife", "other": "other"}
BOOL = {"true": True, "1": True, "yes": True, "false": False, "0": False, "no": False, "": False}


def split_name(full: str | None, surname: str | None) -> tuple[str | None, str | None, str | None]:
    """'First Middle Surname' -> (first, middle, last). Surname column wins for the last name."""
    words = (full or "").split()
    last = surname or None
    if words and last and words[-1].lower() == last.lower():
        words = words[:-1]
    elif words and not last and len(words) > 1:
        last, words = words[-1], words[:-1]
    first = words[0] if words else None
    middle = " ".join(words[1:]) or None
    return first, middle, last


def flag(v: str | None, field: str, warn: Counter) -> bool:
    raw = (v or "").strip().lower()
    if raw not in BOOL:
        warn[f"flag_unrecognised:{field}"] += 1
    return BOOL.get(raw, False)


def run(args: argparse.Namespace) -> None:
    files = sorted(glob.glob(args.parts))
    if not files:
        raise SystemExit("No files match --parts.")
    errors_path = Path(args.errors).resolve()
    if errors_path.is_relative_to(ROOT) and subprocess.run(
            ["git", "-C", str(ROOT), "check-ignore", "-q", str(errors_path)]).returncode != 0:
        raise SystemExit("--errors must be outside the repo or git-ignored (it contains voter data).")
    errors_path.parent.mkdir(parents=True, exist_ok=True)

    # Same assembly in every file name; byte-identical files are skipped.
    acs = {m.group(2) for f in files if (m := FILE_RE.search(Path(f).name))}
    if len(acs) != 1:
        raise SystemExit("File names must all carry the same assembly (SxxAyyPzz).")
    ac_no = int(acs.pop())
    seen_hash: dict[str, str] = {}
    dup_files: list[str] = []
    for f in files:
        h = hashlib.sha256(Path(f).read_bytes()).hexdigest()
        if h in seen_hash:
            dup_files.append(Path(f).name)
        seen_hash.setdefault(h, f)
    files = [f for f in files if Path(f).name not in dup_files]

    read = imported = skipped = 0
    errors: Counter = Counter()
    dropped: Counter = Counter()
    warn: Counter = Counter()

    with connect_owner() as conn, open(errors_path, "w", encoding="utf-8-sig", newline="") as errf:
        writer = csv.writer(errf)
        writer.writerow(["file", "row_no", "action", "reasons", *REQUIRED])
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
        conn.execute("SET LOCAL app.skip_audit = 'on'")  # bulk import: allowed for jansetu_owner only

        imp = Importer(conn, args.tenant_code, warn)
        imp.ensure_tenant()
        imp.load_masters()
        imp.load_existing_voters()
        created = imp.created

        lb = imp.geo_get_or_create(None, "local_body", f"AC{ac_no}", None, name_mr=args.ac_name,
                                   name_en=args.ac_name)
        conn.execute("UPDATE app.geo_units SET ac_no = %s WHERE id = %s AND ac_no IS NULL", (ac_no, lb))

        roll_title = f"Electoral roll AC {ac_no} (part files)"
        row = conn.execute("SELECT id FROM app.roll_versions WHERE tenant_id = %s AND title = %s",
                           (imp.tenant, roll_title)).fetchone()
        roll = row[0] if row else uuid.uuid4()
        if not row:
            conn.execute("""INSERT INTO app.roll_versions (id, tenant_id, local_body_id, list_type, title, status, applied_at)
                            VALUES (%s, %s, %s, 'main', %s, 'applied', now())""", (roll, imp.tenant, lb, roll_title))
            created["roll_version"] += 1

        published = None
        versioned: set[uuid.UUID] = set()
        seen_epic: set[str] = set()
        seen_serial: set[tuple] = set()

        # Read everything first, then import live rows before rows deleted in the roll: a voter deleted in
        # one place and re-added elsewhere shares one EPIC, and the live entry must be the one kept.
        all_rows: list[tuple[str, int, dict]] = []
        for path in files:
            name = Path(path).name
            with open(path, encoding="utf-8-sig", newline="") as src:
                reader = csv.DictReader(src)
                missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
                if missing:
                    raise SystemExit(f"{name} is missing columns: {', '.join(missing)}")
                all_rows.extend((name, row_no, r) for row_no, r in enumerate(reader, start=2))
        is_del = lambda r: (r.get("is_deleted") or "").strip().lower() == "true"  # noqa: E731
        all_rows.sort(key=lambda t: is_del(t[2]))  # stable: file order kept within each group
        live_epics = Counter(re.sub(r"\s", "", (r.get("epic_no") or "")).upper()
                             for _, _, r in all_rows if not is_del(r))
        repeated_epics = {e for e, n in live_epics.items() if e and n > 1}

        for name, row_no, r in all_rows:
            read += 1
            drops: list[str] = []
            try:
                if None in r or any(v is None for v in r.values()):
                    raise RowError("malformed_csv_row")
                part_no, serial = to_int(r["part_no"]), to_int(r["serial_no"])
                if part_no is None:
                    raise RowError("no_part_no")
                if serial is None or serial <= 0:
                    raise RowError("bad_serial_no")
                gender = GENDER.get(r["gender"].strip().lower())
                if gender is None:
                    raise RowError("bad_gender")
                first, middle, last = split_name(clean(r["full_name"]), clean(r["surname"]))
                if not (first or last):
                    raise RowError("no_name")
                epic = clean(r["epic_no"])
                if epic:
                    epic = re.sub(r"\s", "", epic).upper()
                    if not EPIC_RE.match(epic):
                        epic = None
                        drops.append("epic_invalid")
                age = to_int(r["age"])
                if age is not None and not 18 <= age <= 125:
                    age = None
                    drops.append("age_out_of_range")
                rel_raw = clean(r["relation_type"])
                relation = RELATION.get(rel_raw.lower()) if rel_raw else None
                if rel_raw and relation is None:
                    drops.append("relation_type_unknown")
                as_of = None
                if ts := clean(r["updated_at"]):
                    try:
                        as_of = datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
                    except ValueError:
                        drops.append("updated_at_invalid")
                published = max(filter(None, (published, as_of)), default=None)

                # areas: ward = part, booth = polling station, section
                ward = imp.geo_get_or_create(lb, "ward", str(part_no), part_no,
                                             name_mr=f"भाग {part_no}", name_en=f"Part {part_no}")
                station = clean(r["polling_booth"]) or f"Part {part_no}"
                station = re.sub(rf"^\s*{part_no}\s*-\s*", "", station)
                booth = imp.geo_get_or_create(ward, "booth", str(part_no), 1, name_mr=station,
                                              name_en=station, address_mr=station, address_en=station)
                sec_no = to_int(r["section_no"])
                sec_name = clean(r["section_name"])
                section = None
                if sec_no is not None or sec_name:
                    section = imp.geo_get_or_create(
                        booth, "section", str(sec_no if sec_no is not None else sec_name), sec_no,
                        name_mr=sec_name or f"Section {sec_no}", name_en=sec_name)
                if ward not in versioned:
                    versioned.add(ward)
                    conn.execute("""INSERT INTO app.roll_part_versions (tenant_id, ward_id, data_version,
                                                                       published_on, roll_version_id)
                                    VALUES (%s, %s, 1, %s, %s) ON CONFLICT DO NOTHING""",
                                 (imp.tenant, ward, as_of, roll))

                key = (booth, serial)
                if (epic and epic in imp.existing_epic) or key in imp.existing_serial:
                    skipped += 1
                    continue
                if epic and epic in seen_epic:
                    raise RowError("duplicate_epic_in_file")
                if key in seen_serial:
                    raise RowError("duplicate_part_serial_in_file")

                deleted = flag(r["is_deleted"], "is_deleted", warn)
                voter = dict(
                    id=uuid.uuid4(), tenant_id=imp.tenant, local_body_id=lb, ward_id=ward, booth_id=booth,
                    section_id=section, part_no=part_no, booth_no=1, serial_no=serial, epic_no=epic,
                    first_name_en=first, middle_name_en=middle, last_name_en=last,
                    relation_type=relation, relative_name_en=clean(r["relative_name"]),
                    gender=gender, age=age, age_as_of=as_of if age else None,
                    house_no=clean(r["house_no"]), address_en=sec_name,
                    list_type="supplementary" if flag(r["is_supplement_addition"], "is_supplement_addition",
                                                       warn) else "main",
                    roll_status="deleted_in_roll" if deleted else "active",
                    is_repeated_in_roll=bool(epic) and epic in repeated_epics,
                    first_roll_version_id=roll, last_roll_version_id=roll,
                    legacy_id=f"{part_no}:{clean(r['id'])}",
                )
                with conn.transaction():
                    imp.insert(voter, None)
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
                    writer.writerow([name, row_no, "imported_field_dropped", ";".join(drops),
                                     *(r.get(c) for c in REQUIRED)])
                continue
            errors[reason] += 1
            writer.writerow([name, row_no, "not_imported", reason, *(r.get(c) for c in REQUIRED)])

        if published:
            conn.execute("UPDATE app.roll_versions SET published_on = %s WHERE id = %s AND published_on IS NULL",
                         (published, roll))
        if args.dry_run:
            conn.rollback()

    print("=" * 60)
    print("DRY RUN - everything rolled back, nothing saved" if args.dry_run else "COMMITTED")
    print("=" * 60)
    print(f"files read                                      {len(files)}")
    print(f"files skipped (byte-identical to another)       {len(dup_files)}  {' '.join(dup_files)}")
    print(f"rows read                                       {read}")
    print(f"imported                                        {imported}")
    print(f"skipped (already in database)                   {skipped}")
    for title, c in (("errors (row not imported)", errors), ("fields dropped (row imported without it)", dropped),
                     ("unrecognised yes/no values (treated as no)", warn), ("created", created)):
        print(f"{title}: {sum(c.values())}")
        for k, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"    {k:<45} {n}")
    print(f"bad rows written to: {errors_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parts", required=True, help='glob of part files, e.g. "jansetu-private/S05A02P*.csv"')
    ap.add_argument("--dry-run", action="store_true", help="do everything, then roll back")
    ap.add_argument("--tenant-code", default="naik")
    ap.add_argument("--ac-name", default="Pernem (AC 2)", help="constituency name to show in the app")
    ap.add_argument("--errors", default=str(ROOT.parent / "jansetu-private" / "import_errors_parts.csv"))
    args = ap.parse_args()
    try:
        run(args)
    except SystemExit:
        raise
    except psycopg.Error as e:
        raise SystemExit(f"Database error ({db_reason(e)}). Nothing was saved.")
    except Exception as e:  # never let a message with row content reach the terminal
        tb = e.__traceback__
        while tb and tb.tb_next:
            tb = tb.tb_next
        raise SystemExit(f"Import failed: {type(e).__name__} at line {tb.tb_lineno if tb else '?'}. Nothing was saved.")


if __name__ == "__main__":
    main()
