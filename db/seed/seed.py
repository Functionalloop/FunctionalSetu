"""Fill a freshly migrated database with FAKE sample data for development.

    python db/seed/seed.py

Creates (all invented, deterministic: same output on every run):
  * workspace "demo" with default colour tags / templates (app.seed_tenant_defaults)
  * 1 constituency (local body), 3 wards, 2 booths per ward
  * ~2000 voters grouped into households, names in Marathi and English,
    fake EPIC numbers with the prefix TST (never a real EPIC)
  * one user per role, all with the same test password (SEED_USER_PASSWORD,
    default Jansetu@123), plus ward / booth assignments

Runs as jansetu_owner (BYPASSRLS), as the schema intends for imports. Audit
logging is skipped for the bulk insert (app.skip_audit). If workspace "demo"
already exists it stops; to start over, drop the dev volume and migrate again.
No real voter data is read or written by this script.
"""

from __future__ import annotations

import os
import random
import sys
import uuid
from datetime import date
from pathlib import Path

import psycopg
from argon2 import PasswordHasher
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]

TENANT_CODE = "demo"
VOTER_TARGET = 2000
WARDS = 3
BOOTHS_PER_WARD = 2
AGE_AS_OF = date(2026, 1, 1)
RNG = random.Random(20261125)  # fixed seed → same data every run

# (Marathi, English) pairs. Common Konkan / Maharashtra names; no real people.
MALE = [
    ("राहुल", "Rahul"), ("संदीप", "Sandeep"), ("अमित", "Amit"), ("विजय", "Vijay"), ("गणेश", "Ganesh"),
    ("प्रकाश", "Prakash"), ("सुनील", "Sunil"), ("महेश", "Mahesh"), ("नितीन", "Nitin"), ("अजय", "Ajay"),
    ("दत्ताराम", "Dattaram"), ("रमेश", "Ramesh"), ("सुरेश", "Suresh"), ("विनायक", "Vinayak"),
    ("प्रशांत", "Prashant"), ("संतोष", "Santosh"), ("मंगेश", "Mangesh"), ("नारायण", "Narayan"),
    ("शंकर", "Shankar"), ("अनिल", "Anil"), ("दीपक", "Deepak"), ("योगेश", "Yogesh"), ("किरण", "Kiran"),
    ("सागर", "Sagar"), ("आदित्य", "Aditya"), ("ओंकार", "Omkar"), ("रोहन", "Rohan"), ("तुषार", "Tushar"),
    ("विठ्ठल", "Vitthal"), ("बाबाजी", "Babaji"),
]
FEMALE = [
    ("सुनिता", "Sunita"), ("प्रिया", "Priya"), ("अनिता", "Anita"), ("मीना", "Meena"), ("स्नेहा", "Sneha"),
    ("पूजा", "Pooja"), ("वैशाली", "Vaishali"), ("सविता", "Savita"), ("कविता", "Kavita"), ("रेखा", "Rekha"),
    ("शुभांगी", "Shubhangi"), ("मनीषा", "Manisha"), ("अश्विनी", "Ashwini"), ("प्राजक्ता", "Prajakta"),
    ("सुरेखा", "Surekha"), ("लता", "Lata"), ("शारदा", "Sharada"), ("वंदना", "Vandana"),
    ("दीपाली", "Deepali"), ("रुपाली", "Rupali"), ("अर्चना", "Archana"), ("सायली", "Sayali"),
    ("गौरी", "Gauri"), ("नेहा", "Neha"), ("माधुरी", "Madhuri"),
]
SURNAMES = [
    ("पाटील", "Patil"), ("देसाई", "Desai"), ("सावंत", "Sawant"), ("राऊळ", "Raul"), ("परब", "Parab"),
    ("गावडे", "Gawade"), ("कदम", "Kadam"), ("शिंदे", "Shinde"), ("जाधव", "Jadhav"), ("पवार", "Pawar"),
    ("गोसावी", "Gosavi"), ("कुलकर्णी", "Kulkarni"), ("जोशी", "Joshi"), ("मोरे", "More"),
    ("चव्हाण", "Chavan"), ("भोसले", "Bhosale"), ("राणे", "Rane"), ("केरकर", "Kerkar"), ("तेली", "Teli"),
    ("कांबळे", "Kamble"), ("गवस", "Gawas"), ("धुरी", "Dhuri"), ("मेस्त्री", "Mestry"),
    ("पेडणेकर", "Pednekar"), ("साळगावकर", "Salgaonkar"),
]
LOCALITIES = [
    ("गणेश नगर", "Ganesh Nagar"), ("स्टेशन रोड", "Station Road"), ("नवी वाडी", "Navi Wadi"),
    ("मंदिर गल्ली", "Mandir Galli"), ("तलाव काठ", "Talav Kath"), ("शाळा रोड", "Shala Road"),
]

# username, role, display name (en, mr)
USERS = [
    ("superadmin", "super_admin", "Demo Super Admin", "डेमो सुपर ॲडमिन"),
    ("admin", "admin", "Demo Admin", "डेमो ॲडमिन"),
    ("supervisor", "supervisor", "Demo Supervisor", "डेमो पर्यवेक्षक"),
    ("surveyor", "surveyor", "Demo Surveyor", "डेमो सर्वेक्षक"),
    ("boothagent", "booth_agent", "Demo Booth Agent", "डेमो बूथ प्रतिनिधी"),
]


def new_id() -> uuid.UUID:
    return uuid.UUID(int=RNG.getrandbits(128), version=4)


def connect_owner() -> psycopg.Connection:
    load_dotenv(ROOT / "deploy" / ".env")
    return psycopg.connect(
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("POSTGRES_DB", "jansetu"),
        user="jansetu_owner",
        password=os.environ["JANSETU_OWNER_PASSWORD"],
    )


def make_household(surname: tuple[str, str]) -> list[dict]:
    """A household: head, often a spouse, then adult children. Middle name = father's / husband's name."""
    size = RNG.choices([1, 2, 3, 4, 5, 6], weights=[8, 22, 25, 25, 13, 7])[0]
    head_age = RNG.randint(30, 82) if size > 1 else RNG.randint(18, 85)
    head_gender = "M" if size > 1 or RNG.random() < 0.6 else "F"
    head_first = RNG.choice(MALE if head_gender == "M" else FEMALE)
    head_rel = RNG.choice(MALE)  # head's father (or husband, for a woman living alone)
    members = [dict(first=head_first, gender=head_gender, age=head_age, rel_type="father" if head_gender == "M"
                    else RNG.choice(["father", "husband"]), rel_first=head_rel)]
    if size >= 2 and head_gender == "M":
        members.append(dict(first=RNG.choice(FEMALE), gender="F", age=max(18, head_age - RNG.randint(0, 8)),
                            rel_type="husband", rel_first=head_first))
    while len(members) < size:
        child_age = head_age - RNG.randint(20, 34)
        if child_age < 18:
            break
        gender = RNG.choice("MF")
        members.append(dict(first=RNG.choice(MALE if gender == "M" else FEMALE), gender=gender, age=child_age,
                            rel_type="father", rel_first=head_first if head_gender == "M" else head_rel))
    for m in members:
        m["surname"] = surname
    return members


def main() -> None:
    password = os.environ.get("SEED_USER_PASSWORD") or "Jansetu@123"
    with connect_owner() as conn, conn.cursor() as cur:
        if cur.execute("SELECT 1 FROM app.tenants WHERE code = %s", (TENANT_CODE,)).fetchone():
            sys.exit(f'Workspace "{TENANT_CODE}" already exists; nothing to do. '
                     "To start over: docker compose -f deploy/docker-compose.dev.yml down -v, then migrate and seed.")

        cur.execute("SET LOCAL app.skip_audit = 'on'")

        # --- workspace ------------------------------------------------------
        tenant = new_id()
        cur.execute("INSERT INTO app.tenants (id, code, name_en, name_mr) VALUES (%s, %s, %s, %s)",
                    (tenant, TENANT_CODE, "Demo Workspace", "डेमो कार्यक्षेत्र"))
        cur.execute("SELECT app.seed_tenant_defaults(%s)", (tenant,))
        cur.execute(
            """UPDATE app.tenant_settings
                  SET election_name_en = 'Sample Nagar Parishad Election 2026',
                      election_name_mr = 'नमुना नगर परिषद निवडणूक २०२६',
                      election_type = 'nagarpalika', polling_date = DATE '2026-12-20'
                WHERE tenant_id = %s""", (tenant,))

        # --- areas ----------------------------------------------------------
        geo_sql = """INSERT INTO app.geo_units (id, tenant_id, parent_id, level, code, number, name_mr, name_en,
                                                address_mr, address_en, ac_no, sort_order)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        local_body = new_id()
        cur.execute(geo_sql, (local_body, tenant, None, "local_body", "999", None, "नमुना नगर परिषद",
                              "Sample Nagar Parishad", None, None, 999, 1))
        wards: list[uuid.UUID] = []
        booths: list[tuple[uuid.UUID, uuid.UUID, int, int]] = []  # booth, ward, ward_no, booth_no
        for w in range(1, WARDS + 1):
            ward = new_id()
            wards.append(ward)
            cur.execute(geo_sql, (ward, tenant, local_body, "ward", str(w), w, f"प्रभाग क्र. {w}", f"Ward {w}",
                                  None, None, None, w))
            for b in range(1, BOOTHS_PER_WARD + 1):
                booth = new_id()
                booths.append((booth, ward, w, b))
                cur.execute(geo_sql, (booth, tenant, ward, "booth", f"{w}{b:03d}", b,
                                      f"जि. प. शाळा, खोली क्र. {b} (प्रभाग {w})",
                                      f"ZP School, Room {b} (Ward {w})",
                                      f"जि. प. शाळा, प्रभाग {w}", f"ZP School, Ward {w}", None, b))

        # --- roll version, so the app can show "List v1" --------------------
        roll = new_id()
        cur.execute("""INSERT INTO app.roll_versions (id, tenant_id, local_body_id, list_type, title, published_on,
                                                     status, applied_at)
                       VALUES (%s, %s, %s, 'main', 'Sample roll (fake data)', DATE '2026-01-01', 'applied', now())""",
                    (roll, tenant, local_body))
        cur.executemany("""INSERT INTO app.roll_part_versions (tenant_id, ward_id, data_version, published_on,
                                                              roll_version_id)
                           VALUES (%s, %s, 1, DATE '2026-01-01', %s)""",
                        [(tenant, w, roll) for w in wards])

        # --- voters ---------------------------------------------------------
        rows = []
        epic_seq = 1_000_001
        per_booth = [VOTER_TARGET // len(booths) + (1 if i < VOTER_TARGET % len(booths) else 0)
                     for i in range(len(booths))]
        for (booth, ward, ward_no, booth_no), target in zip(booths, per_booth):
            serial, house = 0, 0
            locality = LOCALITIES[(ward_no - 1) * BOOTHS_PER_WARD + booth_no - 1]
            while serial < target:
                house += 1
                house_no = str(house) if RNG.random() < 0.8 else f"{house}/{RNG.choice('ABC')}"
                for m in make_household(RNG.choice(SURNAMES)):
                    if serial >= target:
                        break
                    serial += 1
                    (first_mr, first_en), (last_mr, last_en), (rel_mr, rel_en) = m["first"], m["surname"], m["rel_first"]
                    rows.append((
                        new_id(), tenant, local_body, ward, booth, ward_no, booth_no, serial,
                        f"TST{epic_seq:07d}",
                        first_mr, rel_mr, last_mr, first_en, rel_en, last_en,
                        m["rel_type"], f"{rel_mr} {last_mr}", f"{rel_en} {last_en}",
                        m["gender"], min(m["age"], 100), AGE_AS_OF, house_no,
                        f"{house_no}, {locality[0]}", f"{house_no}, {locality[1]}",
                        f"999/{ward_no}/{serial}", roll, roll,
                    ))
                    epic_seq += 1
        cur.executemany(
            """INSERT INTO app.voters (id, tenant_id, local_body_id, ward_id, booth_id, part_no, booth_no, serial_no,
                                       epic_no, first_name_mr, middle_name_mr, last_name_mr,
                                       first_name_en, middle_name_en, last_name_en,
                                       relation_type, relative_name_mr, relative_name_en,
                                       gender, age, age_as_of, house_no, address_mr, address_en,
                                       assembly_mapping, first_roll_version_id, last_roll_version_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            rows,
        )

        # --- users and area assignments --------------------------------------
        hasher = PasswordHasher()  # Argon2id
        user_ids: dict[str, uuid.UUID] = {}
        for username, role, name_en, name_mr in USERS:
            uid = new_id()
            user_ids[role] = uid
            cur.execute(
                """INSERT INTO app.users (id, tenant_id, username, full_name_en, full_name_mr, role, local_body_id,
                                          password_hash, must_change_password, preferred_language)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, false, 'en')""",
                (uid, tenant, username, name_en, name_mr, role,
                 None if role == "super_admin" else local_body, hasher.hash(password)),
            )
        # supervisor: wards 1 and 2 · surveyor: both booths of ward 1 · booth agent: ward 1 booth 1
        assignments = [
            ("supervisor", wards[0]), ("supervisor", wards[1]),
            ("surveyor", booths[0][0]), ("surveyor", booths[1][0]),
            ("booth_agent", booths[0][0]),
        ]
        cur.executemany(
            """INSERT INTO app.user_area_assignments (tenant_id, user_id, geo_unit_id, assigned_by)
               VALUES (%s, %s, %s, %s)""",
            [(tenant, user_ids[role], geo, user_ids["admin"]) for role, geo in assignments],
        )

    print(f'Seeded workspace "{TENANT_CODE}" (tenant id {tenant})')
    print(f"  1 constituency, {len(wards)} wards, {len(booths)} booths, {len(rows)} voters (all fake)")
    print(f"  users: {', '.join(u[0] for u in USERS)}  password: {password}")
    print("  supervisor -> Ward 1, Ward 2 | surveyor -> Ward 1 booths 1-2 | boothagent -> Ward 1 booth 1")


if __name__ == "__main__":
    main()
