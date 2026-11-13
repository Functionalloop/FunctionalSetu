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
  wipe_on_block a blocked phone gets 200 with wipe=true instead of 403 device_blocked (sync pull)
  stub         contract only (4.10): an allowed role reaches it and gets 501 not_implemented (or 422 when
               the row has no sample body). Building it: drop `stub`, add `target` / `lists` and its own tests.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.deps import POLLING_ROLES, SURVEY_ROLES
from app.schemas import Role

ALL = frozenset(Role)
ADMINS = frozenset({Role.super_admin, Role.admin})
SUPERVISORS = frozenset({Role.super_admin, Role.admin, Role.supervisor})
SUPER = frozenset({Role.super_admin})


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
    wipe_on_block: bool = False
    stub: bool = False

    @property
    def label(self) -> str:
        return f"{self.method} {self.path}"


ENDPOINTS: list[Endpoint] = [
    # system and auth
    Endpoint("GET", "/health", level="public"),
    Endpoint("POST", "/auth/login", level="public"),
    Endpoint("POST", "/auth/refresh", level="public"),
    Endpoint("GET", "/app/version", level="public"),  # test_app_version.py
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
    # sync (area isolation of the pages: test_sync_pull.py)
    Endpoint("GET", "/sync/pull", wipe_on_block=True),
    Endpoint("POST", "/sync/push", body={"items": []}),  # per-item roles: test_sync_push.py
    Endpoint("PUT", "/voters/{voter_id}/survey", roles=SURVEY_ROLES, target="voter",
             body={"version": 0, "notes": "rule check"}),
] + [Endpoint(m, p, roles=r, level=lv, stub=True) for m, p, r, lv in [
    # --- contract only (4.10); roles from the API document's "Who" column ---------------------------
    # sync conflicts (7.10; who resolves: gap-table proposal)
    ("GET", "/sync/conflicts", SURVEY_ROLES, "ready"),
    ("POST", "/sync/conflicts/{conflict_id}/resolve", SURVEY_ROLES, "ready"),
    # field work (7)
    ("GET", "/voters/{voter_id}/family", ALL, "ready"),
    ("PUT", "/voters/{voter_id}/family", SURVEY_ROLES, "ready"),
    ("GET", "/families", ALL, "ready"),
    ("POST", "/families", SURVEY_ROLES, "ready"),
    ("PATCH", "/families/{family_id}", SURVEY_ROLES, "ready"),
    ("GET", "/booths/{booth_id}/families", ALL, "ready"),
    ("GET", "/booths/{booth_id}/note", ALL, "ready"),
    ("PUT", "/booths/{booth_id}/note", SURVEY_ROLES, "ready"),
    ("POST", "/voters/{voter_id}/visits", SURVEY_ROLES, "ready"),
    ("GET", "/new-voters", SURVEY_ROLES, "ready"),
    ("POST", "/new-voters", SURVEY_ROLES, "ready"),
    ("PATCH", "/new-voters/{new_voter_id}", SURVEY_ROLES, "ready"),
    ("GET", "/voters/{voter_id}/history", ALL, "ready"),
    ("POST", "/voters/{voter_id}/slip-events", ALL, "ready"),
    ("GET", "/voters/{voter_id}/slip", ALL, "ready"),
    ("GET", "/birthdays", ALL, "ready"),
    # More menu (7.9)
    ("GET", "/terms/current", ALL, "public"),
    ("POST", "/terms/accept", ALL, "active"),
    ("GET", "/announcements", ALL, "ready"),
    ("POST", "/announcements/{announcement_id}/read", ALL, "ready"),
    ("POST", "/problem-reports", ALL, "active"),
    # polling day (8.1): not surveyors
    ("GET", "/turnout/summary", POLLING_ROLES, "ready"),
    ("POST", "/turnout/marks", POLLING_ROLES, "ready"),
    ("DELETE", "/turnout/marks/{voter_id}", POLLING_ROLES, "ready"),
    # admin (9)
    ("GET", "/users", ADMINS, "ready"),
    ("POST", "/users", ADMINS, "ready"),
    ("GET", "/users/{user_id}", ADMINS, "ready"),
    ("PATCH", "/users/{user_id}", ADMINS, "ready"),
    ("POST", "/users/{user_id}/reset-password", ADMINS, "ready"),
    ("GET", "/users/{user_id}/assignments", ADMINS, "ready"),
    ("PUT", "/users/{user_id}/assignments", ADMINS, "ready"),
    ("GET", "/constituencies", SUPER, "ready"),
    ("POST", "/constituencies", SUPER, "ready"),
    ("PATCH", "/constituencies/{constituency_id}", SUPER, "ready"),
    ("GET", "/settings/election", ADMINS, "ready"),
    ("PUT", "/settings/election", ADMINS, "ready"),
    *[(m, f"/masters/{lst}{suffix}", ADMINS, "ready") for lst in ("castes", "professions", "color-tags")
      for m, suffix in (("GET", ""), ("POST", ""), ("PATCH", "/{entry_id}"))],
    ("GET", "/masters/custom-fields", ADMINS, "ready"),
    ("PATCH", "/masters/custom-fields/{field_key}", ADMINS, "ready"),
    ("GET", "/masters/message-templates", ADMINS, "ready"),
    ("PATCH", "/masters/message-templates/{kind}", ADMINS, "ready"),
    ("POST", "/files", ADMINS, "ready"),
    ("GET", "/files/{file_id}", ALL, "ready"),
    ("POST", "/announcements", ADMINS, "ready"),
    ("DELETE", "/announcements/{announcement_id}", ADMINS, "ready"),
    ("GET", "/problem-reports", ADMINS, "ready"),
    ("GET", "/audit-log", ADMINS, "ready"),
    ("GET", "/reports/worker-activity", ADMINS, "ready"),
    ("GET", "/worker-locations", ADMINS, "ready"),
    # roll and data quality (10); roll writes: super admin only (client, 12 Nov)
    ("POST", "/rolls/imports", SUPER, "ready"),
    ("GET", "/rolls/imports", ADMINS, "ready"),
    ("GET", "/rolls/imports/{import_id}", ADMINS, "ready"),
    ("GET", "/rolls/imports/{import_id}/rows", ADMINS, "ready"),
    ("POST", "/rolls/imports/{import_id}/rows/{row_id}/resolve", SUPER, "ready"),
    ("POST", "/rolls/imports/{import_id}/apply", SUPER, "ready"),
    ("POST", "/rolls/imports/{import_id}/discard", SUPER, "ready"),
    ("POST", "/voters", SUPER, "ready"),
    ("PATCH", "/voters/{voter_id}/roll", SUPER, "ready"),
    ("POST", "/voters/{voter_id}/remove", SUPER, "ready"),
    ("POST", "/voters/{voter_id}/restore", SUPER, "ready"),
    ("GET", "/voters/{voter_id}/roll-edits", ADMINS, "ready"),
    ("GET", "/data-quality/summary", SUPERVISORS, "ready"),
    ("GET", "/data-quality/duplicates", SUPERVISORS, "ready"),
    ("POST", "/data-quality/duplicates/{pair_id}/resolve", SUPERVISORS, "ready"),
    ("POST", "/mobile-imports", ADMINS, "ready"),
    ("GET", "/mobile-imports/{import_id}", ADMINS, "ready"),
    ("POST", "/mobile-imports/{import_id}/rows/{row_id}/resolve", ADMINS, "ready"),
    # reports and exports (11)
    ("GET", "/reports/survey-progress", SUPERVISORS, "ready"),
    ("GET", "/reports/colour-tags", SUPERVISORS, "ready"),
    ("GET", "/reports/demographics", SUPERVISORS, "ready"),
    ("GET", "/reports/turnout", SUPERVISORS, "ready"),
    ("POST", "/exports", SUPERVISORS, "ready"),
    ("GET", "/exports/{export_id}", SUPERVISORS, "ready"),
    ("GET", "/exports/{export_id}/download", SUPERVISORS, "ready"),
]]

# Sample values for path parameters of stub routes (built routes use `target`).
PATH_SAMPLES = {"row_id": "1", "field_key": "extra_check_1", "kind": "birthday"}
# Required query parameters of stub routes, so a call is well-formed.
QUERY_SAMPLES = {"/families": {"booth_id": str(uuid.UUID(int=1))},
                 "/birthdays": {"date_from": "2026-11-01"},
                 "/reports/worker-activity": {"date_from": "2026-11-01", "date_to": "2026-11-02"},
                 "/worker-locations": {"date_from": "2026-11-01", "date_to": "2026-11-02"}}


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
