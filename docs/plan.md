# JANSETU – plan to final delivery

Written 11 Nov 2026; changed 12 Nov for the client's changes (see "Client changes of 12 Nov"). Scope is `docs/01_srs.md` plus those changes; anything else is a change request.

| Date | Milestone | What must work |
|---|---|---|
| Wed 25 Nov | Demo | Login + phone approval, sync pull/push, area tree, voter list/search/profile, survey save, all offline on a real phone, server deployed |
| Mon 30 Nov | Working APK | All 42 screens (the client removed Spelling fixes on 12 Nov) |
| Tue 15 Dec | Final delivery | Fixes from client testing, scanned roll PDF import (English), live server, backups, restore test, load test, training, handover notes |

## How to use this file

- One checkbox = one Claude Code session = one commit on the step's branch. Tick it once it is committed (`python scripts/tasks.py done <id>`).
- Each session reads CLAUDE.md, `context/README.md` and the one `context/` file for its section, and updates that file in the same commit.
- Every endpoint gets four tests: it works, a lower role gets 403, another workspace gets 404, another area gets 404. The last three (and 401, pending / blocked phone, bad id) come from one row in `backend/tests/endpoints.py`; the endpoint's own test file covers what it does.
- After every API subtask: run `scripts/export_openapi.py`, commit `docs/openapi.json`, tell the teammate the same day. The portal needs nothing else from me.
- Paths: `app/` = `backend/app/`, `tests/` = `backend/tests/`, `A/` = `android/app/src/main/java/com/jansetu/app/`.
- Android tests: `androidTest` for the database, unit tests with a fake server for sync and view models, and a short manual check on a real phone for each screen.

## Step 4 – Demo API · 12–17 Nov · branch `step4-demo-api`

Goal: everything the phone needs from the server for the demo.

- [x] **4.0 Merge step 3 into `main`**, start the branch. Create `context/README.md`, `context/database.md` and `context/backend.md` from what steps 1–3 built (see CLAUDE.md, "Context files"). Test: 40 tests pass on `main`. (12 Nov)
- [x] **4.1 Area scope helper.** Super admin: whole workspace; admin: own constituency; others: assigned wards and booths. Also a role-list check (`require_roles`), because surveyor and booth agent are not interchangeable: survey work refuses booth agents, polling day refuses surveyors. Files: `app/scope.py`, `app/deps.py`, `tests/test_scope.py`. Test: a surveyor's scope holds only booth 1; `require_roles` lets a booth agent through only where listed. (12 Nov)
- [x] **4.2 `GET /geo/tree`.** Files: `app/routers/geo.py`, `app/schemas.py`, `tests/test_geo.py`. Test: supervisor sees only the assigned ward and its booths. (12 Nov)
- [x] **4.3 `GET /voters`** with `q` (name, EPIC, house; a number also matches serial and mobile), ward, booth, age, gender, colour tag, survey status, cursor paging. Files: `app/routers/voters.py`, `tests/test_voters_list.py`. Test: paging returns every voter once; a voter in booth 2 is not listed for a booth 1 surveyor. (13 Nov)
- [x] **4.11 Generic endpoint checks.** One table of endpoints and one test file that runs the same checks on every row: 401 without or with a bad token; 403 for a pending phone, a password not yet changed, a blocked phone and every role not listed; 404 for another workspace's or another area's record; 422 / 404 for a bad or unknown id; lists hold only the user's own records; refused writes change nothing. A route in the OpenAPI schema without a row fails the run. Files: `tests/endpoints.py`, `tests/test_endpoint_rules.py`, `tests/conftest.py`. Test: removing the area filter from `/voters` or the role check from device approval makes the checks fail. (11 Nov)
- [x] **4.4 `GET /voters/{id}` and `PUT /voters/{id}/survey`.** First save creates the survey row; a stale `version` returns 409 with the server copy; notes limited to 2,000 characters. A booth agent can read the voter but not save a survey. Files: `app/routers/voters.py`, `tests/test_survey.py`. Test: two saves with the same version give one 200 and one 409; a booth agent's save gets 403. (13 Nov)
- [x] **4.5 `GET /devices`** (admin; filter by status) so the admin can find the waiting phone. Files: `app/routers/devices.py`, `tests/test_devices_admin.py`. Test: an admin sees only phones of the own constituency. (13 Nov)
- [x] **4.6 `GET /sync/pull`, first download.** Pages of areas, voters, surveys, lists and settings for the user's area, then the watermark. Files: `app/routers/sync.py`, `app/sync_pull.py`, `tests/test_sync_pull.py`. Test: all pages together equal the user's area exactly. (14 Nov)
- [x] **4.7 `GET /sync/pull?since=W`.** Rows with `sync_xid >= W`, the current list of assigned areas (the phone drops the rest), and the wipe signal for a blocked phone. Files: same. Test: a survey changed after W comes back; a blocked phone gets `wipe`. (14 Nov)
- [x] **4.8 `POST /sync/push`** for surveys. `sync_mutations` makes a retry safe; a stale version goes to `sync_conflicts`; each item gets its own result; an item the user's role may not send is rejected on its own. Files: `app/routers/sync.py`, `app/sync_push.py`, `tests/test_sync_push.py`. Test: the same batch sent twice changes the data once; a survey pushed by a booth agent is rejected. (15 Nov)
- [x] **4.9 Demo users.** One admin, one supervisor, one surveyor with two parts, in workspace `naik`. Files: `scripts/create_demo_users.py`. Test: the surveyor's first download has only those two parts. Merge to `main`. (15 Nov)
- [x] **4.10 Contract for the remaining endpoints.** Request and response shapes for steps 7–11, with routes that answer 501, so the portal can be built against `openapi.json` now. Files: `app/schemas.py`, `app/routers/*.py`, `tests/test_openapi.py`. Test: every path in `docs/02_tech_stack_and_api.md` is in `openapi.json`. (16–17 Nov, two sessions)

Done when: a script can log in, get approved, download an area, save a survey and push it, with nothing visible from another workspace or area.

Portal (teammate): login, voter list, search and profile, phone approval list. After 4.10: every other portal screen against the 501 contract with mocked data.

## Step 5 – Android demo app · 14–23 Nov · branch `step5-android-demo`

Goal: the demo flow on a real phone, working without internet.

- [x] **5.1 Project.** Kotlin, Compose, Hilt, minSdk 26, debug and release builds with their own server address, signing key kept outside git. Files: `android/` Gradle files, `A/JansetuApp.kt`, `A/MainActivity.kt`. Test: the debug APK installs and runs on the Android 15 emulator (12 Nov) and on my Android 16 phone (5.13). There is no Android 8 device yet: that check is 12.11. (14 Nov)
- [x] **5.2 Local database.** Room + SQLCipher, key from Android Keystore; tables for areas, voters, surveys, lists, outbox and sync state. Files: `A/data/local/`. Test: `androidTest` writes and reads a voter; the database file is not readable without the key. (15 Nov)
- [x] **5.3 Search.** FTS table over English name, Marathi name, EPIC, house and mobile; a number also finds a serial. Search screen showing results while typing. Files: `A/data/local/VoterFts.kt`, `A/ui/search/`. Test: 32,000 fake voters, English and Marathi prefix search each answer in under 200 ms on the test phone. (16 Nov)
- [x] **5.4 API client.** Retrofit + OkHttp, encrypted token store, automatic refresh on `token_expired`, error body mapping. Files: `A/data/remote/`. Test: fake server returns `token_expired` once; the call succeeds after one refresh. (17 Nov)
- [x] **5.5 Login, Set password, Device approval.** The Login screen is built without the language buttons shown in the screen flow (labels are English only). Files: `A/ui/login/`, `A/ui/setup/`. Test: wrong password shows the server message; a waiting phone moves on by itself after approval. (17–18 Nov)
- [x] **5.6 First download.** Paged pull with progress, safe to resume after the app is closed. Files: `A/data/sync/PullWorker.kt`, `A/ui/setup/FirstSyncScreen.kt`. Test: stopping at page 3 and reopening finishes with the right voter count. (18–19 Nov)
- [x] **5.7 Home, bottom bar, More menu shell.** Counts come from the local database. Files: `A/ui/home/`, `A/ui/nav/`. Test: counts match the database in airplane mode. (19 Nov)
- [x] **5.8 Filters:** ward, booth, age, gender, colour tag, survey status. Files: `A/ui/search/FiltersScreen.kt`. Test: each filter alone and two together give the same count as a direct query. (20 Nov)
- [ ] **5.9 Voter profile, Details tab,** with call, WhatsApp and SMS through the phone's own apps. Files: `A/ui/voter/`. Test: manual check on a phone; no internet permission is needed for the intents. (20 Nov)
- [x] **5.10 Survey tab.** Mobiles, caste, profession, colour tag, residence check, date of birth, notes; location only at save. Saved locally and added to the outbox. Read-only for a booth agent. Files: `A/ui/voter/SurveyScreen.kt`, `A/data/OutboxRepository.kt`. Test: a save in airplane mode shows at once and leaves one outbox item. (21 Nov)
- [x] **5.11 Push, delta pull and the Sync screen.** WorkManager every 15 minutes and "Sync now"; a conflict is shown, not lost. Files: `A/data/sync/`, `A/ui/sync/`. Test: with a fake server, a failed push is retried with the same UUID; a conflict item appears on the Sync screen. (21–22 Nov)
- [x] **5.12 Blocked phone and logout.** A wipe signal deletes the local database. Files: `A/data/sync/WipeHandler.kt`. Test: after the signal the database file is gone and the app is at Login. (22 Nov)
- [x] **5.14 Client changes: database and survey API.** One migration holds every schema change in the client's list, so parallel sessions do not each add a `002`: the white colour tag is switched off and no longer seeded (a voter without a tag has none); lists `positions` and `influencer_types` (placeholder entries until the client sends the real ones); `voter_surveys` gets `position_id`, `influencer_type_id`, `in_self_help_group`, `self_help_group_name` and `ration_card` (AAY / PHH / NPHH); table `part_notes` (one shared note per part, with `version`); `polling_start_time` and `polling_end_time` in the election settings. The survey body (PUT, push and pull) gains `is_important`, `position_id`, `is_influencer`, `influencer_type_id`, the self help group pair and `ration_card`; the two new lists ride in the pull; `GET /voters?important=true`. Files: `db/migrations/002_client_changes.sql`, `db/seed/seed.py`, `app/routers/voters.py`, `app/sync_pull.py`, `app/schemas.py`, `tests/test_survey.py`, `tests/test_voters_list.py`. Test: a position without "important", an influencer type without "influencer" or a group name without "self help group" is 422; a ration card outside the three is 422; a new workspace has no white tag. (13 Nov)
- [x] **5.15 Client changes: contract.** Spelling fixes leave the API (`/name-fixes`, push type `name_fix`, `name_fixes_waiting`). Every write to official roll data becomes super admin only (`POST /rolls/imports`, row resolve, apply, discard, `POST /voters`, `PATCH /voters/{id}/roll`, remove, restore): an admin gets 403 and can still read imports and roll edits. New 501 routes with their shapes: `POST /families`, `PATCH /families/{id}`, `GET /booths/{id}/families`, `GET/PUT /booths/{id}/note`, push types `family_new` and `part_note`; `leave_family` in the family change. `GET /families` stays the walk list: changing a published shape would break the portal ("add, never break"). Polling times in the election settings shapes. Files: `app/routers/*.py`, `app/schemas*.py`, `tests/endpoints.py`, `docs/02_tech_stack_and_api.md`, `docs/openapi.json`. Test: an admin's roll write is 403; the endpoint table and the API document match `openapi.json`. Tell the teammate the same day: two routes are removed (never built), everything else is added. (13 Nov)
- [ ] **5.16 Client changes: Survey screen and Important filter.** Important voter = Yes shows a searchable position picker; Influencer = Yes shows the influencer type; Self help group = Yes shows the group name; Ration card has three choices; no white tag. Filters gets "Important voters". Local database version 2 (no upgrade code: no phone holds data yet, and logout deletes it). Files: `A/ui/voter/SurveyScreen.kt`, `A/ui/search/FiltersScreen.kt`, `A/data/local/`, `A/data/remote/ApiModels.kt`, `A/data/OutboxRepository.kt`. Test: switching Important to No clears the position in the saved item; the Important filter gives the same count as a direct query. (14 Nov)
- [ ] **5.13 Rehearsal on a real phone** against the server: full flow, then survey in airplane mode, reconnect, sync, see the change from a second login. Fix what breaks. Merge to `main`. (23 Nov)

Done when: the demo script below runs twice in a row without touching the laptop.

Portal (teammate): nothing from this step.

## Step 6 – Server · 19–23 Nov · branch `step6-server`

Goal: the API on the KVM 4 with HTTPS, and a laptop fallback that has been tried.

- [ ] **6.1 Production containers,** tried on the laptop first: `caddy`, `api`, `db`. Files: `backend/Dockerfile`, `deploy/docker-compose.yml`, `deploy/Caddyfile`, `deploy/.env.example`. Test: `docker compose up` on the laptop, `/api/v1/health` answers through Caddy. (19 Nov)
- [ ] **6.2 Nightly backup.** `pg_dump` at night, 14 days kept. Files: `scripts/backup.sh`, `scripts/restore.sh`. Test: on the laptop, restore a dump into a scratch database and compare row counts. (19 Nov)
- [ ] **6.3 APK download and `GET /app/version`.** Caddy serves the APK; a script adds the `app_releases` row. Files: `app/routers/app_version.py`, `scripts/publish_apk.py`, `tests/test_app_version.py`. Test: the endpoint returns the newest row without a token. (20 Nov)
- [ ] **6.4 Server setup** when the KVM 4 arrives: Ubuntu LTS, SSH keys only, firewall open for 22, 80, 443, Docker, domain pointed, compose up, HTTPS working. Check whether the Hostinger plan includes snapshots and switch them on if it does. Files: `deploy/README.md` (the exact commands). Test: `https://<domain>/api/v1/health` from a phone on mobile data. (20–21 Nov)
- [ ] **6.5 Data on the server.** Migrations, super admin, then I copy the dev database over SSH myself. Test: voter count on the server is 31,871. (21 Nov)
- [ ] **6.6 Laptop fallback.** Phone and laptop on one hotspot; the debug build lets me type the server address. Test: full demo flow against the laptop. Do this even if the server arrives on time. (22 Nov)

Done when: the phone syncs with the server over HTTPS, and with the laptop when the server is switched off.

Portal (teammate): gives me the static build folder; Caddy serves it at the domain root after the demo (subtask 9.9).

## Demo · 24–25 Nov

- [ ] **24 Nov: freeze.** No new features. Run the script twice on the demo phone and once on the laptop fallback. Charge the phone, install the final APK, check the server.
- [ ] **25 Nov: demo script.** Install the APK from the server → log in with a temporary password → set a new password → "waiting for approval" → admin approves → first download → search by name, EPIC and house → open a voter → airplane mode → save a survey → internet back → sync → the change is on the server.

Not in the demo: Marathi search (the roll has no Marathi names yet). Say so before the client asks.

## Step 7 – Field screens · 26–27 Nov · branch `step7-field`

Goal: everything a surveyor uses besides the survey. Each subtask is the endpoint, its sync part and its screen together.

- [ ] **7.1 Families made by hand.** The client (12 Nov) wants surveyors to make families themselves, so the script that grouped voters by house number is dropped. `POST /families` (free-text name, in one booth; the phone makes the UUID), `PATCH /families/{id}` (rename), `PUT /voters/{id}/family` (add to a family, take out with `leave_family`, set the head), `GET /voters/{id}/family`, `GET /booths/{id}/families` (the booth's families). `GET /families` stays the walk list (houses), as in the 4.10 contract. Files: `app/routers/families.py`, `tests/test_families.py`. Test: a voter is in one family at most; a family in booth 2 is 404 for a booth 1 surveyor; a booth agent cannot make one. (26 Nov)
- [ ] **7.2 Families in sync.** Families and their members in the pull; push types `family_new` and `family`. Files: `app/sync_pull.py`, `app/sync_push.py`, `tests/test_sync_families.py`. Test: a family made offline and pushed twice exists once. (26 Nov)
- [ ] **7.3 Visits API:** `POST /voters/{id}/visits`, visits in push. Files: `app/routers/visits.py`, `tests/test_visits.py`. Test: a visit pushed twice is stored once. (26 Nov)
- [ ] **7.4 Screens: Family, Walk list.** Family tab: make a family, name it, add members from search, take a member out. The walk list still goes house by house: it groups the booth's voters by the roll's house number on the phone and needs no family rows. Files: `A/ui/family/`, `A/ui/walklist/`. Test: marking a house "not home" offline shows on the walk list and syncs; a family made offline shows at once. (26 Nov)
- [ ] **7.5 New voters:** `GET/POST /new-voters`, `PATCH /new-voters/{id}` with `version`, in pull and push. Screens: New voter, New voters list. Files: `app/routers/new_voters.py`, `tests/test_new_voters.py`, `A/ui/newvoter/`. Test: stale version gives 409. (26 Nov)
- [ ] **7.6 History:** `GET /voters/{id}/history` from `audit_log`. Every update is listed (survey, notes, family, visits, voted marks, roll corrections), each with the fields that changed, the old and the new value, who and when. Screen: History tab (needs internet; says so when offline). Files: `app/routers/voters.py`, `tests/test_history.py`, `A/ui/voter/HistoryTab.kt`. Test: a survey save appears with user, time and the changed fields. (27 Nov)
- [ ] **7.7 Voter slip:** drawn on the phone as an image, with the polling date and time from the election settings, and shared to WhatsApp; `POST /voters/{id}/slip-events` through push. Files: `A/ui/slip/`, `app/routers/slips.py`, `tests/test_slips.py`. Test: sharing offline leaves one outbox item. (27 Nov)
- [ ] **7.8 Birthdays and Select many.** `GET /birthdays`; both screens read the local database; bulk colour tag goes through the outbox. Files: `app/routers/birthdays.py`, `A/ui/birthdays/`, `A/ui/search/BulkSelectScreen.kt`. Test: tagging 50 voters makes 50 outbox items and one push. (27 Nov)
- [ ] **7.9 More menu items:** Terms (`GET /terms/current`, `POST /terms/accept`; the text comes from the client, and until it arrives the screen shows a line saying so), Announcements (`GET`, `POST .../read`), Help and report a problem (`POST /problem-reports`), Update required, Change password. Files: `app/routers/misc.py`, `tests/test_misc.py`, `A/ui/more/`. Test: an app below the minimum version is sent to Update required. (27 Nov)
- [ ] **7.10 Conflict review:** `GET /sync/conflicts`, `POST /sync/conflicts/{id}/resolve` (contract in 4.10). A surveyor sees and resolves their own; supervisor and above any in their area. Keeping the phone's value writes it with a new version. Screen: conflicts on the Sync screen. Files: `app/routers/sync.py`, `tests/test_conflicts.py`. Test: keep-phone writes the value once; another surveyor's conflict is 404. (27 Nov)
- [ ] **7.11 Part notes.** One shared note per part (up to 2,000 characters) that everyone assigned to the part sees: `GET/PUT /booths/{id}/note` with `version`, in pull and push (`part_note`). Surveyor and above can write; a booth agent reads. Shown at the top of the walk list and on the Survey tab. Files: `app/routers/part_notes.py`, `tests/test_part_notes.py`, `A/ui/partnote/`. Test: a note saved offline reaches a second phone on its next sync; a stale version gives a conflict, not a lost note. (27 Nov)
- [ ] **7.12 Share to families on WhatsApp.** On the family list, tick up to 5 families and choose the voter slip or a message (the candidate message from the election settings, editable before sending). The phone's own WhatsApp then opens for **every voter in those families who has a mobile number**, one after another, each with their own slip or the message; the worker presses send each time. Not the family head only (client, 12 Nov). No WhatsApp API; a sixth family is refused. Voters without a mobile are skipped and counted. Files: `A/ui/family/ShareFamiliesScreen.kt`. Test: 2 families with 3 and 4 voters who have mobiles open WhatsApp 7 times, each with the right voter's slip; a voter without a mobile is skipped and counted. (27 Nov)

Portal (teammate): family view (hand-made families), new voters list, voter history.

## Step 8 – Polling day · 27–28 Nov · branch `step8-polling-day`

Goal: mark who has voted, one by one or many, offline.

- [ ] **8.1 Turnout API:** `POST /turnout/marks` (by voter or by booth + serials), `DELETE /turnout/marks/{voter_id}`, `GET /turnout/summary`; marks in pull and push. Allowed for booth agent, supervisor, admin and super admin; not for a surveyor. Files: `app/routers/turnout.py`, `tests/test_turnout.py`. Test: marking the same voter from two phones leaves one mark; a booth agent cannot mark another booth; a surveyor gets 403. (27 Nov)
- [ ] **8.2 Screens: Polling day, Mark voted.** For a surveyor the tab only says polling day is not part of their role. Files: `A/ui/polling/`. Test: marks made offline upload on reconnect; the unsent count is shown. (28 Nov)
- [ ] **8.3 Screen: Mark many voted** (typed serials and ranges, or ticked from the booth list). Files: `A/ui/polling/BulkVotedScreen.kt`. Test: "12, 15, 18-25" marks 10 voters and skips one already marked. (28 Nov)

Portal (teammate): turnout by booth.

## Step 9 – Admin · 28–29 Nov · branch `step9-admin`

Goal: an admin can run the workspace from the phone and the portal.

- [ ] **9.1 Users:** `GET/POST /users`, `GET/PATCH /users/{id}`, `POST /users/{id}/reset-password` (limit 200). Files: `app/routers/users.py`, `tests/test_users.py`. Test: the 201st user is refused; an admin cannot create a user in another constituency. (28 Nov)
- [ ] **9.2 Assignments:** `GET/PUT /users/{id}/assignments`. Files: same router, `tests/test_assignments.py`. Test: after a booth is removed, the next pull tells the phone to drop it. (28 Nov)
- [ ] **9.3 Constituencies:** `GET/POST/PATCH /constituencies` (limit 5, super admin). Files: `app/routers/constituencies.py`, `tests/test_constituencies.py`. (28 Nov)
- [ ] **9.4 Settings and lists:** `GET/PUT /settings/election` (admin and super admin can both save the election and the candidate, with polling start and end time), `GET/POST/PATCH /masters/{list}` (also positions and influencer types), `POST /files`. Files: `app/routers/settings.py`, `app/routers/masters.py`, `app/routers/files.py`, tests for each. Test: a renamed colour tag reaches the phone on the next pull; an admin's election save works and a supervisor's gets 403. (28 Nov)
- [ ] **9.5 Team and logs:** `POST/DELETE /announcements`, `GET /problem-reports`, `GET /audit-log`, `GET /reports/worker-activity`, `GET /worker-locations`. Files: `app/routers/admin_logs.py`, `tests/test_admin_logs.py`. (29 Nov)
- [ ] **9.6 Screens: Users & devices, Add user (also Add admin), Booths & karyakartas.** Files: `A/ui/admin/users/`. Test: approve a waiting phone from the app. (29 Nov)
- [ ] **9.7 Screens: Constituencies, Election & candidate (with polling time), Lists & labels (with positions and influencer types).** Files: `A/ui/admin/settings/`. (29 Nov)
- [ ] **9.8 Screens: Activity log, Worker activity, Worker locations.** Files: `A/ui/admin/logs/`. (29 Nov)
- [ ] **9.9 Portal files on the server.** Caddy serves the teammate's build. Files: `deploy/Caddyfile`. Test: the portal login page loads from the domain. (29 Nov)

Portal (teammate): users, assignments, phones, constituencies, election settings, lists, announcements, activity log, worker activity.

## Step 10 – Roll update and data quality · 29–30 Nov · branch `step10-roll`

Goal: apply a new roll without losing survey work, and clean the list.

Client, 12 Nov: only a super admin may change official roll data. Upload, resolve, apply, discard, add, correct, remove and restore answer 403 to everyone else; an admin can still read imports and roll edits (contract in 5.15).

- [ ] **10.1 Worker.** One process that takes queued rows with `FOR UPDATE SKIP LOCKED`. Files: `app/worker.py`, `deploy/docker-compose.yml`, `tests/test_worker.py`. Test: two workers never take the same job. (29 Nov)
- [ ] **10.2 Roll upload and matching** for CSV and Excel: `POST /rolls/imports`, `GET /rolls/imports`, `GET /rolls/imports/{id}`, `.../rows`. Files: `app/routers/rolls.py`, `app/roll_match.py`, `tests/test_roll_import.py`. Test: a fake roll with one changed name, one new and one missing voter gives matched, uncertain, new and absent rows. (29 Nov, two sessions)
- [ ] **10.3 Review and apply:** `.../rows/{row_id}/resolve`, `.../apply`, `.../discard`. Test: after apply, surveys are still linked, the missing voter is "not in current roll" and nobody is marked dead. Files: same. (30 Nov)
- [ ] **10.4 One-voter corrections:** `POST /voters`, `PATCH /voters/{id}/roll`, `.../remove`, `.../restore`, `GET /voters/{id}/roll-edits`. Files: `app/routers/roll_edits.py`, `tests/test_roll_edits.py`. Test: a removed voter is hidden from search and comes back with restore; an admin's correction gets 403. (30 Nov)
- [ ] **10.5 Data quality:** `GET /data-quality/summary`, `/data-quality/duplicates`, `.../resolve`, `POST /mobile-imports`, `GET /mobile-imports/{id}`. Files: `app/routers/data_quality.py`, `tests/test_data_quality.py`. (30 Nov)
- [ ] **10.6 Screens: Data quality, Repeated voters, Roll update, Correct roll record, Mobile numbers & contacts.** No Spelling fixes screen (client, 12 Nov). Roll update and Correct roll record are shown to a super admin only. Files: `A/ui/quality/`, `A/ui/admin/roll/`. (30 Nov, two sessions)

Portal (teammate): roll upload, matching review and corrections (super admin only), duplicates, mobile number sheets. No spelling fixes page.

## Step 11 – Reports and exports · 30 Nov · branch `step11-reports`

Goal: charts and printed lists; then hand over the working APK.

- [ ] **11.1 Reports:** `GET /reports/survey-progress`, `/colour-tags`, `/demographics`, `/turnout`. Files: `app/routers/reports.py`, `tests/test_reports.py`. Test: totals equal direct counts; a supervisor gets only own wards. (30 Nov)
- [ ] **11.2 Exports:** `POST /exports`, `GET /exports/{id}`, `.../download`; the worker writes Excel and PDF. Files: `app/routers/exports.py`, `app/export_jobs.py`, `tests/test_exports.py`. Test: an Excel export of a filter has the same rows as `GET /voters` with that filter. (30 Nov)
- [ ] **11.3 Screens: Reports & charts, Print or export a list.** Files: `A/ui/reports/`. (30 Nov)
- [ ] **11.4 Working APK.** Signed release build on the server through `publish_apk.py`; link sent to the client. Test: an older build shows Update required and installs the new one. (30 Nov)

Portal (teammate): reports, charts, exports.

## Step 12 – Hardening and handover · 1–15 Dec · branch `step12-delivery`

Goal: what the SRS promises for final delivery.

- [ ] **12.2 `GET /voters/{id}/slip`** from the server, for the portal. Files: `app/routers/slips.py`. (3 Dec)
- [ ] **12.3 Fixes from client testing.** The client reports within 3 working days of 30 Nov, so by 3 Dec. One session per group of fixes. (3–10 Dec)
- [ ] **12.4 Load test: 200 users syncing at once** on the server, in a fake workspace. Files: `scripts/loadtest.py`, results in `docs/load_test.md`. Pass mark: no errors and 95% of sync calls under 3 seconds (my figure; the SRS gives none). (5–6 Dec)
- [ ] **12.5 Backups stored away from the server,** and a restore test. An office computer pulls the newest dump over SSH every night (and at next start if it was off) and keeps 14 days; the Hostinger snapshot is the second copy if the plan includes one. The copy holds real voter data, so it stays in a folder only I can open. Files: `scripts/pull_backup.ps1` (or `.sh`, to match the office computer), `scripts/backup.sh`, `docs/handover.md`. Test: last night's dump, taken from the office computer, restored into a scratch database; counts match. (7 Dec)
- [ ] **12.6 Isolation check.** Every endpoint in `openapi.json` has its other-workspace and other-area test. Files: `tests/test_coverage_of_isolation.py`. (8 Dec)
- [ ] **12.7 Server check.** New secrets, CORS only for the portal domain, API docs page off or admin only, disk and log size. Files: `deploy/`. (9 Dec)
- [ ] **12.8 Handover notes.** Server access, deploy, backup and restore, new workspace and admin, publishing an APK, known limits. Files: `docs/handover.md`. (10–11 Dec)
- [ ] **12.9 Admin training** with the client, using the notes. (12–14 Dec)
- [ ] **12.11 Android 8 check.** Moved from 5.1: install the release APK on an Android 8 phone or emulator and run the demo script. The SRS promises Android 8.0 or newer. Test: the demo script passes on Android 8.0. (4 Dec)
- [ ] **12.10 Final delivery.** Final APK published, tag `v1.0` on `main`. (15 Dec)

Portal (teammate): fixes from client testing, final build on the server by 10 Dec. Public website pages only if the client's content arrives by 1 Dec; otherwise they are dropped and I tell the client in writing.

## Step 13 – Scanned roll PDFs (OCR) · 1–9 Dec · branch `step13-roll-ocr`

Goal: an election office roll PDF in, the import CSV out, without typing. In the SRS from version 1.1 (12 Nov), for final delivery. Details, numbers and pitfalls: `context/roll_ocr.md`.

The PDFs are page images with no text (part 49: 30 pages of 949 × 1343 at 115 dpi, letters about 6 pixels tall). Free tools only, run on this laptop (its GPU may be used); voter data never goes to an outside service. Output is the 35-column CSV that `scripts/import_roll_parts.py` already takes. The 51 CSVs are the answer key: parts 1–35 tune the reader, parts 36–51 test it. They were made with an AI tool (Antigravity), not typed and checked, so a disagreement is not automatically an OCR error (13.5). English rolls only: Maharashtra is not being built now (12 Nov). Never print names or EPICs: counts and percentages only.

- [ ] **13.1 Measure first.** Install Tesseract 5 and OpenCV; take the page images out of part 49 at their own size; cut and read the boxes as simply as possible; record accuracy per field and seconds per page. Go / no-go: if names are far from the target, stop and decide with the client before more is built. Files: `context/roll_ocr.md`. Test: the numbers are written down. (1 Dec)
- [ ] **13.2 Page and box cutter.** Page types (cover, voter pages, supplement, summary with the total), the 3 × 10 grid found from its lines with a layout profile as fallback; an unknown layout is refused, never guessed. A fake roll page drawn in the test (fake names, same layout, 115 dpi) so the normal suite runs without private data. Files: `app/roll_ocr/pages.py`, `app/roll_ocr/layout.py`, `tests/test_roll_ocr_layout.py`. Test: the fake page gives 30 boxes; a shifted grid is refused. (2 Dec)
- [ ] **13.3 Field reading and rules.** One crop per field, enlarged 3–4 times; digits-only reading for serial and age, letters-and-digits for EPIC; EPIC fixed by position (3 letters + 7 digits); relation from the printed label; "DELETED" stamp. Files: `app/roll_ocr/fields.py`, `tests/test_roll_ocr_fields.py`. Test: every field of the fake page is exact. (3 Dec)
- [ ] **13.4 Better reading.** Tesseract fine-tuned on real boxes from parts 1–35; a second, different reader (PaddleOCR); a field is accepted when the two agree, otherwise it goes to review. Files: `app/roll_ocr/readers.py`, `scripts/roll_ocr_train.py`. Test: held-out accuracy up and review rate down against 13.1. (4–5 Dec, two sessions)
- [ ] **13.5 Checks, CSV, review file, accuracy test.** EPIC format (reuse `EPIC_RE`) and unique in the part, age 18–120, gender, serials 1..N without gaps, count equals the summary page. Clean rows to the CSV; failed rows to a private review file with the reason and the box image. A part is imported whole or not at all: it waits until every row is clean or reviewed, and its count matches the summary page (decided 12 Nov: half a part leaves serial gaps for polling day, and a later roll update would call the missing voters "not in current roll"). The accuracy test joins on part + serial and reports per field: exact, sent to review, and silent errors (wrong and not flagged). It skips when the private PDFs are absent. Files: `app/roll_ocr/checks.py`, `app/roll_ocr/output.py`, `tests/test_roll_ocr_accuracy.py`. Disagreements with the answer key go to a private file with both values and the box image, for you to judge by eye; where the CSV was wrong, it is corrected and the case counted. Test: on parts 36–51, EPIC and age have zero silent errors and every field 99%+ or the gap is reported; part 49 imports with `--dry-run`; the part 4 PDF gives a part 4 CSV that is not the copy of part 3. (6 Dec)
- [ ] **13.6 Batch tool.** `scripts/roll_ocr.py --in DIR --out DIR --shard 2/4 --workers N`: a folder of PDFs, split by file name across machines, resumes by file hash, needs no database. Run all 51 parts. Files: `scripts/roll_ocr.py`, `requirements-ocr.txt`. Test: every part's count equals its summary page and the database; a second run does nothing. (7 Dec)
- [ ] **13.7 Admin upload.** A PDF in `POST /rolls/imports` (super admin) → job → worker runs the same library → rows in `roll_import_rows` → the review and apply of 10.2–10.3. One new endpoint for a review row's box image. Optional `ocr-worker` container, off by default. Files: `app/routers/rolls.py`, `app/worker.py`, `deploy/docker-compose.yml`, `tests/test_roll_import_pdf.py`. Test: a fake PDF goes from upload to applied. (8 Dec)
- [ ] **13.9 Local AI helper (optional, off by default).** A small vision model on the laptop GPU for boxes still in review; its answer is never accepted unless it agrees with one of the readers. Only if the review rate after 13.5 is still too high. Files: `app/roll_ocr/ai_fallback.py`. Test: switched off, nothing changes; switched on, the review rate on parts 36–51 drops with no new silent errors. (9 Dec)

Not now (12 Nov): Marathi / Maharashtra rolls. The SRS adds them only after the client gives sample PDFs and a checked list; the layout profile and the second reader are built so a Devanagari profile can be added later.

Portal (teammate): PDF upload on the roll upload page, and the box image next to a review row.

## Client changes of 12 Nov

The client sent these on 12 Nov. They are in the tasks above and in `docs/01_srs.md` version 1.1, which also adds scanned roll PDFs (Step 13). The client approved version 1.1 on 12 Nov.

| Client's change | Tasks | What it means here |
|---|---|---|
| Survey: remove white from the colour tags | 5.14, 5.16 | The white "Other" tag is switched off. A voter without a tag simply has none. Tags are Ours, Opposite, Doubtful. |
| Important voter = Yes shows a position | 5.14, 5.16, 9.4 | New list `positions`, searchable on the phone. Placeholder entries until the client sends the real list. |
| Influencer = Yes shows an influencer type | 5.14, 5.16, 9.4 | New list `influencer_types`. The client has not named the types yet; placeholders until then. |
| Remove Two-Wheeler and Mandal/Group | none | Neither was built (they are only on the wireframe). They stay out of the form. |
| Self help group = Yes shows a group name | 5.14, 5.16 | Yes/no plus a free-text name. |
| Ration card: only AAY, PHH and NPHH | 5.14, 5.16 | One of the three, or empty. |
| Synced notes for the entire part | 5.14, 7.11 | Assumed: one shared note per part that the whole team edits, not a list of dated notes. |
| Important voters filter | 5.14, 5.16 | On the phone and in `GET /voters`. |
| Families are made by hand, not from house numbers | 7.1, 7.2, 7.4 | The house-number script is dropped. Assumed: the walk list still goes house by house. |
| Family name is free text | 7.1 | Uses `families.label`. |
| WhatsApp to at most 5 families at a time, no API | 7.12 | The phone's own WhatsApp, to every voter in the chosen families who has a mobile (not the head only), one after another. The voter slip or a message. |
| History tracks every update (what, who, when) | 7.6 | Already in the SRS; the task now names the changed fields with old and new values. |
| Polling time on voter slips | 5.14, 7.7, 9.4, 12.2 | Start and end time in the election settings. |
| Admin and super admin can edit elections and candidates | 9.4 | The contract already allowed both; a test is added. Assumed: still one election and one candidate per workspace, as in the SRS. |
| Remove the Spelling fixes screen | 5.15, 10.5, 10.6 | Screen, endpoints and push type go. 42 screens. |
| Only a super admin can edit official roll data | 5.15, 10.2–10.4, 10.6 | Changes the SRS roles table: an admin no longer imports or corrects rolls. |
| Not registered = new voter | none | No change. |

Questions for the client that these raise:

1. The real list of positions, and the list of influencer types.
2. Part notes: one shared note per part, or many dated notes?
3. ~~WhatsApp to 5 families: what is sent, and to whom?~~ Answered 12 Nov: slips and messages go to every voter in the families, not the head only.
4. Does the walk list stay house by house, from the roll's house numbers?
5. May an admin still see roll imports and corrections, without changing them?

Done 12 Nov: `docs/01_srs.md` version 1.1 has all of these, the scanned roll PDFs, and the old app's data marked as not imported. Questions 1, 2 and 4 are in its "Points for the Company to confirm".

## The 42 screens

43 in the wireframes; the client removed Spelling fixes on 12 Nov. Part notes and family sharing sit on existing screens.

| Step | Screens | Count |
|---|---|---|
| 5 (demo) | Login, Set password, Device approval, First download, Home, Search, Filters, Voter profile, Voter survey, Sync & list updates | 10 |
| 7 | Family, Walk list, Voter history, Voter slip, Birthdays, New voter, New voters list, Select many voters, More, Terms of use, Update required, Announcements, Help & support | 13 |
| 8 | Polling day, Mark voted, Mark many voted | 3 |
| 9 | Users & devices, Add user, Booths & karyakartas, Constituencies, Election & candidate, Lists & labels, Activity log, Worker activity, Worker locations | 9 |
| 10 | Data quality, Repeated voters, Roll update, Correct roll record, Mobile numbers & contacts | 5 |
| 11 | Reports & charts, Print or export a list | 2 |

## SRS items that are risky for the dates

1. **All 42 screens by 30 Nov.** 10 are done by the demo; the other 32, with about 75 endpoints, fall in 26–30 Nov. This is the biggest risk in the plan. If it slips, the last things in line are steps 10 and 11 on the phone, because the portal covers the same work.
2. **Marathi names and search.** The roll has English names only and the SRS excludes automatic conversion. The app will be built and tested for Marathi with fake data, but real Marathi names need a Marathi roll from the client.
3. **Server around 20 Nov.** Five days before the demo, and a domain must be bought and pointed first. Subtask 6.6 is the fallback.
4. **Scanned roll PDFs (Step 13).** The election office PDFs have no text, only 115 dpi page images, so they need OCR. 99% on names is not certain at that resolution; EPIC and age are easier. Maharashtra is not being built now. The answer key was made with an AI tool, so its own errors must be told apart from OCR errors. Step 13 adds about 8 sessions in 1–9 Dec on top of Step 12; 13.7 and 13.9 slip first. 13.1 measures before anything more is promised. The SRS promises the reading and the review list, not an accuracy figure.
5. **Roll matching and review.** The SRS describes the result, not the rules for "clear" and "uncertain" matches. I will use: same EPIC = clear; same booth, serial and similar name = clear; anything else similar = uncertain.
6. **PDF lists in Marathi.** Devanagari needs a PDF tool that shapes the letters correctly; to be tried in 11.2 before promising a layout.
7. **Client feedback window.** Problems from the demo arrive up to 28 Nov, in the middle of steps 7–9.
8. **Portal.** The teammate's screens depend on my endpoints; subtask 4.10 gives the full contract by 17 Nov so the portal is not waiting for steps 9–11.
9. **"Existing data will be imported before the demo."** The client has since decided against it; the SRS line should be changed in writing.
10. **Part 4 file is a copy of part 3.** About 688 voters are missing until the client sends the right file.
11. **Content from the client.** The terms of use text and the public website pages come from the client. No website content by 1 Dec means the website pages are dropped.
12. **Client changes of 12 Nov.** Six more sessions (5.14–5.16, 7.11, 7.12, 12.11); spelling fixes and the house-number script fall away. Five of the six land before 30 Nov, on top of risk 1. They are in SRS version 1.1, approved by the client on 12 Nov.

## SRS asks for it; the schema or API document does not cover it yet

Rows marked **Decided** were settled on 11 Nov. The others need a small addition to the contract; I will add nothing without your OK.

| SRS item | Gap | Proposed |
|---|---|---|
| Spelling fixes | The API can list and resolve fixes, but nothing creates one. | **Removed by the client, 12 Nov:** leaves the contract in 5.15. |
| Doubtful "dead" marks, confirmed by a supervisor | No endpoint to mark or confirm. | Two fields in the survey body; confirming needs supervisor. |
| Survey: residence check, location | Not in the API document's survey line (columns exist in the schema). | **Decided 11 Nov:** added to the survey body in 4.4 (`has_new_address` + new address; `location` sets lat/lng/accuracy, left out = kept). |
| Search by serial number or mobile | The server search text has names, EPIC and house only. | Handle numbers in the `/voters` query; no schema change. |
| Candidate photo, symbol, slip header | `POST /files` exists, no way to download. | **In the contract (4.10):** `GET /files/{id}`, all roles. |
| Mobile number sheets | No endpoint to accept or reject a row under review. | **In the contract (4.10):** `POST /mobile-imports/{id}/rows/{row_id}/resolve`. |
| Possible duplicates | Nothing says what creates the pairs. | Worker job after each roll import. |
| Roles | Surveyor and booth agent have the same rank in the code, but the SRS gives polling day only to booth agents and survey only to surveyors. | **Decided:** keep the SRS table. Surveyor does survey, booth agent does polling day; endpoints check a list of allowed roles (4.1, 4.4, 8.1). I confirm it with the client. |
| Conflicts | The screen lets the worker choose "keep mine / keep server"; the API document says supervisor. | **In the contract (4.10), task 7.10:** worker resolves own conflicts, supervisor any in the area (confirm with the client). |
| History tab | `audit_log` is not synced to the phone. | History needs internet; the SRS does not promise it offline. |
| Blocked phone | Nothing records that the phone finished wiping. | The phone reports it on its next `/devices/me` call. |
| Backups "stored separately" | One server, no outside paid services. | **Decided:** a nightly pull to an office computer, plus a Hostinger snapshot if the plan includes one (6.4, 12.5). |
| Terms of use | The table is empty. | **Decided:** the text comes from the client. |
| Public website pages (portal) | No content or page list anywhere. | **Decided:** content comes from the client. None by 1 Dec = the pages are dropped. |
| Roll file format for import | The SRS names file types, not columns. | Use the columns of the 51 part files until a sample arrives. |
| 200 users at once | The schema default is 150 concurrent users; nothing enforces it. | Test at 200, as the SRS says. |

## In the screens, schema or API document but not in the SRS: not built

App labels in Marathi or Hindi (the language buttons on the Login screen), voter photos, Bluetooth slip printing, slip by SMS, saved filters, the extra filter chips (society, influencer; "important" is now built, client 12 Nov), matching the phone's own contacts, a separate karyakarta list for voters, comparing two days in reports. Each is a change request.

**Decided 11 Nov:** none of this is built. The Login screen has no language buttons. The client's changes of 12 Nov are the only additions.
