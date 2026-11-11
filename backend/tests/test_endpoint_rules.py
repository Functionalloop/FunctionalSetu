"""Generic checks run on every endpoint in tests/endpoints.py.

For each row: no token / bad token -> 401; pending phone, password not changed,
blocked phone -> 403 (as its level says); every role not listed -> 403
forbidden_role; every listed role succeeds; a record in another workspace or
another area -> 404; malformed id -> 422; unknown id -> 404; refused writes
change nothing; lists never contain another area's or workspace's records.
All errors must have the standard shape.

One shared set of fake data is built once for this file (World) and each check
makes the records it needs, so the checks do not depend on each other.
"""

from __future__ import annotations

import itertools
import re
import uuid
from dataclasses import dataclass, field

import pytest

from app.main import API_PREFIX, create_app
from app.schemas import Role
from conftest import Workspace, _connect, bearer, create_workspace, login, phone
from endpoints import ENDPOINTS, KINDS, PATH_SAMPLES, QUERY_SAMPLES, Endpoint

USERNAME = {Role.super_admin: "boss", Role.admin: "admin1", Role.supervisor: "sup1",
            Role.surveyor: "survey1", Role.booth_agent: "agent1"}


# --- shared fake data -----------------------------------------------------------------
@dataclass
class World:
    conn: object
    client: object
    a: Workspace
    b: Workspace
    lb2: uuid.UUID = field(default_factory=uuid.uuid4)
    ward2: uuid.UUID = field(default_factory=uuid.uuid4)
    booth2: uuid.UUID = field(default_factory=uuid.uuid4)
    tokens: dict[str, dict] = field(default_factory=dict)
    _serial: itertools.count = field(default_factory=lambda: itertools.count(1))

    def next_serial(self) -> int:
        return next(self._serial)

    def place(self, where: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
        """(tenant, constituency, ward, booth) for "own", "other_area" or "other_ws"."""
        if where == "own":
            return self.a.tenant, self.a.local_body, self.a.ward, self.a.booths[0]
        if where == "other_area":
            return self.a.tenant, self.lb2, self.ward2, self.booth2
        return self.b.tenant, self.b.local_body, self.b.ward, self.b.booths[0]

    def area(self, param: str, where: str) -> uuid.UUID:
        _, _, ward, booth = self.place(where)
        return ward if param.startswith("ward") else booth

    def phone_login(self, ws: Workspace, username: str, status: str | None = "approved") -> dict:
        t = login(self.client, ws, username, device=phone(f"rules-{ws.code}-{username}"))
        assert t.status_code == 200, t.text
        t = t.json()
        if status:
            self.conn.execute(
                """UPDATE app.devices SET status = %s, decided_at = now(),
                          wipe_requested_at = CASE WHEN %s = 'blocked' THEN now() END WHERE id = %s""",
                (status, status, t["device"]["id"]))
        return t


@pytest.fixture(scope="module")
def world(test_database, client):
    with _connect("jansetu_owner", "JANSETU_OWNER_PASSWORD", autocommit=True) as conn:
        a = create_workspace(conn, "rules", must_change=("chg1",), extra_users={
            "agent1": "booth_agent", "pend1": "surveyor", "blk1": "surveyor", "chg1": "supervisor"})
        b = create_workspace(conn, "rules-b")
        w = World(conn, client, a, b)
        conn.execute("""INSERT INTO app.user_area_assignments (tenant_id, user_id, geo_unit_id)
                        VALUES (%s, %s, %s)""", (a.tenant, a.users["agent1"], a.booths[0]))
        geo = """INSERT INTO app.geo_units (id, tenant_id, parent_id, level, code, number, name_mr)
                 VALUES (%s, %s, %s, %s, %s, %s, 'X')"""
        conn.execute(geo, (w.lb2, a.tenant, None, "local_body", "2", None))
        conn.execute(geo, (w.ward2, a.tenant, w.lb2, "ward", "1", 1))
        conn.execute(geo, (w.booth2, a.tenant, w.ward2, "booth", "2001", 1))

        for role, username in USERNAME.items():
            w.tokens[role] = w.phone_login(a, username)
        w.tokens["b_boss"] = login(client, b, "boss").json()
        w.tokens["pending"] = w.phone_login(a, "pend1", status=None)
        w.tokens["blocked"] = w.phone_login(a, "blk1", status="blocked")
        w.tokens["must_change"] = w.phone_login(a, "chg1")
        yield w


# --- helpers ------------------------------------------------------------------------------
def fill_path(ep: Endpoint, target_id=None) -> str:
    """Path with its parameters: the target's id, or sample values for stub routes."""
    if ep.target:
        return re.sub(r"\{[^}]+\}", str(target_id), ep.path)
    return re.sub(r"\{([^}]+)\}", lambda m: PATH_SAMPLES.get(m.group(1), str(uuid.uuid4())), ep.path)


def call(world: World, ep: Endpoint, token: dict | None, target_id=None, params=None, raw_auth=None):
    headers = {"Authorization": raw_auth} if raw_auth else (bearer(token) if token else {})
    if params is None and ep.stub:
        params = QUERY_SAMPLES.get(ep.path)
    return world.client.request(ep.method, API_PREFIX + fill_path(ep, target_id), headers=headers, params=params,
                                json=ep.body)


def assert_error(r, status: int, code: str | None = None) -> None:
    assert r.status_code == status, f"expected {status}, got {r.status_code}: {r.text}"
    body = r.json()
    assert set(body) == {"error"}, body
    assert isinstance(body["error"].get("code"), str) and isinstance(body["error"].get("message"), str), body
    if code:
        assert body["error"]["code"] == code, body


def own_target(world: World, ep: Endpoint):
    return KINDS[ep.target].make(world, "own") if ep.target else None


def state(world: World, ep: Endpoint, target_id):
    return KINDS[ep.target].state(world, target_id) if ep.target else None


def params(pred) -> list:
    return [pytest.param(e, id=e.label) for e in ENDPOINTS if pred(e)]


def role_params(pred, allowed: bool) -> list:
    return [pytest.param(e, r, id=f"{e.label} as {r.value}")
            for e in ENDPOINTS if pred(e) for r in Role if (r in e.roles) == allowed]


def needs_login(e: Endpoint) -> bool:
    return e.level != "public"


# --- the table covers the API ------------------------------------------------------------
def test_every_route_is_in_the_table():
    # From the OpenAPI schema: included routers are not flattened into app.routes in this FastAPI version.
    paths = create_app().openapi()["paths"]
    served = {(m.upper(), p.removeprefix(API_PREFIX)) for p, ops in paths.items() for m in ops}
    assert len(served) >= 11
    listed = {(e.method, e.path) for e in ENDPOINTS}
    assert served - listed == set(), "add these routes to tests/endpoints.py"
    assert listed - served == set(), "these rows in tests/endpoints.py match no route"
    assert len(listed) == len(ENDPOINTS), "duplicate rows in tests/endpoints.py"
    for e in ENDPOINTS:
        assert e.target is None or e.target in KINDS
        assert e.lists is None or e.lists in KINDS


# --- login state ----------------------------------------------------------------------------
@pytest.mark.parametrize("ep", params(needs_login))
def test_no_token(world, ep):
    assert_error(call(world, ep, None, own_target(world, ep)), 401, "not_authenticated")


@pytest.mark.parametrize("ep", params(needs_login))
def test_bad_token(world, ep):
    assert_error(call(world, ep, None, own_target(world, ep), raw_auth="Bearer not.a.token"), 401, "invalid_token")


@pytest.mark.parametrize("ep", params(lambda e: e.level == "ready"))
def test_pending_phone(world, ep):
    assert_error(call(world, ep, world.tokens["pending"], own_target(world, ep)), 403, "device_pending")


@pytest.mark.parametrize("ep", params(lambda e: e.level == "ready"))
def test_password_not_changed(world, ep):
    assert_error(call(world, ep, world.tokens["must_change"], own_target(world, ep)), 403,
                 "password_change_required")


@pytest.mark.parametrize("ep", params(lambda e: e.level in ("active", "ready") and not e.wipe_on_block))
def test_blocked_phone(world, ep):
    assert_error(call(world, ep, world.tokens["blocked"], own_target(world, ep)), 403, "device_blocked")


@pytest.mark.parametrize("ep", params(lambda e: e.wipe_on_block))
def test_blocked_phone_is_told_to_wipe(world, ep):
    r = call(world, ep, world.tokens["blocked"], own_target(world, ep))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["wipe"] is True and body["next_cursor"] is None
    assert not body["voters"] and not body["surveys"] and not body["areas"] and body["lists"] is None


# --- roles --------------------------------------------------------------------------------------
@pytest.mark.parametrize("ep, role", role_params(needs_login, allowed=False))
def test_role_refused(world, ep, role):
    tid = own_target(world, ep)
    before = state(world, ep, tid)
    assert_error(call(world, ep, world.tokens[role], tid), 403, "forbidden_role")
    assert state(world, ep, tid) == before


@pytest.mark.parametrize("ep, role", role_params(lambda e: needs_login(e) and e.works, allowed=True))
def test_role_allowed(world, ep, role):
    token = world.tokens[role]
    if ep.fresh_login:
        token = world.phone_login(world.a, USERNAME[role], status=None)  # same phone, still approved
    r = call(world, ep, token, own_target(world, ep))
    if ep.stub:  # passed login and the role check, reached the stub
        if r.status_code == 422 and ep.method in ("POST", "PUT", "PATCH") and ep.body is None:
            assert_error(r, 422, "validation_error")  # no sample body: the body check comes after the role check
        else:
            assert_error(r, 501, "not_implemented")
        return
    assert r.status_code < 400, r.text


@pytest.mark.parametrize("ep", params(lambda e: e.stub and e.level == "public"))
def test_public_stub_answers_without_login(world, ep):
    assert_error(call(world, ep, None), 501, "not_implemented")


def test_stub_flags_match_the_api():
    """A row is a stub exactly when its route still documents 501, so building a route flips both."""
    paths = create_app().openapi()["paths"]
    documented = {(m.upper(), p.removeprefix(API_PREFIX)) for p, ops in paths.items() for m, op in ops.items()
                  if "501" in op["responses"]}
    assert {(e.method, e.path) for e in ENDPOINTS if e.stub} == documented


# --- isolation ------------------------------------------------------------------------------------
@pytest.mark.parametrize("ep", params(lambda e: e.target))
def test_other_workspace_is_404(world, ep):
    tid = KINDS[ep.target].make(world, "other_ws")
    before = state(world, ep, tid)
    assert_error(call(world, ep, world.tokens[Role.super_admin], tid), 404, "not_found")
    assert state(world, ep, tid) == before


@pytest.mark.parametrize("ep, role", [p for p in role_params(lambda e: e.target, allowed=True)
                                      if p.values[1] != Role.super_admin])  # super admin: whole workspace
def test_other_area_is_404(world, ep, role):
    tid = KINDS[ep.target].make(world, "other_area")
    before = state(world, ep, tid)
    assert_error(call(world, ep, world.tokens[role], tid), 404, "not_found")
    assert state(world, ep, tid) == before


@pytest.mark.parametrize("ep", params(lambda e: e.target))
def test_malformed_id_is_422(world, ep):
    r = world.client.request(ep.method, API_PREFIX + re.sub(r"\{[^}]+\}", "not-a-uuid", ep.path),
                             headers=bearer(world.tokens[Role.super_admin]), json=ep.body)
    assert_error(r, 422, "validation_error")


@pytest.mark.parametrize("ep", params(lambda e: e.target))
def test_unknown_id_is_404(world, ep):
    assert_error(call(world, ep, world.tokens[Role.super_admin], uuid.uuid4()), 404, "not_found")


@pytest.mark.parametrize("ep, role", role_params(lambda e: e.lists, allowed=True))
def test_list_holds_only_own_records(world, ep, role):
    make = KINDS[ep.lists].make
    own, other_area, other_ws = make(world, "own"), make(world, "other_area"), make(world, "other_ws")
    seen, cursor = set(), None
    while True:
        r = call(world, ep, world.tokens[role], params={"limit": 200, **({"cursor": cursor} if cursor else {})})
        assert r.status_code == 200, r.text
        seen |= {uuid.UUID(i["id"]) for i in r.json()["items"]}
        cursor = r.json().get("next_cursor")
        if not cursor:
            break
    assert own in seen
    assert other_ws not in seen
    if role != Role.super_admin:
        assert other_area not in seen


@pytest.mark.parametrize("ep, role", role_params(lambda e: e.area_params, allowed=True))
def test_area_filter_outside_area_is_404(world, ep, role):
    booth_only = role in (Role.surveyor, Role.booth_agent)  # their area is booth 1, not the whole ward
    for p in ep.area_params:
        own = call(world, ep, world.tokens[role], params={p: str(world.area(p, "own"))})
        if booth_only and p.startswith("ward"):
            assert_error(own, 404, "not_found")
        else:
            assert own.status_code == 200, own.text
        outside = "other_ws" if role == Role.super_admin else "other_area"
        assert_error(call(world, ep, world.tokens[role], params={p: str(world.area(p, outside))}), 404, "not_found")
