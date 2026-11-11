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
- Rank: super_admin 4 > admin 3 > supervisor 2 > surveyor = booth_agent 1. Equal rank is **not** interchangeable: survey work refuses booth agents, polling day refuses surveyors. Step 4.1 adds an explicit role-list check (`require_roles`) and `app/scope.py` (area scope).
- `last_seen_at` on the session is written at most once a minute.

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

Everything else in `docs/02_tech_stack_and_api.md` is not built; step 4 starts it (see `docs/plan.md`).

## Tests

- `conftest.py` drops and rebuilds `jansetu_test` each run, applies migrations via `scripts/migrate.py`. The name is hard-guarded: anything but `jansetu_test` aborts.
- Fixtures: `owner_conn` (BYPASSRLS, setup only), `app_conn` (RLS applies), `client`, `make_workspace(label, must_change=(), extra_users={})`, `set_device_status`.
- `make_workspace` gives: 1 local body, 1 ward, booths 1001/1002, users `boss` (super_admin), `admin1`, `sup1` (assigned the ward), `survey1` (assigned booth 1 only). All use password `PASSWORD` (`Test@pass123`).
- Helpers: `login(client, ws, username, device=phone())`, `bearer(tokens)`.
- Every endpoint needs four tests: works, lower role 403, other workspace 404, other area 404.

## Pitfalls

- Never use a superuser or owner connection in the API.
- Do not write `audit_log` or `sync_xid` by hand; triggers do it.
- After editing any route or schema: export OpenAPI, commit it, tell the teammate the same day. Add fields instead of changing existing ones.
