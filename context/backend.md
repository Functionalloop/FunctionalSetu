# Backend

FastAPI + Pydantic v2 + SQLAlchemy 2 Core (no ORM) + psycopg 3. Code in `backend/app/`, tests in `backend/tests/`. API contract as built: `docs/openapi.json`.

## Commands

```
# dev DB must be up (see database.md); use the repo .venv
pip install -r requirements-dev.txt          # repo root
cd backend && pytest                         # 40 tests, ~10 s
uvicorn app.main:app --reload                # from backend/; docs at /api/v1/docs
python scripts/export_openapi.py             # after any API change; commit docs/openapi.json
```

`tests/test_openapi.py` fails if `docs/openapi.json` is out of date.

## Layout

| File | Purpose |
|---|---|
| `app/main.py` | `create_app()`, router wiring under `/api/v1`, CORS, error handlers, API description (error table) |
| `app/config.py` | `Settings` from env, falling back to `deploy/.env`. DB URL always user `jansetu_app` |
| `app/db.py` | `get_engine()`, `transaction(tenant, user, device)` = BEGIN + `app.set_context` |
| `app/deps.py` | `get_db` (one transaction per request), principal levels, `require_role` |
| `app/errors.py` | `ApiError(status, code, message)`; one JSON shape for all errors; `ERROR_RESPONSES` for OpenAPI |
| `app/security.py` | Argon2id hashing, JWT access token (15 min), refresh token helpers |
| `app/schemas.py` | All Pydantic request/response models, `Role` enum |
| `app/routers/` | `auth.py`, `me.py`, `devices.py`, `health.py`, `geo.py`, `voters.py`, `families.py`, `visits.py`, `new_voters.py`, `slips.py`, `birthdays.py`, `misc.py`, `part_notes.py`, `turnout.py`, `sync.py`, `app_version.py`; stubs in `field.py`, ... |

Operation ids are the function names (stable names for the portal's generated client). Add every router in `main.py` with `responses=errors.ERROR_RESPONSES`.

## Dependencies (`app/deps.py`)

Strictest last. Use the strictest that fits:

| Type | Checks |
|---|---|
| `CurrentUser` | valid, live session; account active; workspace active; device matches token |
| `ActiveUser` | + phone not `blocked`/`wiped` (`device_blocked`) |
| `ReadyUser` | + password changed (`password_change_required`) + phone approved (`device_pending`). **Every data endpoint uses this** |
| `require_role(Role.x)` | ReadyUser with rank >= x (`forbidden_role`) |

- `Db` is the request's transaction, RLS context already set. Commits before the response is sent.
- Rank: super_admin 4 > admin 3 > supervisor 2 > surveyor = booth_agent 1. Equal rank is **not** interchangeable, so work-specific endpoints use a role list instead:
  - `require_roles(SURVEY_ROLES)`: super_admin, admin, supervisor, surveyor (no booth agent).
  - `require_roles(POLLING_ROLES)`: super_admin, admin, supervisor, booth_agent (no surveyor).
  - `check_roles(principal, roles)` does the same check for a single item, e.g. one entry in a sync push batch.
- `last_seen_at` on the session is written at most once a minute.

Cursors: `app/paging.py` (`encode_cursor(list)`, `decode_cursor(cursor, n)` → 400 `invalid_cursor`). Use it for every list.

## Area scope (`app/scope.py`)

- Switched-off areas (`geo_units.is_active = false`) and everything below them are out of every scope, for every role: `Scope.excluded`, applied by `filter` and `contains_path`. `/me` areas come from the scope too.
- `UserScope` dependency → `Scope`. Super admin: whole workspace. Admin: own constituency. Others: assigned wards/booths that are active and inside their own constituency. Each area covers its subtree.
- `scope.filter("v.geo_path")` → `(sql_condition, params)` for any ltree column (`geo_units.path`, `voters.geo_path`). Returns `TRUE` / `FALSE` for whole/empty scope. Pass column names from code only.
- `require_area(conn, scope, geo_id)` → 404 `not_found` unless the area is active and in scope (use it for `ward=` / `booth=` filters).
- A user with no assignments has an empty scope (sees nothing), not an error.
- Tests build a scope directly with `load_scope` inside `app.db.transaction(...)` (RLS applies); see `tests/test_scope.py`.

## Error codes

Table is in `app/main.py` (`DESCRIPTION`). Add new codes there. Shape: `{"error": {"code", "message", "details"?}}`. Records outside your workspace or area return **404**, not 403.

## Endpoints built (base `/api/v1`)

| Route | Notes |
|---|---|
| `GET /health` | no auth |
| `POST /auth/login` | workspace code + user ID + password (+ `device` for surveyor/booth agent). Lockout after 5 wrong tries (15 min). Creates/updates the device row |
| `POST /auth/refresh` | rotating refresh token stored in `app.auth_sessions` |
| `POST /auth/logout` | 204 |
| `POST /auth/change-password` | 204; ends other sessions |
| `GET /me` | user, workspace, assigned areas, settings |
| `GET /devices/me` | phone polls this for approval; `CurrentUser` level |
| `POST /devices/{id}/approve`, `/block` | admin (own constituency); block sets the wipe signal |
| `GET /devices` | admin (own constituency) / super admin (all). `?status=`, newest request first, cursor on (requested_at, id). Items add username, full_name_en, role, last_seen_at |
| `GET /app/version` | public (no token; a bad token is ignored). Newest `app_releases` row; `min_version_code` = newest `is_required` release, else 1; `apk_url` absolute from the request's address (`/download/<file>`). 404 `not_found` while none is published. Router `app_version.py`. Releases are written only by `scripts/publish_apk.py` (owner) |
| `GET /geo/tree` | all roles; `{"roots": [GeoNode]}` nested by `children`. Roots = the scope's top areas (super admin: every constituency; supervisor: the assigned ward, no parent above it). Inactive areas and their subtree are left out. Not paged (real roll: ~300 areas) |

| `GET /voters` | all roles, area scope. Filters `q`, `ward_id`, `booth_id` (404 outside scope), `age_min/max`, `gender`, `color_tag_id`, `survey_status`, `caste_id`, `profession_id`, `has_mobile`, `influencer`, `influencer_type_id` (7.13; `important` is gone, and like any unknown parameter it is ignored). Roll order (part, booth, serial, id), keyset cursor (opaque base64), `limit` 1–200. Removed voters (`deleted_at`) never listed. "voted" filter comes with step 8 |

| `GET /voters/{voter_id}` | all roles, area scope (404 outside, removed or other workspace). Roll fields + `survey` (null until first save) |
| `PUT /voters/{voter_id}/survey` | `SURVEY_ROLES` (booth agent 403). PUT replaces every editable field (left out = cleared), except `location`: left out = previous kept, given = `location_captured_at` now. `version` 0 = first save (INSERT … ON CONFLICT DO NOTHING); else `UPDATE … WHERE version = :v` (trigger bumps it). Zero rows → 409 `version_conflict` with `error.current` = server copy (null if none). Caste / profession / colour tag must be active entries of the workspace, else 422 |
| `GET /sync/pull` | first download and delta (`since`), blocked phone gets `wipe: true`; see `context/sync.md`. Endpoint-table flag `wipe_on_block`. Settings load via `app/workspace_settings.py` (shared with `/me`) |
| `GET/PUT /booths/{id}/note` | 7.11, `routers/part_notes.py`. One note per part (`part_notes`, unique booth, up to 2,000 characters). GET: all roles, 404 if the booth is not in the area; none yet = version 0 and "". PUT: survey roles, `{note, version}` (0 = none yet: insert, ON CONFLICT on the booth = stale); stale = 409 `version_conflict` with `current`. Version bumped by the `part_notes_version` trigger. `PartNote` is defined in `schemas.py` (used by `SyncPage` and `PushResult`), re-exported from `schemas_field.py` |
| `GET /sync/conflicts`, `POST /sync/conflicts/{id}/resolve` | 7.10, survey roles, `app/conflicts.py` (routes in `routers/sync.py`). A row is visible when its record is in the user's area (voter; new voter's part, else Village Panchayat; Kutumb's part) and, for a surveyor, only the rows of their own pushes; supervisor and above see every row in their area. `?status=` (default open), `?entity_id=`, newest first, cursor `[created_at, id]`. Resolve `{keep}`: `kept_server` writes nothing; `kept_client` puts that one field's phone value on the current record and saves it through `write_survey` / `write_new_voter_update` (checks, references, audit, new version); a record that would break a rule = 422 (keep the other field first); decided already = 409 `conflict_resolved` (row locked `FOR UPDATE`, so it is written once). Kutumb rows (never made) = 422 |
| `POST /sync/push` | `survey` (4.8), `family_new` and `family` (7.2), `visit` (7.3), `new_voter` and `new_voter_update` (7.5) (dispatch table `APPLY` in `sync_push.py`); per-item results, retry-safe; see `context/sync.md`. Survey writes go through `write_survey` in `routers/voters.py` (shared with PUT) |
| `POST /families` | Kutumb Connect (7.1), `SURVEY_ROLES`. Free-text `label` (trimmed, 1–200) in one **booth** (a ward or another area: 404). Phone-made id; a repeat returns the stored Kutumb (first name kept, 201). An id taken by a record the user cannot see: 409 `id_in_use` |
| `PATCH /families/{id}` | rename, `SURVEY_ROLES` |
| `GET /booths/{id}/families` | all roles; the booth's Kutumbs by `lower(label)`, id; cursor `[sort_name, id]`. Not a booth / outside area: 404 |
| `GET /voters/{id}/family` | all roles; `{"family": Family | null}` |
| `GET/POST /new-voters`, `PATCH /new-voters/{id}` | Eligible but Not Registered (7.5), `SURVEY_ROLES`, `routers/new_voters.py`. A record is seen through `coalesce(booth_id, ward_id)` (its part, else its Village Panchayat), so a booth-only surveyor cannot add or see a record without a part (404). `check_place`: part in that ward (422), Kutumb in that part (422). POST: repeat id stored once (first copy kept), id of an unseen record 409 `id_in_use`. PATCH: the whole record + `version` (starts at 1, `bump_version` trigger); stale 409 `version_conflict` with `current`. List: newest first, cursor `[created_at, id]`, filters `ward_id`, `form6_status`. Text fields trimmed, blank = null; `dob` not in the future; `family_id` needs `booth_id`. Model in `schemas.py` (pull and push use it) |
| `GET /terms/current`, `POST /terms/accept` | 7.9, `routers/misc.py`. Terms are global rows (`terms_versions`, newest version wins), loaded by us from the client's text; none yet = 404 `not_found` (also for accept). Reading is public; accepting (active user, also while the phone waits) must name the current version, else 409 `terms_changed`; it sets `users.terms_version` / `terms_accepted_at` (`GET /me` shows it). Tests use version 9001 and remove it |
| `GET /announcements`, `POST /announcements/{id}/read` | 7.9, ready users. Visible: not deleted, not expired, and audience null (everyone) or an area that contains the user's area or lies inside it (a ward's notice reaches its booths; an admin sees booth notices). Newest first, cursor `[created_at, id]`, `is_read` per user; read = one `announcement_reads` row (again is fine; not visible = 404). Admin create / delete is Step 9 |
| `POST /problem-reports` | 7.9, active users. Body trimmed (blank = 422); stores user, device, `app_version_code`, `phone_model`, status open. Admin list is Step 9 |
| `GET /birthdays` | 7.8, all roles, `routers/birthdays.py`. Date of birth from `voter_surveys.dob` (the roll has only the age). Range by day and month, `date_to` default `date_from`, at most 365 days later (422), may run over the year end; birthday order from `date_from` (cursor `[wrap, 'MM-DD', voter id]`); 29 Feb counts as 28 Feb in a year without it; `turns` = age on that birthday; `booth_id` filter (404 outside). Generic checks: `Endpoint.query` (required query parameters) and `item_id` (list items keyed by `voter_id`) were added for it |
| `POST /voters/{id}/slip-events` | Voter slip shared (7.7), all roles, voter in scope (404); `routers/slips.py`, also push `slip_event`. Stored once per phone-made id (`slip_events.client_mutation_id`); id of another voter's event 409 `id_in_use`; `created_at` = `least(at, now())`. 204, no body. `GET /voters/{id}/slip` (server-drawn, portal) is still a stub (12.2) |
| `GET /voters/{id}/history` | Information Updation (7.6), all roles, voter must be in scope (404). Logic in `app/history.py`: `audit_log` rows of `voter_surveys` / `family_members` / `voter_turnout` / `voters` with `entity_id` = the voter (kinds survey, family, voted, roll_edit), plus `visits` (no audit trigger; at = `visited_at`) and `slip_events` (action = channel). Newest first, cursor `[at, key]` (key `a`/`v`/`s` + row id, compared `COLLATE "C"`). `HIDDEN` drops bookkeeping columns; insert / delete list only fields with a value (not false / empty); `REFS` adds `old_label` / `new_label` for ids (castes, colour tags, Kutumbs, users, areas, ...). Roll imports skip the audit, so imported voters start with an empty history. Not yet: `new_voter_match` (Matching Engine). No index on `visits.voter_id` (one workspace's visits scanned; fine at this size, add one in a later migration if it grows) |
| `POST /voters/{id}/visits` | visits (7.3), `SURVEY_ROLES`, `routers/visits.py`. Stored under the phone-made id (`id` = `client_mutation_id`; `ON CONFLICT DO NOTHING`), so a repeat returns the stored visit (201); an id used by another voter's visit: 409 `id_in_use`. `booth_id`, `house_no` copied from the voter, `family_id` = their Kutumb now. `revisit_at` only with `revisit` (422). Never writes `voter_surveys.last_visit_*` (would raise the survey version) |
| `POST /turnout/marks`, `DELETE /turnout/marks/{voter_id}`, `GET /turnout/summary` | Polling day (8.1), `POLLING_ROLES` (surveyor 403), `routers/turnout.py`; push `voted` / `unvoted` and the pull's `turnout` phase use the same code. One `voter_turnout` row per voter (primary key): two phones = one mark, the first kept, the second request lists the voter in `already`. Body: `voter_ids` (any not in the area = 404 for the whole request; not on the current roll = 422) or `booth_id` + `serials` ("12, 15, 18-25", commas or spaces, at most 2,000; a ward or another area's booth = 404; serials of voters not `roll_status = 'active'` or missing go to `not_found_serials`). Retry key: each row stores `uuid5(request id, voter id)` in `client_mutation_id` (unique per workspace), so the same request again marks nothing (even after an undo) and lists those voters as `marked` again; no migration needed. `marked_at` = phone time, never later than now. Undo: `is_voted = false`, `cleared_by` / `cleared_at`, row kept (no DELETE grant); nothing to undo = 204. Summary: booths in the scope (`ward_id` / `booth_id` narrow it, 404 outside), totals = voters not removed and on the current roll; marks counted on their own from the marks to the voters (one join went to a voter x mark nested loop while the stats said "empty": 0.5 s; now 20 ms, 124 ms with all 31k marked). Real roll: one part of ~600 marked by serials in ~120 ms (an audit row per voter) |
| `GET/POST /users`, `GET/PATCH /users/{id}`, `POST /users/{id}/reset-password` | 9.1, admins, `routers/users.py`. Admin: users of own constituency (`local_body_id`), so no super admins; changes only supervisor / surveyor / booth agent (an admin target or giving the admin role: 403 `forbidden_role`). Super admin: all. Create: temporary password (12 chars, `security.temporary_password`) returned once, `must_change_password`; an admin's user goes in the admin's constituency (another: 404); a super admin's user needs `local_body_id` (a super admin must not have one: 422). PATCH changes only the fields sent; role to / from super admin 422 (new user instead); own role / switch-off / reset: 403 `own_account`. Switch-off ends sessions (`disabled`); reset ends sessions (`password_reset`), clears the lock, keeps the phone's approval. 409 `username_taken` / `mobile_taken` / `user_limit` come from the database (unique indexes, `users_limit` trigger: 200 **active** users, so switching one back on can hit it). List by `lower(full_name_en), id`, filters `role`, `is_active`, `q` (name, user ID, mobile) |
| `GET/PUT /users/{id}/assignments` | 9.2, admins, `routers/users.py`. PUT replaces the list (repeats stored once, at most 500, `assigned_by`). Only wards and booths of the **user's own** constituency (another area or unknown id: 404 for everyone, also a super admin; a constituency: 422). Admin / super admin targets: 422 (no assignments). No sync change needed: the pull's `area_ids` is always the full list, so the phone drops a removed area and re-downloads for a new one |
| `PUT /voters/{id}/family` | `SURVEY_ROLES`. `family_id` (moves the voter out of any other Kutumb) or `leave_family: true` alone; unknown fields (`make_head`) 422 (`extra="forbid"`). Kutumb outside the area 404; in another booth than the voter 422. A repeat writes nothing (no audit row, same `sync_xid`) |

Survey decisions (11 Nov): residence check (`has_new_address`, `new_address_mr/en`) and location are in the body, as the SRS says. `surveyed_at` = first save. Other `voter_surveys` columns (email, society, family, dead marks, karyakarta) are not in the body yet: not in the SRS survey, or later steps.

Client's final list (7.13, built 13 Nov after the app flow was approved): `is_important`, `position_id`, the `positions` list and `?important=` are out of the contract. A survey body (PUT or push `data`) that still has `is_important` or `position_id` is 422 ("update the app"; `REMOVED_SURVEY_FIELDS` in `schemas.py`, a `mode="before"` validator); other unknown keys are still ignored. The column `voter_surveys.is_important` stays, never read or written.

Survey, client changes (12 Nov, 5.14; 7.13): `is_influencer` + `influencer_type_id`, `in_self_help_group` + `self_help_group_name` (200), `ration_card` (`AAY` / `PHH` / `NPHH`). Each second field only with its yes (422, and a CHECK in the database). Influencer types are a list like castes (active entries of the workspace, else 422) and ride in the pull's `lists`. Adding a field to `SurveyFields` adds it to PUT, push, pull and the conflict diff by itself; the column must exist with the same name. Enum values go to SQL as `.value` (`_db_value`).

Errors: `ApiError(..., extra={...})` adds keys inside `error`; `ErrorBody.current` documents the 409 server copy.

Kutumb Connect (7.1, 13 Nov): a Kutumb is seen through its booth (`families.booth_id` → `geo_units.path` in scope), deleted ones never. `member_ids` = members in the user's scope, removed voters left out, roll order. Members live in `app.family_members` (see `database.md`), never in `voter_surveys`: membership must not raise the survey version. `write_new_family` / `write_voter_family` in `routers/families.py` are what push (7.2) will call. No head: `Family` has no `head_voter_id`. `GET /families` (walk list) is still a stub in `field.py`.

`q` rules: up to 5 words, every word must match `voters.search_text` (names mr/en, EPIC, house; lowercase `LIKE`, wildcards escaped). An ASCII number also matches `serial_no` exactly, and `mobile_1/2` when 4+ digits. Real roll (11 Nov): paging all 31,871 voters at 200/page, slowest page 61 ms; searches 10–32 ms.

**Contract stubs (4.10):** every other endpoint exists as a stub that checks login and role, then answers 501 `not_implemented` (`app/stubs.py`). Routers by plan step: `field.py` (7), `misc.py` (6.3, 7.9), `admin.py` (9), `rolls.py` (10), `reports.py` (11); conflicts in `sync.py` (7.10). Models: `schemas_field.py`, `schemas_admin.py`, `schemas_roll.py`. Every push type is built (8.1); a type the server does not know yet would be rejected `not_implemented` and not recorded, so a retry after the update applies it.

**Building a stub:** replace `not_built(...)` with the code; remove `responses=NOT_BUILT` / move the router out of the `planned` loop in `main.py` when all its routes are built; in `tests/endpoints.py` drop `stub` and add `target` / `lists` (and a `Kind` if new); write its own test file; export OpenAPI. `test_stub_flags_match_the_api` fails if the row and the route disagree.

## Tests

- `conftest.py` drops and rebuilds its test database each run and applies migrations via `scripts/migrate.py`. **Each runner its own database:** `TEST_RUNNER=claude pytest` uses `jansetu_test_claude` (Antigravity: `TEST_RUNNER=antigravity`). Two runs on one database wipe each other. Only `jansetu_test` / `jansetu_test_<name>` is accepted.
- Fixtures: `owner_conn` (BYPASSRLS, setup only), `app_conn` (RLS applies), `client`, `make_workspace(label, must_change=(), extra_users={})`, `set_device_status`.
- `make_workspace` gives: 1 local body, 1 ward, booths 1001/1002, users `boss` (super_admin), `admin1`, `sup1` (assigned the ward), `survey1` (assigned booth 1 only). All use password `PASSWORD` (`Test@pass123`).
- Helpers: `login(client, ws, username, device=phone())`, `bearer(tokens)`.
- `create_workspace(owner_conn, ...)` is the plain-function form of `make_workspace` (for module-scoped data).
- **Generic checks:** every route needs a row in `tests/endpoints.py` (`roles`, `level`, `target`, `lists`, `area_params`, `body`). `tests/test_endpoint_rules.py` then checks 401s, pending / blocked phone, password not changed, 403 for each unlisted role, success for each listed role, 404 for another workspace / another area, 422 / 404 for bad / unknown ids, list isolation, and that refused writes change nothing. A new kind of record (path id or list item) needs a `Kind` in `KINDS` (how to make one in "own", "other_area", "other_ws"; optional state read-back). The shared data is built once per run (`World`): workspace A (+ a second constituency = "other area"), workspace B.
- Pitfall: this FastAPI version does not flatten included routers into `app.routes`; list routes from `app.openapi()["paths"]`.
- Each endpoint's own test file covers its behaviour (409, paging, search, ...), not the generic rules.
- Test voters are inserted by the owner without `app.skip_audit`, so their history starts with a `roll_edit` entry.
- Times in tests: the database clock is UTC; a "past" phone time must be before today UTC (a later one becomes now).

## Pitfalls

- Never use a superuser or owner connection in the API.
- The `users_audit` trigger copies whole `users` rows (also `password_hash`) into `audit_log`, and every login writes one (failed count, last login). Anything that reads `audit_log` back (`GET /audit-log`, 9.5) must drop `password_hash`.
- Do not write `audit_log` or `sync_xid` by hand; triggers do it.
- After editing any route or schema: export OpenAPI and commit it; once `portal/` exists, run `npm run gen:api` there in the same commit (see `context/portal.md`). Add fields instead of changing existing ones.
