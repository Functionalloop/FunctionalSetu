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
  body         JSON body to send, or a function (world) -> body when it needs the shared data
  works        False: skip the "allowed role succeeds" check (covered in the endpoint's own tests)
  fresh_login  the call ends the session (logout): use a new login for the success check
  wipe_on_block a blocked phone gets 200 with wipe=true instead of 403 device_blocked (sync pull)
  query        query parameters sent with every call (required ones, e.g. date_from)
  item_id      the key of a list item that holds the record's id (default "id")
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
    body: dict[str, Any] | Callable[[Any], dict[str, Any]] | None = None
    works: bool = True
    fresh_login: bool = False
    wipe_on_block: bool = False
    stub: bool = False
    query: dict[str, Any] = field(default_factory=dict)
    item_id: str = "id"

    @property
    def label(self) -> str:
        return f"{self.method} {self.path}"


def _part_note_body(world) -> dict[str, Any]:
    """A save on top of the current version of workspace A's booth 1 note (each role saves in turn)."""
    row = world.conn.execute("SELECT version FROM app.part_notes WHERE booth_id = %s", (world.a.booths[0],)).fetchone()
    return {"note": "Rule check", "version": row[0] if row else 0}


def _new_voter_body(world) -> dict[str, Any]:
    """A record in workspace A's booth 1 (inside every test user's area)."""
    return {"full_name_en": "Rule Check", "ward_id": str(world.a.ward), "booth_id": str(world.a.booths[0])}


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
    # Kutumb Connect (7.1); behaviour and the booth list's isolation: test_families.py
    Endpoint("POST", "/families", roles=SURVEY_ROLES,
             body=lambda w: {"id": str(uuid.uuid4()), "booth_id": str(w.a.booths[0]), "label": "Rule check"}),
    Endpoint("PATCH", "/families/{family_id}", roles=SURVEY_ROLES, target="family", body={"label": "Renamed"}),
    Endpoint("GET", "/booths/{booth_id}/families", target="booth"),
    Endpoint("GET", "/voters/{voter_id}/family", target="voter"),
    Endpoint("PUT", "/voters/{voter_id}/family", roles=SURVEY_ROLES, target="voter", body={"leave_family": True}),
    # visits (7.3); behaviour: test_visits.py
    Endpoint("POST", "/voters/{voter_id}/visits", roles=SURVEY_ROLES, target="voter",
             body=lambda w: {"id": str(uuid.uuid4()), "outcome": "not_home", "visited_at": "2026-11-13T10:00:00Z"}),
    # Eligible but Not Registered (7.5); behaviour: test_new_voters.py
    Endpoint("GET", "/new-voters", roles=SURVEY_ROLES, lists="new_voter", area_params=("ward_id",)),
    Endpoint("POST", "/new-voters", roles=SURVEY_ROLES,
             body=lambda w: {"id": str(uuid.uuid4()), **_new_voter_body(w)}),
    Endpoint("PATCH", "/new-voters/{new_voter_id}", roles=SURVEY_ROLES, target="new_voter",
             body=lambda w: {"version": 1, **_new_voter_body(w), "form6_status": "applied"}),
    # Information Updation (7.6); behaviour: test_history.py
    Endpoint("GET", "/voters/{voter_id}/history", target="voter"),
    # part notes (7.11); behaviour: test_part_notes.py. The target is the place's booth.
    Endpoint("GET", "/booths/{booth_id}/note", target="part_note"),
    Endpoint("PUT", "/booths/{booth_id}/note", roles=SURVEY_ROLES, target="part_note", body=_part_note_body),
    # conflict review (7.10); behaviour: test_conflicts.py. The rows here are survey1's (own for a surveyor).
    Endpoint("GET", "/sync/conflicts", roles=SURVEY_ROLES, lists="conflict"),
    Endpoint("POST", "/sync/conflicts/{conflict_id}/resolve", roles=SURVEY_ROLES, target="conflict",
             body={"keep": "kept_server"}),
    # More menu (7.9); behaviour: test_misc.py. No terms text in the test database: 404 (own tests load one).
    Endpoint("GET", "/terms/current", level="public", works=False),
    Endpoint("POST", "/terms/accept", level="active", body={"version": 1}, works=False),
    Endpoint("GET", "/announcements", lists="announcement"),
    Endpoint("POST", "/announcements/{announcement_id}/read", target="announcement"),
    Endpoint("POST", "/problem-reports", level="active", body={"body": "Rule check"}),
    # birthdays (7.8); behaviour: test_birthdays.py
    Endpoint("GET", "/birthdays", lists="voter_birthday", area_params=("booth_id",), item_id="voter_id",
             query={"date_from": "2026-01-01", "date_to": "2026-12-31"}),
    # voter slips (7.7); behaviour: test_slips.py
    Endpoint("POST", "/voters/{voter_id}/slip-events", target="voter",
             body=lambda w: {"id": str(uuid.uuid4()), "channel": "whatsapp", "at": "2026-11-13T10:00:00Z"}),
    # polling day (8.1): not surveyors; behaviour: test_turnout.py. Serial 1 may have no voter (not_found_serials).
    Endpoint("GET", "/turnout/summary", roles=POLLING_ROLES, area_params=("ward_id", "booth_id")),
    Endpoint("POST", "/turnout/marks", roles=POLLING_ROLES,
             body=lambda w: {"id": str(uuid.uuid4()), "booth_id": str(w.a.booths[0]), "serials": "1"}),
    Endpoint("DELETE", "/turnout/marks/{voter_id}", roles=POLLING_ROLES, target="voter"),
    # users (9.1); behaviour: test_users.py. The target is a surveyor of that place's constituency.
    Endpoint("GET", "/users", roles=ADMINS, lists="user"),
    Endpoint("POST", "/users", roles=ADMINS,
             body=lambda w: {"username": f"r{uuid.uuid4().hex[:12]}", "full_name_en": "Rule Check",
                             "role": "surveyor", "local_body_id": str(w.a.local_body)}),
    Endpoint("GET", "/users/{user_id}", roles=ADMINS, target="user"),
    Endpoint("PATCH", "/users/{user_id}", roles=ADMINS, target="user", body={"full_name_mr": "Rule"}),
    Endpoint("POST", "/users/{user_id}/reset-password", roles=ADMINS, target="user"),
    # assignments (9.2); behaviour: test_assignments.py
    Endpoint("GET", "/users/{user_id}/assignments", roles=ADMINS, target="user"),
    Endpoint("PUT", "/users/{user_id}/assignments", roles=ADMINS, target="user",
             body=lambda w: {"area_ids": [str(w.a.booths[0])]}),
] + [Endpoint(m, p, roles=r, level=lv, stub=True) for m, p, r, lv in [
    # --- contract only (4.10); roles from the API document's "Who" column ---------------------------
    # field work (7)
    ("GET", "/families", ALL, "ready"),
    ("GET", "/voters/{voter_id}/slip", ALL, "ready"),
    # More menu (7.9)
    # admin (9)
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


def _make_user(world, where: str) -> uuid.UUID:
    """A surveyor in that place's constituency."""
    tenant, lb, _, _ = world.place(where)
    uid = uuid.uuid4()
    world.conn.execute(
        """INSERT INTO app.users (id, tenant_id, username, full_name_en, role, local_body_id, password_hash)
           VALUES (%s, %s, %s, 'Rule Person', 'surveyor', %s, 'x')""",
        (uid, tenant, f"p{uid.hex[:12]}", lb))
    return uid


def _user_state(world, user_id: uuid.UUID):
    return (world.conn.execute("""SELECT full_name_mr, role, is_active, password_hash, updated_at
                                    FROM app.users WHERE id = %s""", (user_id,)).fetchone(),
            world.conn.execute("""SELECT array_agg(geo_unit_id ORDER BY geo_unit_id) FROM app.user_area_assignments
                                   WHERE user_id = %s""", (user_id,)).fetchone()[0])


def _device_state(world, device_id: uuid.UUID):
    return world.conn.execute("SELECT status, decided_at FROM app.devices WHERE id = %s", (device_id,)).fetchone()


def _voter_state(world, voter_id: uuid.UUID):
    """The voter's survey row (None until the first save), Kutumb row (None until first put in one),
    number of visits and voted mark (None until marked)."""
    return (world.conn.execute("SELECT version, notes, updated_at FROM app.voter_surveys WHERE voter_id = %s",
                               (voter_id,)).fetchone(),
            world.conn.execute("SELECT family_id, updated_at FROM app.family_members WHERE voter_id = %s",
                               (voter_id,)).fetchone(),
            world.conn.execute("SELECT count(*) FROM app.visits WHERE voter_id = %s", (voter_id,)).fetchone()[0],
            world.conn.execute("SELECT is_voted, updated_at FROM app.voter_turnout WHERE voter_id = %s",
                               (voter_id,)).fetchone())


def _make_family(world, where: str) -> uuid.UUID:
    """A hand-made Kutumb in that place's booth."""
    tenant, _, ward, booth = world.place(where)
    fid = uuid.uuid4()
    world.conn.execute(
        """INSERT INTO app.families (id, tenant_id, ward_id, booth_id, label, source)
           VALUES (%s, %s, %s, %s, 'Rule Kutumb', 'manual')""", (fid, tenant, ward, booth))
    return fid


def _family_state(world, family_id: uuid.UUID):
    return world.conn.execute("SELECT label, updated_at FROM app.families WHERE id = %s", (family_id,)).fetchone()


def _make_new_voter(world, where: str) -> uuid.UUID:
    """An Eligible but Not Registered record in that place's booth, made by the workspace's super admin."""
    tenant, _, ward, booth = world.place(where)
    ws = world.a if tenant == world.a.tenant else world.b
    nid = uuid.uuid4()
    world.conn.execute(
        """INSERT INTO app.new_voters (id, tenant_id, full_name_en, ward_id, booth_id, created_by)
           VALUES (%s, %s, 'Rule Person', %s, %s, %s)""", (nid, tenant, ward, booth, ws.users["boss"]))
    return nid


def _new_voter_state(world, new_voter_id: uuid.UUID):
    return world.conn.execute("SELECT version, form6_status, updated_at FROM app.new_voters WHERE id = %s",
                              (new_voter_id,)).fetchone()


def _make_voter_birthday(world, where: str) -> uuid.UUID:
    """A voter whose survey has a date of birth (birthdays come from the survey)."""
    vid = _make_voter(world, where)
    tenant = world.place(where)[0]
    world.conn.execute("INSERT INTO app.voter_surveys (voter_id, tenant_id, dob) VALUES (%s, %s, '1980-06-15')",
                       (vid, tenant))
    return vid


def _make_part_note(world, where: str) -> uuid.UUID:
    """The place's booth (a part note is reached by its booth id)."""
    return world.place(where)[3]


def _part_note_state(world, booth_id: uuid.UUID):
    return world.conn.execute("SELECT note, version FROM app.part_notes WHERE booth_id = %s", (booth_id,)).fetchone()


def _make_conflict(world, where: str) -> uuid.UUID:
    """An open survey conflict on a voter of that place, from a push by the workspace's surveyor."""
    vid = _make_voter(world, where)
    tenant = world.place(where)[0]
    ws = world.a if tenant == world.a.tenant else world.b
    world.conn.execute("INSERT INTO app.voter_surveys (voter_id, tenant_id, notes) VALUES (%s, %s, 'server')",
                       (vid, tenant))
    cid = uuid.uuid4()
    world.conn.execute("""INSERT INTO app.sync_conflicts (id, tenant_id, entity_type, entity_id, field_name,
                                 client_value, server_value, client_user_id)
                          VALUES (%s, %s, 'voter_survey', %s, 'notes', '"phone"', '"server"', %s)""",
                       (cid, tenant, vid, ws.users["survey1"]))
    return cid


def _conflict_state(world, conflict_id: uuid.UUID):
    return world.conn.execute("""SELECT c.status, c.resolved_by, s.notes, s.version FROM app.sync_conflicts c
                                 JOIN app.voter_surveys s ON s.voter_id = c.entity_id WHERE c.id = %s""",
                              (conflict_id,)).fetchone()


def _make_announcement(world, where: str) -> uuid.UUID:
    """An announcement for that place's booth, by the workspace's super admin."""
    tenant, _, _, booth = world.place(where)
    ws = world.a if tenant == world.a.tenant else world.b
    aid = uuid.uuid4()
    world.conn.execute("""INSERT INTO app.announcements (id, tenant_id, body, audience_geo_id, created_by)
                          VALUES (%s, %s, 'Rule notice', %s, %s)""", (aid, tenant, booth, ws.users["boss"]))
    return aid


def _announcement_state(world, announcement_id: uuid.UUID):
    return world.conn.execute("SELECT count(*) FROM app.announcement_reads WHERE announcement_id = %s",
                              (announcement_id,)).fetchone()


def _booth(world, where: str) -> uuid.UUID:
    return world.place(where)[3]


KINDS: dict[str, Kind] = {
    "voter": Kind(_make_voter, _voter_state),
    "device": Kind(_make_device, _device_state),
    "user": Kind(_make_user, _user_state),
    "family": Kind(_make_family, _family_state),
    "booth": Kind(_booth),
    "new_voter": Kind(_make_new_voter, _new_voter_state),
    "voter_birthday": Kind(_make_voter_birthday),
    "announcement": Kind(_make_announcement, _announcement_state),
    "conflict": Kind(_make_conflict, _conflict_state),
    "part_note": Kind(_make_part_note, _part_note_state),
}
