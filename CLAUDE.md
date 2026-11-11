# JANSETU – project guide for Claude Code

JANSETU is a voter data management platform: an offline-first Android app for field workers, a web admin portal, and one backend + PostgreSQL database on a single Hostinger KVM 4 server.

- **Client:** Naik Management Solutions Pvt Ltd, Sawantwadi
- **Developer:** Shree Samarth Krupa (me). I build the backend, database, server and Android app. My teammate builds only the web portal (`portal/`).
- **Deadlines:** demo 25 Nov 2026 · working build 30 Nov · final delivery 15 Dec 2026

## Source of truth (read before big changes)

| File | What it is |
|---|---|
| `docs/01_srs.md` | Approved scope. Anything not in it is a change request. Do not add features beyond it. |
| `docs/02_tech_stack_and_api.md` | Stack, sync design, API rules, the full endpoint list. |
| `db/migrations/001_jansetu_schema.sql` | The database schema (PostgreSQL 16, schema `app`). Tested; treat as the data model. |
| `docs/wireframes.pdf`, `docs/screen_flow.pdf` | 43 Android screens and how they connect. |

If code and these docs disagree, ask me; do not quietly change the contract.

## Hard rules

1. **Voter data is private.** Never open, print, copy or commit real voter files (`voters.csv`, the old app DB, any `activation.csv` or credentials file). They live outside this repo in `../jansetu-private/`. For tests and demos use `db/seed/sample_voters.csv` (fake data you generate). Import scripts are written here and run by me on the real data.
2. **No outside paid services.** No OTP or SMS gateway, no WhatsApp API, no Firebase, no cloud storage, no Redis or Celery. Calls, WhatsApp and SMS use the phone's own apps (Android intents).
3. **No Play Store.** The APK is downloaded from our server; the app checks `GET /api/v1/app/version`.
4. **Android 8.0 minimum** (minSdk 26).
5. **Everything runs on one KVM 4** (4 vCPU, 16 GB RAM, 200 GB NVMe) with Docker Compose.
6. **Never commit secrets.** `.env` is git-ignored; keep `.env.example` up to date.

## Stack

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 **Core** (no ORM models) + psycopg 3. Argon2 password hashes. JWT access token (15 min) + refresh token stored in `app.auth_sessions`.
- **Worker:** one Python process taking job rows from PostgreSQL with `FOR UPDATE SKIP LOCKED` (roll imports, exports).
- **Database:** PostgreSQL 16. Migrations are plain numbered SQL files in `db/migrations/`, applied in order by `scripts/migrate.py`, which records them in a table.
- **Android:** Kotlin, Jetpack Compose, MVVM, Hilt, Retrofit + OkHttp, Room + SQLCipher (FTS for search), WorkManager for sync, Android Keystore for the DB key.
- **Portal (teammate):** React + TypeScript + Vite static build, TanStack Query, API types generated from `openapi.json`.
- **Server:** Ubuntu LTS, Docker Compose: `caddy` (HTTPS, portal files, APK), `api`, `worker`, `db`. Nightly `pg_dump`, kept 14 days.

## How the database must be used

- Every request runs in **one transaction** that first calls `SELECT app.set_context(:tenant, :user, :device)`. Row-level security (FORCE RLS) then limits all queries to that workspace. Never bypass it with a superuser connection in the API; the API connects as the non-owner app role.
- The API also checks **role** (super_admin > admin > supervisor > surveyor / booth_agent) and **assigned wards/booths**.
- Triggers write `audit_log` and stamp `sync_xid`. Do not write these by hand.
- `voter_surveys` and `new_voters` carry `version`. An update with a stale version returns **409** with the server copy.
- Official roll data and campaign data stay separate; a new roll never deletes survey work. Removing a voter only hides it.
- Limits: 200 users and 5 constituencies per workspace.

## Sync (Android)

- Pull: `GET /api/v1/sync/pull?since=W` returns rows with `sync_xid >= W` and a new watermark from `app.sync_watermark()`. No `since` = first download, paged.
- Push: `POST /api/v1/sync/push` with a batch of outbox items, each with a client-made UUID. The server records it in `sync_mutations` so retries never apply twice; version clashes go to `sync_conflicts` and are reported back per item.
- The pull response can tell the phone to drop areas or wipe everything (blocked device).

## API conventions

- Base path `/api/v1`, JSON, `Authorization: Bearer <token>`.
- IDs are UUIDs (the app creates them offline).
- Lists: `?limit=50&cursor=...` → `{ "items": [...], "next_cursor": ... }`.
- Errors: `{ "error": { "code": "...", "message": "..." } }` with 400/401/403/404/409/422.
- Dates ISO 8601 UTC; clients display Indian time.
- Any endpoint change goes into the OpenAPI schema first and I tell my teammate the same day. No silent breaking changes; add a field or endpoint instead.

## Repo layout

```
CLAUDE.md
docs/                 SRS, API contract, wireframes, screen flow
db/migrations/        001_jansetu_schema.sql, 002_..., ...
db/seed/              fake sample data only
backend/              FastAPI app (app/, tests/), pyproject.toml
worker/               (or backend/app/worker.py) background jobs
scripts/              migrate.py, import_legacy.py, backup.sh
android/              Android Studio project
portal/               teammate's web portal
deploy/               docker-compose.yml, Caddyfile, .env.example
```

## Build order

1. Local PostgreSQL (Docker) + `migrate.py` + fake seed data.
2. `scripts/import_legacy.py`: maps the old VoterappDB tables (schema in `docs/legacy/VoterappDB_schema.sql`, master lists in `docs/legacy/*.csv`) into the new schema. I run it on the real data myself.
3. FastAPI skeleton: config, DB session with `set_context`, auth (login, refresh, change password, device approval), `/me`, error format, `/health`. Publish `openapi.json`.
4. Demo endpoints (needed by 25 Nov): auth + device, `/me`, `/sync/pull`, `/sync/push`, `/geo/tree`, `/voters`, `/voters/{id}`, `/voters/{id}/survey`.
5. Android: Room + SQLCipher + FTS search first, then login, sync, voter profile, survey.
6. Remaining endpoints in this order: polling day, admin, roll import, reports, exports.
7. Docker Compose + Caddy on the KVM 4, backups, restore test.

## Working style

- Small, reviewable steps. Run the tests after each change (`pytest` in `backend/`).
- Every endpoint gets a test, including a test that a user cannot see another workspace's or another area's data.
- Keep explanations short and plain; I am the only backend developer.
