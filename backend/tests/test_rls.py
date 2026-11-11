"""Row-level security: after app.set_context(A), workspace B's rows are invisible.

Creates two throwaway workspaces as jansetu_owner, checks them as jansetu_app
(the API role), then deletes them. Needs a migrated database (see README steps).
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

TABLES_WITH_ROWS = ("geo_units", "users", "voters")


def _make_workspace(cur: psycopg.Cursor, label: str) -> dict[str, uuid.UUID]:
    ids = {k: uuid.uuid4() for k in ("tenant", "local_body", "ward", "booth", "voter", "user")}
    code = f"rls-{label}-{ids['tenant'].hex[:8]}"
    cur.execute("INSERT INTO app.tenants (id, code, name_en) VALUES (%s, %s, %s)",
                (ids["tenant"], code, f"RLS test {label}"))
    geo = "INSERT INTO app.geo_units (id, tenant_id, parent_id, level, code, name_mr) VALUES (%s, %s, %s, %s, %s, %s)"
    cur.execute(geo, (ids["local_body"], ids["tenant"], None, "local_body", "1", "LB"))
    cur.execute(geo, (ids["ward"], ids["tenant"], ids["local_body"], "ward", "1", "W1"))
    cur.execute(geo, (ids["booth"], ids["tenant"], ids["ward"], "booth", "1001", "B1"))
    cur.execute(
        """INSERT INTO app.voters (id, tenant_id, local_body_id, ward_id, booth_id, part_no, serial_no,
                                   first_name_en, last_name_en, gender, age)
           VALUES (%s, %s, %s, %s, %s, 1, 1, %s, 'Testcase', 'M', 40)""",
        (ids["voter"], ids["tenant"], ids["local_body"], ids["ward"], ids["booth"], f"Voter{label}"),
    )
    cur.execute(
        """INSERT INTO app.users (id, tenant_id, username, full_name_en, role, local_body_id, password_hash)
           VALUES (%s, %s, 'rlsuser', 'RLS User', 'admin', %s, 'not-a-real-hash')""",
        (ids["user"], ids["tenant"], ids["local_body"]),
    )
    return ids


def _delete_workspace(cur: psycopg.Cursor, ids: dict[str, uuid.UUID]) -> None:
    t = ids["tenant"]
    cur.execute("DELETE FROM app.users WHERE tenant_id = %s", (t,))
    cur.execute("DELETE FROM app.voters WHERE tenant_id = %s", (t,))
    for level in ("booth", "ward", "local_body"):
        cur.execute("DELETE FROM app.geo_units WHERE tenant_id = %s AND level = %s", (t, level))
    cur.execute("DELETE FROM app.tenants WHERE id = %s", (t,))


@pytest.fixture
def two_workspaces(owner_conn):
    with owner_conn.transaction(), owner_conn.cursor() as cur:
        cur.execute("SET LOCAL app.skip_audit = 'on'")  # keep audit_log (append-only) clean
        a, b = _make_workspace(cur, "a"), _make_workspace(cur, "b")
    yield a, b
    with owner_conn.transaction(), owner_conn.cursor() as cur:
        cur.execute("SET LOCAL app.skip_audit = 'on'")
        for ids in (a, b):
            _delete_workspace(cur, ids)


def test_app_role_cannot_bypass_rls(app_conn):
    row = app_conn.execute(
        "SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()
    assert row == (False, False)


def test_no_context_sees_nothing(app_conn, two_workspaces):
    for table in TABLES_WITH_ROWS + ("tenants",):
        count = app_conn.execute(f"SELECT count(*) FROM app.{table}").fetchone()[0]
        assert count == 0, f"app.{table} visible without set_context"


def test_other_workspace_invisible(app_conn, two_workspaces):
    a, b = two_workspaces
    with app_conn.transaction():
        app_conn.execute("SELECT app.set_context(%s, %s, NULL)", (a["tenant"], a["user"]))

        # A's own rows are visible ...
        assert app_conn.execute("SELECT id FROM app.tenants").fetchall() == [(a["tenant"],)]
        voters = app_conn.execute("SELECT id FROM app.voters").fetchall()
        assert (a["voter"],) in voters

        # ... B's rows are not, not even when asked for by id or tenant_id.
        for table in TABLES_WITH_ROWS:
            n = app_conn.execute(f"SELECT count(*) FROM app.{table} WHERE tenant_id = %s",
                                 (b["tenant"],)).fetchone()[0]
            assert n == 0, f"workspace B rows visible in app.{table}"
        assert app_conn.execute("SELECT 1 FROM app.voters WHERE id = %s", (b["voter"],)).fetchone() is None

        # Updates cannot reach B's rows either.
        cur = app_conn.execute("UPDATE app.voters SET house_no = 'x' WHERE id = %s", (b["voter"],))
        assert cur.rowcount == 0


def test_cannot_write_into_other_workspace(app_conn, two_workspaces):
    a, b = two_workspaces
    # castes has no lookup trigger, so the error must come from the RLS WITH CHECK itself
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="row-level security"):
        with app_conn.transaction():
            app_conn.execute("SELECT app.set_context(%s, %s, NULL)", (a["tenant"], a["user"]))
            app_conn.execute("INSERT INTO app.castes (tenant_id, name_mr) VALUES (%s, 'intruder')", (b["tenant"],))


def test_context_ends_with_transaction(app_conn, two_workspaces):
    a, _ = two_workspaces
    with app_conn.transaction():
        app_conn.execute("SELECT app.set_context(%s, NULL, NULL)", (a["tenant"],))
        assert app_conn.execute("SELECT count(*) FROM app.voters").fetchone()[0] >= 1
    # set_context is transaction-local: the next transaction starts blind again.
    assert app_conn.execute("SELECT count(*) FROM app.voters").fetchone()[0] == 0
