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
| `app/routers/` | `auth.py`, `me.py`, `devices.py`, `health.py` |

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

## Area scope (`app/scope.py`)

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
| `GET /geo/tree` | all roles; `{"roots": [GeoNode]}` nested by `children`. Roots = the scope's top areas (super admin: every constituency; supervisor: the assigned ward, no parent above it). Inactive areas and their subtree are left out. Not paged (real roll: ~300 areas) |

| `GET /voters` | all roles, area scope. Filters `q`, `ward_id`, `booth_id` (404 outside scope), `age_min/max`, `gender`, `color_tag_id`, `survey_status`, `caste_id`, `profession_id`, `has_mobile`. Roll order (part, booth, serial, id), keyset cursor (opaque base64), `limit` 1–200. Removed voters (`deleted_at`) never listed. "voted" filter comes with step 8 |

| `GET /voters/{voter_id}` | all roles, area scope (404 outside, removed or other workspace). Roll fields + `survey` (null until first save) |
| `PUT /voters/{voter_id}/survey` | `SURVEY_ROLES` (booth agent 403). PUT replaces every editable field (left out = cleared), except `location`: left out = previous kept, given = `location_captured_at` now. `version` 0 = first save (INSERT … ON CONFLICT DO NOTHING); else `UPDATE … WHERE version = :v` (trigger bumps it). Zero rows → 409 `version_conflict` with `error.current` = server copy (null if none). Caste / profession / colour tag must be active entries of the workspace, else 422 |

Survey decisions (11 Nov): residence check (`has_new_address`, `new_address_mr/en`) and location are in the body, as the SRS says. `surveyed_at` = first save. Other `voter_surveys` columns (email, society, family, dead marks, karyakarta, important/influencer) are not in the body yet: not in the SRS survey, or later steps.

Errors: `ApiError(..., extra={...})` adds keys inside `error`; `ErrorBody.current` documents the 409 server copy.

`q` rules: up to 5 words, every word must match `voters.search_text` (names mr/en, EPIC, house; lowercase `LIKE`, wildcards escaped). An ASCII number also matches `serial_no` exactly, and `mobile_1/2` when 4+ digits. Real roll (11 Nov): paging all 31,871 voters at 200/page, slowest page 61 ms; searches 10–32 ms.

Everything else in `docs/02_tech_stack_and_api.md` is not built; step 4 starts it (see `docs/plan.md`).

## Tests

- `conftest.py` drops and rebuilds `jansetu_test` each run, applies migrations via `scripts/migrate.py`. The name is hard-guarded: anything but `jansetu_test` aborts.
- Fixtures: `owner_conn` (BYPASSRLS, setup only), `app_conn` (RLS applies), `client`, `make_workspace(label, must_change=(), extra_users={})`, `set_device_status`.
- `make_workspace` gives: 1 local body, 1 ward, booths 1001/1002, users `boss` (super_admin), `admin1`, `sup1` (assigned the ward), `survey1` (assigned booth 1 only). All use password `PASSWORD` (`Test@pass123`).
- Helpers: `login(client, ws, username, device=phone())`, `bearer(tokens)`.
- `create_workspace(owner_conn, ...)` is the plain-function form of `make_workspace` (for module-scoped data).
- **Generic checks:** every route needs a row in `tests/endpoints.py` (`roles`, `level`, `target`, `lists`, `area_params`, `body`). `tests/test_endpoint_rules.py` then checks 401s, pending / blocked phone, password not changed, 403 for each unlisted role, success for each listed role, 404 for another workspace / another area, 422 / 404 for bad / unknown ids, list isolation, and that refused writes change nothing. A new kind of record (path id or list item) needs a `Kind` in `KINDS` (how to make one in "own", "other_area", "other_ws"; optional state read-back). The shared data is built once per run (`World`): workspace A (+ a second constituency = "other area"), workspace B.
- Pitfall: this FastAPI version does not flatten included routers into `app.routes`; list routes from `app.openapi()["paths"]`.
- Each endpoint's own test file covers its behaviour (409, paging, search, ...), not the generic rules.

## Pitfalls

- Never use a superuser or owner connection in the API.
- Do not write `audit_log` or `sync_xid` by hand; triggers do it.
- After editing any route or schema: export OpenAPI, commit it, tell the teammate the same day. Add fields instead of changing existing ones.
