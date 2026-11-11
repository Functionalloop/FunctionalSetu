"""The endpoint table for the generic checks in test_endpoint_rules.py.

Every route the API serves must have one row here (a test fails otherwise).
Adding an endpoint = add a row; its 401 / 403 / other-workspace / other-area
checks then run automatically. Endpoint logic (409, paging, search, ...) still
gets its own test file.

Row fields:
  roles        roles that may call it (anyone else: 403 forbidden_role)
  level        "public" (no login), "current" (any live session), "active" (+ phone not
               blocked), "ready" (+ password changed + phone approved). Matches app/deps.py.
  target       kind of record named by the path parameter, if any (see KINDS)
  lists        kind of record returned in `items` (list isolation is checked)
  area_params  query parameters that take an area id (404 outside the user's area)
  body         JSON body to send
  works        False: skip the "allowed role succeeds" check (covered in the endpoint's own tests)
  fresh_login  the call ends the session (logout): use a new login for the success check
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.deps import POLLING_ROLES, SURVEY_ROLES  # noqa: F401  (POLLING_ROLES: used by later rows)
from app.schemas import Role

ALL = frozenset(Role)
ADMINS = frozenset({Role.super_admin, Role.admin})


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    roles: frozenset[Role] = ALL
    level: str = "ready"
    target: str | None = None
    lists: str | None = None
    area_params: tuple[str, ...] = ()
    body: dict[str, Any] | None = None
    works: bool = True
    fresh_login: bool = False

    @property
    def label(self) -> str:
        return f"{self.method} {self.path}"


ENDPOINTS: list[Endpoint] = [
    # system and auth
    Endpoint("GET", "/health", level="public"),
    Endpoint("POST", "/auth/login", level="public"),
    Endpoint("POST", "/auth/refresh", level="public"),
    Endpoint("POST", "/auth/logout", level="current", fresh_login=True),
    Endpoint("POST", "/auth/change-password", level="active", works=False),  # test_auth.py
    Endpoint("GET", "/me"),
    # devices
    Endpoint("GET", "/devices/me", level="current"),
    Endpoint("GET", "/devices", roles=ADMINS, lists="device"),
    Endpoint("POST", "/devices/{device_id}/approve", roles=ADMINS, target="device"),
    Endpoint("POST", "/devices/{device_id}/block", roles=ADMINS, target="device", body={"reason": "Phone lost"}),
    # areas and voters
    Endpoint("GET", "/geo/tree"),  # tree isolation: test_geo.py
    Endpoint("GET", "/voters", lists="voter", area_params=("ward_id", "booth_id")),
    Endpoint("GET", "/voters/{voter_id}", target="voter"),
    Endpoint("PUT", "/voters/{voter_id}/survey", roles=SURVEY_ROLES, target="voter",
             body={"version": 0, "notes": "rule check"}),
]


# --- kinds of records the checks create ---------------------------------------------
# where: "own"        inside every test user's area (workspace A, booth 1)
#        "other_area" workspace A, second constituency (outside every role but super admin)
#        "other_ws"   workspace B


@dataclass
class Kind:
    make: Callable[[Any, str], uuid.UUID]                       # (world, where) -> id
    state: Callable[[Any, uuid.UUID], Any] = field(default=lambda w, i: None)  # read back after a refusal


def _make_voter(world, where: str) -> uuid.UUID:
    tenant, lb, ward, booth = world.place(where)
    vid = uuid.uuid4()
    world.conn.execute(
        """INSERT INTO app.voters (id, tenant_id, local_body_id, ward_id, booth_id, part_no, serial_no,
                                   gender, first_name_en, last_name_en)
           VALUES (%s, %s, %s, %s, %s, 1, %s, 'F', 'Rule', 'Check')""",
        (vid, tenant, lb, ward, booth, world.next_serial()))
    return vid


def _make_device(world, where: str) -> uuid.UUID:
    """A pending phone of a new surveyor in that place's constituency."""
    tenant, lb, _, _ = world.place(where)
    uid, did = uuid.uuid4(), uuid.uuid4()
    world.conn.execute(
        """INSERT INTO app.users (id, tenant_id, username, full_name_en, role, local_body_id, password_hash)
           VALUES (%s, %s, %s, 'Rule Check', 'surveyor', %s, 'x')""",
        (uid, tenant, f"u{uid.hex[:12]}", lb))
    world.conn.execute(
        "INSERT INTO app.devices (id, tenant_id, user_id, device_uid_hash) VALUES (%s, %s, %s, %s)",
        (did, tenant, uid, uuid.uuid4().hex * 2))
    return did


def _device_state(world, device_id: uuid.UUID):
    return world.conn.execute("SELECT status, decided_at FROM app.devices WHERE id = %s", (device_id,)).fetchone()


def _voter_state(world, voter_id: uuid.UUID):
    """The voter's survey row (None until the first save)."""
    return world.conn.execute("SELECT version, notes, updated_at FROM app.voter_surveys WHERE voter_id = %s",
                              (voter_id,)).fetchone()


KINDS: dict[str, Kind] = {
    "voter": Kind(_make_voter, _voter_state),
    "device": Kind(_make_device, _device_state),
}
