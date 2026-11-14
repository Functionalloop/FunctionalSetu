# Portal

The web portal for super admin, admin and supervisor. **I build it** (14 Nov: the teammate gave up and left nothing: no code, no designs). Plan: `docs/plan.md`, Step 15 (15.1–15.14), branch `step15-portal`. Pages are laid out from the approved app flow (`docs/app_flow_v2.pdf`), with the same screen names and fields; there are no separate portal designs.

## Current state (14 Nov)

- Not started: no `portal/` folder yet (15.1, 17 Nov). Step 9 comes first.
- Scope (decided 14 Nov): everything the app's admin screens have. Public website pages are **dropped**; the domain root opens the portal login. The client is to be told in writing (the SRS names them).
- Not in the demo. The portal reaches the server only after the demo (15.8, 26 Nov); before that it runs on the laptop.

## Stack

React + TypeScript + Vite (static build), TanStack Query, React Router, `openapi-typescript` + `openapi-fetch`. Versions fixed by `package-lock.json` (`npm ci`). Node on the laptop only, never on the server.

## Safety rules (full text: plan, Step 15)

1. Portal tasks change only `portal/` (plus `deploy/Caddyfile`, `deploy/docker-compose.yml`, `scripts/publish_portal.sh` in 15.7). Never `backend/`, `db/`, `android/`; a missing API piece is its own backend commit, additions only.
2. `portal/src/api/schema.d.ts` is generated from `docs/openapi.json` and committed; `npm run check` fails if it is stale or a page uses a field that is gone.
3. The API is the only door. No database access, no server process. The API checks role and area; the portal only hides menu items.
4. Fake data only in tests and mocks. Nothing in `localStorage`, IndexedDB or a service worker; access token in memory, refresh token in `sessionStorage`.
5. No outside scripts, fonts, analytics or map tiles. Worker locations = a list with a maps link.
6. Same address as the API: Vite passes `/api` to `localhost:8000` (no CORS change); Caddy matches `/api/*` and `/download/*` first, the portal is the last fallback.
7. Server change after the demo, tried on the laptop stack first, backup just before; only `caddy` is recreated.
8. Builds in `deploy/portal/releases/<time>/`, `current` points at one; going back = point at the one before. `index.html` never cached.
9. Versioned records send `version`; a 409 shows the server copy and asks. No `/sync/*`. Surveys are read on the portal, edited on the phone.
10. Branch from `main` for each part (A, B, C), merge after the full check; the check adds `npm run check`.

## Commands

Filled in by 15.1. Planned:

```
cd portal
npm ci
npm run gen:api      # after any API change; commit with docs/openapi.json
npm run dev          # http://localhost:5173, /api -> localhost:8000
npm run check        # types, lint, tests, build, types current, no outside address
```

## Pages by task

| Task | Pages | API (step) |
|---|---|---|
| 15.2 | Login (no phone), Set password, shell, menu by role, area picker | auth, `/me`, `/geo/tree` |
| 15.3 | Voters list and filters, profile (Details, Survey, Kutumb Connect, Information Updation), Kutumbs of a part, Eligible but Not Registered, part note | built (4, 7) |
| 15.4 | Users, assignments, phones | 9.1, 9.2, `/devices` |
| 15.5 | Constituencies, Election & candidate, Lists & labels | 9.3, 9.4 |
| 15.6 | Announcements, problem reports, activity log, worker activity, worker locations, turnout by part | 9.5, 8.1 |
| 15.7 / 15.8 | Caddy serves the build (laptop / server) | – |
| 15.9 | Matching Engine: upload, rows, resolve, apply, discard | 10.2, 10.3 |
| 15.10 | Corrections, data quality, repeated voters, mobile number sheets | 10.4, 10.5 |
| 15.11 | Reports, charts, exports | 11.1, 11.2 |
| 15.12 | Voter slip, PDF upload, box image | 12.2, 13.7 |
| 15.13 | Step 14 pages (only what the client approved) | 14.x |
| 15.14 | Final build, browsers, handover | – |

## Contract notes

- `docs/openapi.json` is the contract (exported by `scripts/export_openapi.py`, checked by `tests/test_openapi.py`). Operation ids are the Python function names and stable. Every endpoint exists; unbuilt ones answer `501 not_implemented` with their final shapes.
- Errors: `{"error": {"code", "message", "details"?, "current"?}}`; code table in the OpenAPI description. 409 `version_conflict` carries `error.current`.
- Lists: `?limit=&cursor=` → `{items, next_cursor}`. Dates UTC; show Indian time.
- Login: super admin, admin and supervisor leave `device` out. A surveyor or booth agent is told to use the app.
- Do not offer inactive colour tags (the white tag is off).
- Kutumb view = `GET /booths/{id}/families` (`GET /families` is the walk list). No head.
- Roll writes are super admin only; an admin reads imports and roll edits, so hide the buttons.
- Roll import (10.2): POST answers 202 at once; poll `GET /rolls/imports/{id}` until `status` leaves `uploaded` / `parsing` (`review` or `failed`; `error` holds a plain message for the user). One open import per constituency: 409 `import_in_progress`. `counts` keys: matched, uncertain, possible_duplicate, absent_from_current_roll, new, unreadable, rows, to_review, reviewed. Rows with `match_status` null are unreadable (`match_notes` "unreadable: <reason>").
- Review and apply (10.3): resolve returns the changed row; after any resolve, reload the counts and the absent rows (they follow the matches). An unreadable row is cleared with reject (= skip). "Pick a voter" sends `accept: true` + `voter_id`. Apply is disabled while `counts.to_review` > 0 (409 `review_not_finished`); it takes a few seconds on a full roll, so show a spinner. Apply's 409 `epic_in_use` / `serial_in_use` list `error.row_nos` to show the user. After apply, `counts` has the `applied` keys (updated, unchanged, added, marked_absent, deleted_in_roll, skipped).
- Corrections (10.4): removed voters are found with `GET /voters?removed=true` (admins); `GET /voters/{id}` is 404 for them, so take the row from that list (remove / restore return the voter with `deleted_at`). PATCH sends only the changed fields in `fields`; field errors come at `details[].loc` = `["body", "fields", "<key>"]`. 409 `epic_in_use` / `serial_in_use` carry `error.voter_id` (the other voter). A super admin gets the buttons; an admin reads the roll edits only.
- Data quality (10.5): summary counts link to `GET /data-quality/duplicates` (`?source=roll_flag` = Repeated in the roll). "Same person" for everyone who sees the pair; the "hide this one" choice (`keep_voter_id`) only for a super admin (others 403). Mobile sheets: upload answers 202, poll `GET /mobile-imports/{id}` until `done` / `failed` (`error` is a plain message); `GET /mobile-imports` lists them. Rows to review carry `candidate_voter_ids` (fetch each with `GET /voters/{id}`); resolve returns the whole sheet again. Switched off in settings: 403 `feature_off`.
- Reports (11.1): `by_area` is each ward followed by its booths; nest booths by `parent_id` (added 11.1; null on wards). A ward not in the user's area is not listed, only its booths. Report totals equal `GET /voters` with the same filter (removed voters left out, absent ones counted), so a number can link to the list; turnout counts only voters on the current roll (= `GET /turnout/summary`). Colour tags: only counts above zero, `color_tag_id` null = no tag; take labels and colours from `/masters/color-tags`. Age bands are fixed (`18-25` … `76+`), plus `unknown` last only when some voter has no age. `by_hour` = Indian hours from the first mark to the last, gaps filled with 0.
- Show the `ward` level as "Village Panchayat"; no spelling fixes page, no bulk message.
- `/masters/{list}` is served as one route per list (`/masters/castes`, `/masters/color-tags`, `/masters/custom-fields/{field_key}`, ...).

## Pitfalls

- Any API change: export OpenAPI and run `npm run gen:api` in the same commit. Add fields, never break.
- CORS: not needed (same address). `CORS_ORIGINS` stays as it is until 12.7.
