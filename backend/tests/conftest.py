"""Shared test fixtures.

Tests never touch the dev database (it may hold real voter data). Each pytest run
drops and re-creates TEST_POSTGRES_DB (default jansetu_test) on the same server,
applies db/migrations with scripts/migrate.py, and every test makes its own
throwaway workspace in it. Server and passwords come from deploy/.env.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
import pytest
from dotenv import load_dotenv
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "deploy" / ".env")

# The run DROPs this database. Only this exact name is ever accepted.
ALLOWED_TEST_DB = "jansetu_test"
TEST_DB = os.environ.get("TEST_POSTGRES_DB", ALLOWED_TEST_DB)
if TEST_DB != ALLOWED_TEST_DB:
    raise RuntimeError(f"Refusing to run: TEST_POSTGRES_DB is {TEST_DB!r}; tests only drop/rebuild "
                       f"{ALLOWED_TEST_DB!r}.")
# Everything below (the app's Settings, migrate.py) now points at the test database.
os.environ["POSTGRES_DB"] = TEST_DB
os.environ.setdefault("JWT_SECRET", "test-only-secret-" + "x" * 32)
os.environ["LOGIN_MAX_FAILURES"] = "5"
os.environ["LOGIN_LOCK_MINUTES"] = "15"
os.environ["CORS_ORIGINS"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402
from app.security import hash_password  # noqa: E402

PASSWORD = "Test@pass123"
_PASSWORD_HASH = hash_password(PASSWORD)


def _connect(user: str, password_var: str, dbname: str = TEST_DB, autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=os.environ.get("PGPORT", "5432"),
        dbname=dbname,
        user=user,
        password=os.environ[password_var],
        autocommit=autocommit,
    )


@pytest.fixture(scope="session", autouse=True)
def test_database():
    """Fresh database with all migrations applied, once per pytest run."""
    if TEST_DB != ALLOWED_TEST_DB:  # checked again right before the DROP
        pytest.exit(f"Refusing to drop {TEST_DB!r}", returncode=1)
    with _connect(os.environ.get("POSTGRES_USER", "postgres"), "POSTGRES_PASSWORD",
                  dbname="postgres", autocommit=True) as su:
        su.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(TEST_DB)))
        su.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(sql.Identifier(TEST_DB)))
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "migrate.py")], env=os.environ.copy(),
                          capture_output=True, text=True)
    if done.returncode != 0:
        pytest.exit(f"migrate.py failed on {TEST_DB}:\n{done.stdout}\n{done.stderr}", returncode=1)
    yield


@pytest.fixture
def owner_conn():
    """jansetu_owner (BYPASSRLS): test setup only. Autocommit, so setup is visible to the API at once."""
    with _connect("jansetu_owner", "JANSETU_OWNER_PASSWORD", autocommit=True) as conn:
        yield conn


@pytest.fixture
def app_conn():
    """jansetu_app: the role the API uses. RLS applies."""
    with _connect("jansetu_app", "JANSETU_APP_PASSWORD") as conn:
        yield conn


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(create_app())


# --- throwaway workspaces --------------------------------------------------------
@dataclass
class Workspace:
    tenant: uuid.UUID
    code: str
    local_body: uuid.UUID
    ward: uuid.UUID
    booths: list[uuid.UUID]
    users: dict[str, uuid.UUID] = field(default_factory=dict)


def create_workspace(owner_conn: psycopg.Connection, label: str = "ws", must_change: tuple[str, ...] = (),
                     extra_users: dict[str, str] | None = None) -> Workspace:
    """Workspace with 1 constituency, 1 ward, 2 booths and users (password PASSWORD):
       boss (super_admin), admin1 (admin), sup1 (supervisor, the ward),
       survey1 (surveyor, booth 1 only), plus any `extra_users` {username: role}.
       `must_change` lists usernames that must change their password.
       `owner_conn` is a jansetu_owner connection in autocommit mode."""
    ids = [uuid.uuid4() for _ in range(5)]
    tenant, lb, ward, b1, b2 = ids
    ws = Workspace(tenant, f"t-{label}-{tenant.hex[:8]}", lb, ward, [b1, b2])
    users = {"boss": "super_admin", "admin1": "admin", "sup1": "supervisor", "survey1": "surveyor",
             **(extra_users or {})}
    with owner_conn.transaction(), owner_conn.cursor() as cur:
        cur.execute("INSERT INTO app.tenants (id, code, name_en) VALUES (%s, %s, %s)",
                    (tenant, ws.code, f"Test {label}"))
        cur.execute("SELECT app.seed_tenant_defaults(%s)", (tenant,))
        geo = """INSERT INTO app.geo_units (id, tenant_id, parent_id, level, code, number, name_mr, name_en)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"""
        cur.execute(geo, (lb, tenant, None, "local_body", "1", None, f"LB {label}", f"LB {label}"))
        cur.execute(geo, (ward, tenant, lb, "ward", "1", 1, "W1", "Ward 1"))
        cur.execute(geo, (b1, tenant, ward, "booth", "1001", 1, "B1", "Booth 1"))
        cur.execute(geo, (b2, tenant, ward, "booth", "1002", 2, "B2", "Booth 2"))
        for username, role in users.items():
            uid = uuid.uuid4()
            ws.users[username] = uid
            cur.execute(
                """INSERT INTO app.users (id, tenant_id, username, full_name_en, role, local_body_id,
                                          password_hash, must_change_password)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (uid, tenant, username, username.title(), role,
                 None if role == "super_admin" else lb, _PASSWORD_HASH, username in must_change))
        assign = "INSERT INTO app.user_area_assignments (tenant_id, user_id, geo_unit_id) VALUES (%s, %s, %s)"
        cur.execute(assign, (tenant, ws.users["sup1"], ward))
        cur.execute(assign, (tenant, ws.users["survey1"], b1))
    return ws


@pytest.fixture
def make_workspace(owner_conn) -> Callable[..., Workspace]:
    """create_workspace bound to this test's owner connection."""

    def make(label: str = "ws", must_change: tuple[str, ...] = (),
             extra_users: dict[str, str] | None = None) -> Workspace:
        return create_workspace(owner_conn, label, must_change, extra_users)

    return make


@pytest.fixture
def set_device_status(owner_conn) -> Callable[[uuid.UUID | str, str], None]:
    """What the admin endpoints will do later: approve or block a phone."""

    def set_status(device_id, status: str) -> None:
        owner_conn.execute(
            """UPDATE app.devices SET status = %s, decided_at = now(),
                      wipe_requested_at = CASE WHEN %s = 'blocked' THEN now() ELSE wipe_requested_at END
                WHERE id = %s""",
            (status, status, device_id))

    return set_status


def phone(uid: str = "android-id-0001") -> dict:
    return {"device_uid": uid, "model": "Test Phone", "os_version": "Android 14", "app_version_code": 1}


def login(client: TestClient, ws: Workspace, username: str, password: str = PASSWORD,
          device: dict | None = None):
    body = {"workspace_code": ws.code, "username": username, "password": password}
    if device is not None:
        body["device"] = device
    return client.post("/api/v1/auth/login", json=body)


def bearer(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}
