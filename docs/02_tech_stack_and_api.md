# JANSETU – Tech Stack and API Contract

Nov 11, 2026 · @Functionalloop

JANSETU runs as one FastAPI backend on PostgreSQL 16, used by a Kotlin Android app and a React web portal, all on one VPS (Bluehost since 13 Nov; the SRS says KVM 4).

## Tech stack

| Part | Choice | Why |
| --- | --- | --- |
| Database | PostgreSQL 16, schema `app` from `001_jansetu_schema.sql` | Already written and tested (48 checks). Row-level security keeps workspaces apart. |
| Backend API | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 Core with psycopg 3 | The schema is hand-written SQL, so a thin SQL layer fits better than a heavy ORM. FastAPI produces the OpenAPI file that the app and portal build from. |
| Migrations | Plain numbered SQL files (`001_`, `002_`…) run by a small script | Keeps triggers, RLS and functions exactly as written. |
| Login | Argon2 password hashes, short access token (JWT, 15 min) + refresh token stored in `auth_sessions` | No OTP. A blocked phone loses access at the next refresh. |
| Background jobs | One Python worker reading job rows from PostgreSQL (`FOR UPDATE SKIP LOCKED`) | Roll imports and exports run outside requests. No Redis or Celery to run. |
| Files | Server disk folder, tracked in the `files` table | Slips, exports, APK builds. No outside storage. |
| Android app | Kotlin, Jetpack Compose, MVVM, Hilt, Retrofit + OkHttp, Room + SQLCipher with FTS, WorkManager, Android Keystore; min SDK 26 (Android 8.0) | Offline-first with an encrypted local copy; fast English and Marathi search. |
| Web portal | React + TypeScript + Vite (static build), TanStack Query, client types generated from the OpenAPI file | A static build needs no Node process on the server. Built by me since 14 Nov (plan, Step 15). |
| Server | Ubuntu LTS, Docker Compose: Caddy (HTTPS), API, worker, PostgreSQL | One command to deploy. Caddy renews the HTTPS certificate by itself. |
| Backups | Nightly `pg_dump`, kept 14 days, copied off the main disk | Matches the SRS. |

The APK is served by Caddy from the server and the app checks `app_releases` for updates. Nothing here needs an outside account except the domain.

## How the parts fit

```
Android app (Room+SQLCipher) ──HTTPS /api/v1──┐
Web portal (static React)    ──HTTPS /api/v1──┤
                                              ▼
VPS (Docker Compose)
  Caddy ── HTTPS, serves portal files + APK, proxies /api → API
  API (FastAPI) ── PostgreSQL 16 (schema app, RLS)
  Worker (Python) ── job rows in PostgreSQL (imports, exports)
  Nightly pg_dump → backup folder (14 days)
```

Neither the app nor the portal talks to PostgreSQL directly; every read and write goes through the API.

What happens on every API request:

1. The client sends `Authorization: Bearer <access token>` to `https://<domain>/api/v1/...`.
2. The API checks the token and reads the workspace, user, role and device from it.
3. It opens one database transaction and calls `app.set_context(tenant, user, device)`.
4. Row-level security then limits every query to that workspace. The API adds the role and assigned-area checks.
5. Triggers write `audit_log` and stamp `sync_xid` on changed rows.
6. The transaction commits and the API returns JSON.

Long jobs (roll import, list export) only create a job row and return a job id. The worker does the work and the client polls the job.

## Offline sync (Android)

The phone reads and writes its own encrypted database first; the server is only touched during sync.

1. **First download:** after login and phone approval, the app calls `GET /sync/pull` with no watermark. The server sends the user's assigned area in pages (voters, families, surveys, lists) and a watermark `W`.
2. **Daily use:** search, surveys, visits and voted marks are saved locally. Each change is also added to an outbox with a client-made UUID.
3. **Push:** WorkManager sends the outbox in batches to `POST /sync/push` when online. The UUID makes a retry safe: the server records it in `sync_mutations` and never applies it twice.
4. **Conflicts:** surveys and new voters carry a `version`. If the server's version is newer, the change is saved in `sync_conflicts` and reported back; nothing is lost.
5. **Pull:** the app calls `GET /sync/pull?since=W`. The server returns rows with `sync_xid >= W` plus a new `W` from `app.sync_watermark()`.
6. **Scope change or blocked phone:** the pull response tells the app to drop areas it no longer has, or to wipe everything.

The web portal does not sync. It calls the REST endpoints live.

## Build workflow

The API contract comes first, so the app and the portal can be built at the same time.

1. **Database (you):** load the schema locally, import the client's voter data.
2. **API skeleton (you):** FastAPI project, login, `set_context` per request, and empty endpoints that return the right shapes. Share `/api/v1/openapi.json`.
3. **Portal (me, since 14 Nov; plan Step 15):** generates typed client code from the OpenAPI file and builds pages against the local API, each step's pages after that step is merged.
4. **API features (you):** fill endpoints in this order: login and devices, sync, voters and surveys, polling day, admin, roll import, reports.
5. **Android app (you):** local database and search first, then login, sync, survey, polling day, admin screens.
6. **Server:** when the VPS is ready, `docker compose up` and point both clients at the domain.

**Rule for changes:** any endpoint change goes into the OpenAPI file first, and the portal's generated types are updated in the same commit. Breaking changes need a new field or endpoint, not a silent change.

## API rules

All endpoints sit under `/api/v1` and speak JSON. This list is the first draft of the contract; exact request and response fields will live in the OpenAPI file.

- **Auth:** every endpoint except login, refresh, terms and app version needs `Authorization: Bearer <access token>`.
- **Roles:** the "Who" column is the lowest role allowed. Order: surveyor / booth agent < supervisor < admin < super admin. Everyone is also limited to their assigned area.
- **IDs:** UUIDs. The app creates the UUID for anything it makes offline.
- **Lists:** `?limit=50&cursor=...`; the response has `items` and `next_cursor`.
- **Edits with versions:** send the `version` you last saw; a stale one returns `409` with the server copy.
- **Errors:** `{ "error": { "code": "...", "message": "..." } }` with status 400, 401, 403, 404, 409 or 422.
- **Dates:** ISO 8601 in UTC; the clients show Indian time.

## Endpoints: login, phone and sync

| Method and path | What it does | Who |
| --- | --- | --- |
| `POST /auth/login` | Workspace code, user ID, password and phone details. Returns tokens, or "change password" / "phone waiting for approval" / "blocked". | Public |
| `POST /auth/refresh` | New access token from a refresh token. | Public |
| `POST /auth/logout` | Ends the session. | All |
| `POST /auth/change-password` | First-login and normal password change. | All |
| `GET /me` | User, role, assigned areas, workspace name and settings, labels. | All |
| `GET /devices/me` | This phone's status: pending, approved, blocked or wiped. | All |
| `GET /app/version` | Latest and minimum app version and the APK link. | Public |
| `GET /terms/current` | Current terms of use text. | Public |
| `POST /terms/accept` | Records that the user accepted the terms. | All |
| `GET /sync/pull` | Changes since `since=W` for the user's area, in pages, with the new watermark. No `since` = first download. | All (app) |
| `POST /sync/push` | Batch of offline changes: surveys, visits, voted marks, new voters, families made and family changes, part notes, slip events. Returns accepted / conflict per item. | All (app) |
| `GET /sync/conflicts` | Open conflicts for review. | Supervisor |
| `POST /sync/conflicts/{id}/resolve` | Keep the phone's copy or the server's copy. | Supervisor |
| `GET /announcements` | Announcements for this user. | All |
| `POST /announcements/{id}/read` | Marks one as read. | All |
| `POST /problem-reports` | "Report a problem" from the Help screen. | All |
| `GET /health` | Server check for monitoring. | Public |

## Endpoints: voters, field work and polling day

The Android app does most of this from its local copy and sends changes through `/sync/push`. These live endpoints are mainly for the web portal, and for the app's admin screens when online.

| Method and path | What it does | Who |
| --- | --- | --- |
| `GET /geo/tree` | Constituency → ward → booth → section tree for the user's area. | All |
| `GET /voters` | Search and filter: `q`, ward, booth, age, gender, colour tag, survey status, caste, profession, has mobile, influencer, influencer type, voted. | All |
| `GET /voters/{id}` | Roll details plus survey. | All |
| `PUT /voters/{id}/survey` | Save survey: mobiles, caste, profession, colour tag, residence check, date of birth, notes, custom fields, influencer + type (the client's 11 entries; no important voter, 7.13), self help group + name, ration card, location. Needs `version`. | Surveyor |
| `GET /voters/{id}/family` | The voter's Kutumb and its members. | All |
| `PUT /voters/{id}/family` | Put the voter in a Kutumb of their booth (moving them out of any other), or take them out. No head (12 Nov). | Surveyor |
| `GET /voters/{id}/history` | Every change: surveys, notes, visits, roll edits, voted marks. | All |
| `POST /voters/{id}/visits` | Record a visit: met, not home, revisit, shifted, with location. | Surveyor |
| `GET /voters/{id}/slip` | Voter slip as an image or PDF. | All |
| `POST /voters/{id}/slip-events` | Logs that a slip was shared or printed. | All |
| `GET /families` | Walk list: houses in a booth with visit status. | All |
| `POST /families` | Make a family by hand in a booth, with a free-text name (client, 12 Nov). | Surveyor |
| `PATCH /families/{id}` | Rename a family. | Surveyor |
| `GET /booths/{id}/families` | The families made in a booth. | All |
| `GET /booths/{id}/note`, `PUT /booths/{id}/note` | The part's one shared note (client, 12 Nov). Needs `version`. | All / Surveyor |
| `GET /new-voters` | Voters added by hand, with Form 6 status. | Surveyor |
| `POST /new-voters` | Add a person not on the roll. | Surveyor |
| `PATCH /new-voters/{id}` | Edit or update the Form 6 status. Needs `version`. | Surveyor |
| `GET /birthdays` | Birthdays for a date or range. | All |
| `GET /saved-filters`, `POST /saved-filters`, `DELETE /saved-filters/{id}` | The user's saved search filters. | All |
| `GET /turnout/summary` | Voted counts and percentage by booth. | Booth agent |
| `POST /turnout/marks` | Mark one or many voters as voted (by voter ID or by booth + serial numbers). | Booth agent |
| `DELETE /turnout/marks/{voter_id}` | Undo a wrong mark. | Booth agent |
| `GET /data-quality/summary` | Counts: no mobile, no date of birth, duplicates, repeated, shifted, doubtful dead marks. | Supervisor |
| `GET /data-quality/duplicates` | Possible duplicate and repeated pairs. | Supervisor |
| `POST /data-quality/duplicates/{id}/resolve` | Same person or different people. | Supervisor |

## Endpoints: roll, reports and admin

The web portal uses most of these; the app's admin screens use the same ones.

| Method and path | What it does | Who |
| --- | --- | --- |
| `POST /rolls/imports` | Upload a new roll file (Excel, CSV or scanned PDF). Starts a job. | Super admin |
| `GET /rolls/imports`, `GET /rolls/imports/{id}` | Import list and one import's progress and counts. | Admin |
| `GET /rolls/imports/{id}/rows` | Rows by match status: matched, uncertain, possible duplicate, absent, new. | Admin |
| `POST /rolls/imports/{id}/rows/{row_id}/resolve` | Accept or reject one uncertain match. | Super admin |
| `POST /rolls/imports/{id}/apply` | Apply the reviewed roll. | Super admin |
| `POST /rolls/imports/{id}/discard` | Throw the import away. | Super admin |
| `POST /voters` | Add one voter to the roll by hand, with reason and reference. | Super admin |
| `PATCH /voters/{id}/roll` | Correct one roll record, with reason and reference. | Super admin |
| `POST /voters/{id}/remove`, `POST /voters/{id}/restore` | Hide or bring back one voter, with reason. | Super admin |
| `GET /voters/{id}/roll-edits` | Roll corrections made to this voter. | Admin |
| `POST /mobile-imports`, `GET /mobile-imports/{id}` | Upload a mobile number sheet and review its matches. | Admin |
| `GET /reports/survey-progress` | Surveyed vs total by ward and booth. | Supervisor |
| `GET /reports/colour-tags` | Counts by colour tag. | Supervisor |
| `GET /reports/demographics` | Age and gender charts. | Supervisor |
| `GET /reports/turnout` | Polling-day turnout by booth and hour. | Supervisor |
| `GET /reports/worker-activity` | Visits, surveys and mobiles collected per worker and day. | Admin |
| `GET /worker-locations` | Places where surveys and visits were saved. | Admin |
| `POST /exports` | Start a PDF or Excel list export with filters and columns. | Supervisor |
| `GET /exports/{id}`, `GET /exports/{id}/download` | Export status and the finished file. | Supervisor |
| `GET /constituencies`, `POST /constituencies`, `PATCH /constituencies/{id}` | Constituencies in the workspace (limit 5). | Super admin |
| `GET /users`, `POST /users` | List users; create a user with a temporary password (limit 200). | Admin |
| `GET /users/{id}`, `PATCH /users/{id}` | View, edit, disable or enable a user. | Admin |
| `POST /users/{id}/reset-password` | New temporary password. | Admin |
| `GET /users/{id}/assignments`, `PUT /users/{id}/assignments` | Wards and booths the user can see. | Admin |
| `GET /devices` | Phones and their status. | Admin |
| `POST /devices/{id}/approve`, `POST /devices/{id}/block` | Approve a new phone, or block and wipe a lost one. | Admin |
| `GET /settings/election`, `PUT /settings/election` | Election, candidate, symbol, polling date and time, slip text and feature switches. | Admin |
| `GET /masters/{list}`, `POST /masters/{list}`, `PATCH /masters/{list}/{id}` | Lists and labels: `castes`, `professions`, `influencer-types` (added 14 Nov, 9.4), `color-tags`, `custom-fields`, `message-templates`. | Admin |
| `POST /files` | Upload candidate photo, symbol or slip header. | Admin |
| `POST /announcements`, `DELETE /announcements/{id}` | Send or remove an announcement. | Admin |
| `GET /problem-reports` | Problems reported by users. | Admin |
| `GET /audit-log` | Who changed what and when. | Admin |

That is about 90 endpoints. For the 25 Nov demo only these are needed: login and phone endpoints, `/me`, `/sync/pull`, `/sync/push`, `/geo/tree`, `/voters`, `/voters/{id}` and `/voters/{id}/survey`.
