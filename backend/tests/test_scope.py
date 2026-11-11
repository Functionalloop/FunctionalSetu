"""Area scope (app/scope.py) and the role-list check (require_roles in app/deps.py)."""

from __future__ import annotations

import uuid

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import transaction
from app.deps import POLLING_ROLES, SURVEY_ROLES, Principal, check_roles, require_roles
from app.errors import ApiError
from app.main import create_app
from app.schemas import Role
from app.scope import Scope, UserScope, load_scope, require_area
from conftest import bearer, login, phone

API = "/api/v1"


def principal(ws, username: str, role: Role) -> Principal:
    return Principal(user_id=ws.users[username], tenant_id=ws.tenant, session_id=uuid.uuid4(),
                     device_id=None, role=role, username=username,
                     local_body_id=None if role == Role.super_admin else ws.local_body,
                     must_change_password=False, device_status="approved")


def scope_of(ws, username: str, role: Role) -> Scope:
    p = principal(ws, username, role)
    with transaction(ws.tenant, p.user_id) as conn:  # as jansetu_app, RLS applies
        return load_scope(conn, p)


def booths_in(ws, scope: Scope) -> set[uuid.UUID]:
    cond, params = scope.filter("g.path")
    with transaction(ws.tenant) as conn:
        rows = conn.execute(text(f"SELECT g.id FROM app.geo_units g WHERE g.level = 'booth' AND {cond}"),
                            params).scalars()
        return set(rows)


def add_voter(owner_conn, ws, booth: uuid.UUID, serial: int) -> uuid.UUID:
    vid = uuid.uuid4()
    owner_conn.execute(
        """INSERT INTO app.voters (id, tenant_id, local_body_id, ward_id, booth_id, part_no, serial_no,
                                   gender, first_name_en, last_name_en)
           VALUES (%s, %s, %s, %s, %s, 1, %s, 'F', 'Test', 'Voter')""",
        (vid, ws.tenant, ws.local_body, ws.ward, booth, serial))
    return vid


def assign(owner_conn, ws, username: str, geo_unit: uuid.UUID) -> None:
    owner_conn.execute(
        "INSERT INTO app.user_area_assignments (tenant_id, user_id, geo_unit_id) VALUES (%s, %s, %s)",
        (ws.tenant, ws.users[username], geo_unit))


# --- scope per role ----------------------------------------------------------------
def test_surveyor_scope_holds_only_booth_1(make_workspace, owner_conn):
    ws = make_workspace("sv")
    v1 = add_voter(owner_conn, ws, ws.booths[0], 1)
    add_voter(owner_conn, ws, ws.booths[1], 1)

    s = scope_of(ws, "survey1", Role.surveyor)
    assert not s.whole_workspace
    assert s.area_ids == {ws.booths[0]}
    assert booths_in(ws, s) == {ws.booths[0]}

    cond, params = s.filter("v.geo_path")
    with transaction(ws.tenant) as conn:
        seen = set(conn.execute(text(f"SELECT v.id FROM app.voters v WHERE {cond}"), params).scalars())
    assert seen == {v1}


def test_supervisor_scope_is_the_ward_and_its_booths(make_workspace):
    ws = make_workspace("sup")
    s = scope_of(ws, "sup1", Role.supervisor)
    assert s.area_ids == {ws.ward}
    assert booths_in(ws, s) == set(ws.booths)


def test_admin_scope_is_own_constituency_only(make_workspace, owner_conn):
    ws = make_workspace("adm")
    other_lb = uuid.uuid4()
    owner_conn.execute(
        """INSERT INTO app.geo_units (id, tenant_id, level, code, name_mr, name_en)
           VALUES (%s, %s, 'local_body', '2', 'LB2', 'LB2')""", (other_lb, ws.tenant))
    other_ward = uuid.uuid4()
    owner_conn.execute(
        """INSERT INTO app.geo_units (id, tenant_id, parent_id, level, code, number, name_mr)
           VALUES (%s, %s, %s, 'ward', '1', 1, 'W')""", (other_ward, ws.tenant, other_lb))

    s = scope_of(ws, "admin1", Role.admin)
    assert s.area_ids == {ws.local_body}
    assert booths_in(ws, s) == set(ws.booths)
    with transaction(ws.tenant) as conn:
        assert require_area(conn, s, ws.ward)
        with pytest.raises(ApiError) as e:
            require_area(conn, s, other_ward)
    assert e.value.status == 404


def test_super_admin_sees_whole_workspace_but_not_another(make_workspace):
    a, b = make_workspace("sa-a"), make_workspace("sa-b")
    s = scope_of(a, "boss", Role.super_admin)
    assert s.whole_workspace
    assert s.filter("g.path") == ("TRUE", {})
    assert booths_in(a, s) == set(a.booths)  # RLS keeps B's booths out
    with transaction(a.tenant) as conn, pytest.raises(ApiError):
        require_area(conn, s, b.booths[0])


def test_no_assignment_means_empty_scope(make_workspace):
    ws = make_workspace("none", extra_users={"agent1": "booth_agent"})
    s = scope_of(ws, "agent1", Role.booth_agent)
    assert s.is_empty
    assert s.filter("g.path") == ("FALSE", {})
    assert booths_in(ws, s) == set()


def test_booth_inside_assigned_ward_is_collapsed(make_workspace, owner_conn):
    ws = make_workspace("nest")
    assign(owner_conn, ws, "sup1", ws.booths[0])  # already has the ward
    s = scope_of(ws, "sup1", Role.supervisor)
    assert s.area_ids == {ws.ward, ws.booths[0]}
    assert len(s.paths) == 1
    assert booths_in(ws, s) == set(ws.booths)


def test_inactive_booth_leaves_the_scope(make_workspace, owner_conn):
    ws = make_workspace("inact")
    assign(owner_conn, ws, "survey1", ws.booths[1])
    owner_conn.execute("UPDATE app.geo_units SET is_active = false WHERE id = %s", (ws.booths[1],))
    s = scope_of(ws, "survey1", Role.surveyor)
    assert s.area_ids == {ws.booths[0]}
    with transaction(ws.tenant) as conn, pytest.raises(ApiError):
        require_area(conn, s, ws.booths[1])


def test_booth_under_inactive_ward_leaves_the_scope(make_workspace, owner_conn):
    ws = make_workspace("inward")
    owner_conn.execute("UPDATE app.geo_units SET is_active = false WHERE id = %s", (ws.ward,))
    assert scope_of(ws, "survey1", Role.surveyor).is_empty  # booth 1 itself is still active
    admin = scope_of(ws, "admin1", Role.admin)
    with transaction(ws.tenant) as conn, pytest.raises(ApiError):
        require_area(conn, admin, ws.booths[0])


def test_assignment_outside_own_constituency_is_ignored(make_workspace, owner_conn):
    ws = make_workspace("out")
    lb2, ward2 = uuid.uuid4(), uuid.uuid4()
    owner_conn.execute(
        """INSERT INTO app.geo_units (id, tenant_id, level, code, name_mr) VALUES (%s, %s, 'local_body', '9', 'X')""",
        (lb2, ws.tenant))
    owner_conn.execute(
        """INSERT INTO app.geo_units (id, tenant_id, parent_id, level, code, number, name_mr)
           VALUES (%s, %s, %s, 'ward', '1', 1, 'W')""", (ward2, ws.tenant, lb2))
    assign(owner_conn, ws, "survey1", ward2)
    s = scope_of(ws, "survey1", Role.surveyor)
    assert s.area_ids == {ws.booths[0]}


def test_require_area_for_surveyor(make_workspace):
    ws = make_workspace("req")
    s = scope_of(ws, "survey1", Role.surveyor)
    with transaction(ws.tenant) as conn:
        assert require_area(conn, s, ws.booths[0])
        for outside in (ws.booths[1], ws.ward, uuid.uuid4()):
            with pytest.raises(ApiError) as e:
                require_area(conn, s, outside)
            assert e.value.status == 404 and e.value.code == "not_found"


def test_filter_refuses_odd_column_names():
    s = Scope(False, frozenset(), ("u1",))
    with pytest.raises(ValueError):
        s.filter("path; DROP TABLE x")


# --- role lists ---------------------------------------------------------------------
@pytest.mark.parametrize("role, survey, polling", [
    (Role.super_admin, True, True),
    (Role.admin, True, True),
    (Role.supervisor, True, True),
    (Role.surveyor, True, False),
    (Role.booth_agent, False, True),
])
def test_role_lists(role, survey, polling):
    p = Principal(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), None, role, "x", None, False, "approved")
    for roles, allowed in ((SURVEY_ROLES, survey), (POLLING_ROLES, polling)):
        if allowed:
            check_roles(p, roles)
        else:
            with pytest.raises(ApiError) as e:
                check_roles(p, roles)
            assert e.value.status == 403 and e.value.code == "forbidden_role"


def test_require_roles_needs_a_role():
    with pytest.raises(ValueError):
        require_roles()


# --- through HTTP: both dependencies on a real request --------------------------------
@pytest.fixture
def scope_client() -> TestClient:
    app = create_app()

    @app.get(f"{API}/_test/survey-scope")
    def survey_scope(scope: UserScope, user: Principal = Depends(require_roles(SURVEY_ROLES))):
        return {"role": user.role, "areas": sorted(str(a) for a in scope.area_ids)}

    @app.get(f"{API}/_test/polling")
    def polling(user: Principal = Depends(require_roles(POLLING_ROLES))):
        return {"role": user.role}

    return TestClient(app)


def phone_login(client, ws, username: str, set_device_status, uid: str) -> dict:
    t = login(client, ws, username, device=phone(uid)).json()
    set_device_status(t["device"]["id"], "approved")
    return t


def test_booth_agent_passes_only_where_listed(scope_client, make_workspace, owner_conn, set_device_status):
    ws = make_workspace("http", extra_users={"agent1": "booth_agent"})
    assign(owner_conn, ws, "agent1", ws.booths[1])

    agent = phone_login(scope_client, ws, "agent1", set_device_status, "phone-agent-0001")
    r = scope_client.get(f"{API}/_test/survey-scope", headers=bearer(agent))
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden_role"
    assert scope_client.get(f"{API}/_test/polling", headers=bearer(agent)).status_code == 200

    surveyor = phone_login(scope_client, ws, "survey1", set_device_status, "phone-surv-0001")
    r = scope_client.get(f"{API}/_test/survey-scope", headers=bearer(surveyor))
    assert r.status_code == 200 and r.json()["areas"] == [str(ws.booths[0])]
    assert scope_client.get(f"{API}/_test/polling", headers=bearer(surveyor)).status_code == 403
