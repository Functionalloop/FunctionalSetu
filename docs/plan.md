# JANSETU – plan to final delivery

Written 11 Nov 2026; changed 12 Nov, twice, for the client's changes (see "Client changes of 12 Nov" and `docs/change_log.md`), and 13 Nov (Bluehost server, task 6.7, audit of Step 6). The dates on the tasks are the latest dates: on 13 Nov the work is about a week ahead, and a step starts as soon as the one before it is merged. Scope is `docs/01_srs.md` version 1.1 plus the change requests in Step 14, which are built only after the client approves the updated app flow (`docs/app_flow_v2.pdf`).

| Date | Milestone | What must work |
|---|---|---|
| Wed 25 Nov | Demo | Login + phone approval, sync pull/push, area tree, voter list/search/profile, survey save, all offline on a real phone, server deployed |
| Mon 30 Nov | Working APK | The 42 screens of SRS 1.1, with the client's new names (Kutumb Connect, Information Updation, Eligible but Not Registered, Matching Engine) |
| Tue 15 Dec | Final delivery | Fixes from client testing, scanned roll PDF import (English), the change requests of Step 14 as far as the client has approved them and sent their data, live server, backups, restore test, load test, training, handover notes |

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

- [x] **5.1 Project.** Kotlin, Compose, Hilt, minSdk 26, debug and release builds with their own server address, signing key kept outside git. Files: `android/` Gradle files, `A/JansetuApp.kt`, `A/MainActivity.kt`. Test: the debug APK installs and runs on the Android 15 emulator (12 Nov) and on my phone, a vivo I2207 on Android 15 (12 Nov; 5.13). There is no Android 8 device yet: that check is 12.11. (14 Nov)
- [x] **5.2 Local database.** Room + SQLCipher, key from Android Keystore; tables for areas, voters, surveys, lists, outbox and sync state. Files: `A/data/local/`. Test: `androidTest` writes and reads a voter; the database file is not readable without the key. (15 Nov)
- [x] **5.3 Search.** FTS table over English name, Marathi name, EPIC, house and mobile; a number also finds a serial. Search screen showing results while typing. Files: `A/data/local/VoterFts.kt`, `A/ui/search/`. Test: 32,000 fake voters, English and Marathi prefix search each answer in under 200 ms on the test phone. (16 Nov)
- [x] **5.4 API client.** Retrofit + OkHttp, encrypted token store, automatic refresh on `token_expired`, error body mapping. Files: `A/data/remote/`. Test: fake server returns `token_expired` once; the call succeeds after one refresh. (17 Nov)
- [x] **5.5 Login, Set password, Device approval.** The Login screen is built without the language buttons shown in the screen flow (labels are English only). Files: `A/ui/login/`, `A/ui/setup/`. Test: wrong password shows the server message; a waiting phone moves on by itself after approval. (17–18 Nov)
- [x] **5.6 First download.** Paged pull with progress, safe to resume after the app is closed. Files: `A/data/sync/PullWorker.kt`, `A/ui/setup/FirstSyncScreen.kt`. Test: stopping at page 3 and reopening finishes with the right voter count. (18–19 Nov)
- [x] **5.7 Home, bottom bar, More menu shell.** Counts come from the local database. Files: `A/ui/home/`, `A/ui/nav/`. Test: counts match the database in airplane mode. (19 Nov)
- [x] **5.8 Filters:** ward, booth, age, gender, colour tag, survey status. Files: `A/ui/search/FiltersScreen.kt`. Test: each filter alone and two together give the same count as a direct query. (20 Nov)
- [x] **5.9 Voter profile, Details tab,** with call, WhatsApp and SMS through the phone's own apps. Files: `A/ui/voter/`. Test: manual check on a phone; no internet permission is needed for the intents. (20 Nov)
- [x] **5.10 Survey tab.** Mobiles, caste, profession, colour tag, residence check, date of birth, notes; location only at save. Saved locally and added to the outbox. Read-only for a booth agent. Files: `A/ui/voter/SurveyScreen.kt`, `A/data/OutboxRepository.kt`. Test: a save in airplane mode shows at once and leaves one outbox item. (21 Nov)
- [x] **5.11 Push, delta pull and the Sync screen.** WorkManager every 15 minutes and "Sync now"; a conflict is shown, not lost. Files: `A/data/sync/`, `A/ui/sync/`. Test: with a fake server, a failed push is retried with the same UUID; a conflict item appears on the Sync screen. (21–22 Nov)
- [x] **5.12 Blocked phone and logout.** A wipe signal deletes the local database. Files: `A/data/sync/WipeHandler.kt`. Test: after the signal the database file is gone and the app is at Login. (22 Nov)
- [x] **5.14 Client changes: database and survey API.** One migration holds every schema change in the client's list, so parallel sessions do not each add a `002`: the white colour tag is switched off and no longer seeded (a voter without a tag has none); lists `positions` and `influencer_types` (placeholder entries until the client sends the real ones); `voter_surveys` gets `position_id`, `influencer_type_id`, `in_self_help_group`, `self_help_group_name` and `ration_card` (AAY / PHH / NPHH); table `part_notes` (one shared note per part, with `version`); `polling_start_time` and `polling_end_time` in the election settings. The survey body (PUT, push and pull) gains `is_important`, `position_id`, `is_influencer`, `influencer_type_id`, the self help group pair and `ration_card`; the two new lists ride in the pull; `GET /voters?important=true`. Files: `db/migrations/002_client_changes.sql`, `db/seed/seed.py`, `app/routers/voters.py`, `app/sync_pull.py`, `app/schemas.py`, `tests/test_survey.py`, `tests/test_voters_list.py`. Test: a position without "important", an influencer type without "influencer" or a group name without "self help group" is 422; a ration card outside the three is 422; a new workspace has no white tag. (13 Nov)
- [x] **5.15 Client changes: contract.** Spelling fixes leave the API (`/name-fixes`, push type `name_fix`, `name_fixes_waiting`). Every write to official roll data becomes super admin only (`POST /rolls/imports`, row resolve, apply, discard, `POST /voters`, `PATCH /voters/{id}/roll`, remove, restore): an admin gets 403 and can still read imports and roll edits. New 501 routes with their shapes: `POST /families`, `PATCH /families/{id}`, `GET /booths/{id}/families`, `GET/PUT /booths/{id}/note`, push types `family_new` and `part_note`; `leave_family` in the family change. `GET /families` stays the walk list: changing a published shape would break the portal ("add, never break"). Polling times in the election settings shapes. Files: `app/routers/*.py`, `app/schemas*.py`, `tests/endpoints.py`, `docs/02_tech_stack_and_api.md`, `docs/openapi.json`. Test: an admin's roll write is 403; the endpoint table and the API document match `openapi.json`. Tell the teammate the same day: two routes are removed (never built), everything else is added. (13 Nov)
- [x] **5.16 Client changes: Survey screen and Important filter.** Important voter = Yes shows a searchable position picker; Influencer = Yes shows the influencer type; Self help group = Yes shows the group name; Ration card has three choices; no white tag. Filters gets "Important voters". Local database version 2 (no upgrade code: no phone holds data yet, and logout deletes it). Files: `A/ui/voter/SurveyScreen.kt`, `A/ui/search/FiltersScreen.kt`, `A/data/local/`, `A/data/remote/ApiModels.kt`, `A/data/OutboxRepository.kt`. Test: switching Important to No clears the position in the saved item; the Important filter gives the same count as a direct query. (14 Nov)
- [x] **5.13 Rehearsal on a real phone** against the server: full flow, then survey in airplane mode, reconnect, sync, see the change from a second login. Fix what breaks. Merge to `main`. (23 Nov)

Done when: the demo script below runs twice in a row without touching the laptop.

Portal (teammate): nothing from this step.

## Step 6 – Server · 19–23 Nov · branch `step6-server`

Goal: the API on the Bluehost VPS with HTTPS, and a laptop fallback that has been tried.

- [x] **6.1 Production containers,** tried on the laptop first: `caddy`, `api`, `db`. Files: `backend/Dockerfile`, `deploy/docker-compose.yml`, `deploy/Caddyfile`, `deploy/.env.example`. Test: `docker compose up` on the laptop, `/api/v1/health` answers through Caddy. (19 Nov)
- [x] **6.2 Nightly backup.** `pg_dump` at night, 14 days kept. Files: `scripts/backup.sh`, `scripts/restore.sh`. Test: on the laptop, restore a dump into a scratch database and compare row counts. (19 Nov)
- [x] **6.3 APK download and `GET /app/version`.** Caddy serves the APK; a script adds the `app_releases` row. Files: `app/routers/app_version.py`, `scripts/publish_apk.py`, `tests/test_app_version.py`. Test: the endpoint returns the newest row without a token. (20 Nov)
- [x] **6.4 Server setup** on the Bluehost VPS (4 vCPU, 16 GB, 100 GB NVMe, Ubuntu 24.04 LTS; replaces the Hostinger KVM 4, 13 Nov): SSH key "FunctionalServer" only, no password login, firewall open for 22, 80, 443, Docker, domain pointed, compose up, HTTPS working. Check whether the Bluehost plan includes snapshots and switch them on if it does. Files: `deploy/README.md` (the exact commands). Test: `https://<domain>/api/v1/health` from a phone on mobile data. (20–21 Nov)
- [x] **6.5 Data on the server.** I copy a dump of the dev database (the real roll) to the server over SSH; it is restored with `restore.sh --live` (api stopped; this also moves the transaction counter), then `migrate.py` for the role passwords. A super admin made before the restore would be replaced by it, so the users are dealt with afterwards: the copy brings the dev logins with it (13 Nov: 4 users, 3 approved phones, 11 sessions, 3 rehearsal surveys), so on the server the super admin and the demo users get new temporary passwords (`create_super_admin.py --reset`, added 13 Nov; `create_demo_users.py --reset`), phones go back to pending, and the sessions and rehearsal surveys are removed. The admin's phone for the demo is approved with `scripts/approve_phone.py` (6.8). Do the pending server reboot first, and copy one dump back to the laptop afterwards (no backup leaves the server until 12.5). The client was told on 13 Nov that the server is outside India; the copy does not wait for their written answer. Files: `deploy/README.md`, `context/deploy.md`. Test: voter count on the server is 31,871; a dev password no longer logs in; a pull with an old dev watermark still returns later changes. (21 Nov)
- [x] **6.6 Laptop fallback.** Phone and laptop on one hotspot; the debug build lets me type the server address. Test: full demo flow against the laptop. Do this even if the server arrives on time. (22 Nov)
- [x] **6.7 Release keystore and first published APK.** Added 13 Nov: the demo starts by installing the APK from the server, and no task made the signing key. Make the release keystore (`.jks` outside the repo) and `android/keystore.properties` (git-ignored); keep two offline copies of the key and its passwords (e.g. a pen drive in the office and a password manager), never on the server: a lost key means phones cannot update without uninstalling, which deletes unsent surveys. Set `jansetu.releaseApiUrl` to `https://myjansetu.com`, build with `assembleRelease`, publish with `publish_apk.py`. Files: `android/gradle.properties`, `context/android.md`, `context/deploy.md`. Test: a phone on mobile data downloads the APK from `apk_url`, installs it and logs in against the server. (23 Nov)
- [x] **6.8 Phones screen in the app** (added 13 Nov: the teammate may not deliver the portal, so the demo must not need it). The phone-approval part of 9.6, built early: More > Phones for admin and super admin, lists Waiting / Approved / Blocked / All from `GET /devices`, Approve, Block with an optional reason (not your own phone), the Waiting list checks again every 10 s. The first admin phone has nobody to approve it, so `scripts/approve_phone.py` approves it on the server (admin or super admin, waiting phones only). Files: `A/ui/admin/PhonesScreen.kt`, `A/data/remote/`, `scripts/approve_phone.py`, `tests/test_approve_phone.py`. Test: on two real phones over the laptop API, the admin's phone approved by the script, then the surveyor's waiting phone approved from the admin's Phones screen moves on by itself and downloads its parts. (13 Nov)

Done when: the phone syncs with the server over HTTPS, and with the laptop when the server is switched off.

Portal: not needed for the demo (decided 13 Nov). The teammate may not deliver it; the web portal is planned later (9.9 and a portal plan still to be written).

## Demo · 24–25 Nov

- [ ] **24 Nov: freeze.** No new features. Run the script twice on the demo phone and once on the laptop fallback. Charge the phone, install the final APK, check the server.
- [ ] **25 Nov: demo script.** Install the APK from the server → log in with a temporary password → set a new password → "waiting for approval" → the admin approves it on their phone (More > Phones) → first download → search by name, EPIC and house → open a voter → airplane mode → save a survey → internet back → sync → Sync now on the admin's phone shows the change.

Not in the demo: Marathi search (the roll has no Marathi names yet). Say so before the client asks.

Decided 13 Nov: no portal at the demo. "Admin approves" is done on the admin's phone (More > Phones, 6.8), and "the change is on the server" is shown by the admin's phone after Sync now. The admin's own phone is approved once on the server with `scripts/approve_phone.py` before the demo.

## Step 7 – Field screens · 26–27 Nov · branch `step7-field`

Goal: everything a surveyor uses besides the survey. Each subtask is the endpoint, its sync part and its screen together.

- [ ] **7.13 Survey: influencer only.** Do this first, and only after the client approves the app flow (on hold, 12 Nov). The Important voter field and the positions list built in 5.14–5.16 go; Influencer = Yes shows the client's 11 entries (Sarpanch, Panch Member, Up Sarpanch, ZP Member, Ex. ZP Member, MLA, Ex. MLA, NGO, Social Worker, News Reporter, Social Media Influencer). Migration `004_client_changes_final.sql`: `positions` and `voter_surveys.position_id` are dropped, `is_important` is no longer read or written, the placeholder influencer types are replaced by the 11. API: `is_important`, `position_id`, the `positions` list and `?important=` leave the contract (they were added on 12 Nov; tell the teammate the same day); `GET /voters?influencer=true` and `?influencer_type_id=` are added. Phone: no Important switch or position picker; the Important filter becomes Influencer; local database version 3 with a real Room migration. Files: `db/migrations/004_client_changes_final.sql`, `db/seed/seed.py`, `app/routers/voters.py`, `app/sync_pull.py`, `app/schemas.py`, `tests/test_client_changes_survey.py`, `A/ui/voter/SurveyScreen.kt`, `A/ui/search/FiltersScreen.kt`, `A/data/local/`. Test: a survey with `is_important` is 422; the Influencer filter gives the same count as a direct query; a phone on database version 2 keeps its unsent surveys after the update. (26 Nov)

- [ ] **7.1 Kutumb Connect, made by hand.** Decided 12 Nov: a surveyor makes each Kutumb, types its name (usually the name of the head of the family, as plain text) and adds or removes members. Nothing is grouped by house number and there is no head field (`families.head_voter_id` stays empty; "set the head" leaves the contract). `POST /families` (free-text name, in one booth; the phone makes the UUID), `PATCH /families/{id}` (rename), `PUT /voters/{id}/family` (add to a Kutumb, take out with `leave_family`), `GET /voters/{id}/family`, `GET /booths/{id}/families`. `GET /families` stays the walk list (houses), as in the 4.10 contract. Decided 13 Nov: members are in their own table `family_members` (migration `003_kutumb_members.sql`), not in `voter_surveys.family_id`, so a membership change never raises the survey version; `PUT` puts a voter in a Kutumb of their own booth (moving them out of any other); `new_family_id` / `new_family_label` / `make_head` and `Family.head_voter_id` leave the contract (a Kutumb is made only with `POST /families`). Files: `db/migrations/003_kutumb_members.sql`, `app/routers/families.py`, `tests/test_families.py`. Test: a voter is in one Kutumb at most; a Kutumb in booth 2 is 404 for a booth 1 surveyor; a booth agent cannot make one; setting a head is 422. (26 Nov)
- [ ] **7.2 Kutumb Connect in sync.** Families (Kutumbs) and their members (`family_members` rows by `sync_xid`; a voter taken out has `family_id` null) in the pull; push types `family_new` and `family`. Files: `app/sync_pull.py`, `app/sync_push.py`, `tests/test_sync_families.py`. Test: a family made offline and pushed twice exists once. (26 Nov)
- [ ] **7.3 Visits API:** `POST /voters/{id}/visits`, visits in push. Files: `app/routers/visits.py`, `tests/test_visits.py`. Test: a visit pushed twice is stored once. (26 Nov)
- [ ] **7.4 Screens: Kutumb Connect, Walk list.** The tab and screen are called "Kutumb Connect" everywhere (client, 12 Nov). Kutumb Connect tab: make a Kutumb, name it, add members from search, take a member out. The walk list still goes house by house: it groups the booth's voters by the roll's house number on the phone and needs no Kutumb rows. Files: `A/ui/family/`, `A/ui/walklist/`. Test: marking a house "not home" offline shows on the walk list and syncs; a Kutumb made offline shows at once. (26 Nov)
- [ ] **7.5 Eligible but Not Registered** (the client's name for "new voter" and "not registered", which are one thing): `GET/POST /new-voters`, `PATCH /new-voters/{id}` with `version`, in pull and push. The paths keep their names; only the labels change. Screens: Eligible but Not Registered (the form) and its list. Files: `app/routers/new_voters.py`, `tests/test_new_voters.py`, `A/ui/newvoter/`. Test: stale version gives 409. (26 Nov)
- [ ] **7.6 Information Updation** (the client's name for the History tab): `GET /voters/{id}/history` from `audit_log`. Every update is listed (survey, notes, family, visits, voted marks, roll corrections), each with the fields that changed, the old and the new value, who and when. Screen: Information Updation tab (needs internet; says so when offline). Files: `app/routers/voters.py`, `tests/test_history.py`, `A/ui/voter/HistoryTab.kt`. Test: a survey save appears with user, time and the changed fields. (27 Nov)
- [ ] **7.7 Voter slip:** drawn on the phone as an image, with the polling date and time from the election settings, and shared to WhatsApp; `POST /voters/{id}/slip-events` through push. Files: `A/ui/slip/`, `app/routers/slips.py`, `tests/test_slips.py`. Test: sharing offline leaves one outbox item. (27 Nov)
- [ ] **7.8 Birthdays and Select many.** `GET /birthdays`; both screens read the local database; bulk colour tag goes through the outbox. Select many also offers "Share on WhatsApp" when 5 or fewer voters are ticked (7.12). Files: `app/routers/birthdays.py`, `A/ui/birthdays/`, `A/ui/search/BulkSelectScreen.kt`. Test: tagging 50 voters makes 50 outbox items and one push. (27 Nov)
- [ ] **7.9 More menu items:** Terms (`GET /terms/current`, `POST /terms/accept`; the text comes from the client, and until it arrives the screen shows a line saying so), Announcements (`GET`, `POST .../read`), Help and report a problem (`POST /problem-reports`), Update required, Change password. Files: `app/routers/misc.py`, `tests/test_misc.py`, `A/ui/more/`. Test: an app below the minimum version is sent to Update required. (27 Nov)
- [ ] **7.10 Conflict review:** `GET /sync/conflicts`, `POST /sync/conflicts/{id}/resolve` (contract in 4.10). A surveyor sees and resolves their own; supervisor and above any in their area. Keeping the phone's value writes it with a new version. Screen: conflicts on the Sync screen. Files: `app/routers/sync.py`, `tests/test_conflicts.py`. Test: keep-phone writes the value once; another surveyor's conflict is 404. (27 Nov)
- [ ] **7.11 Part notes.** One shared note per part (up to 2,000 characters) that everyone assigned to the part sees: `GET/PUT /booths/{id}/note` with `version`, in pull and push (`part_note`). Surveyor and above can write; a booth agent reads. Shown at the top of the walk list and on the Survey tab. Files: `app/routers/part_notes.py`, `tests/test_part_notes.py`, `A/ui/partnote/`. Test: a note saved offline reaches a second phone on its next sync; a stale version gives a conflict, not a lost note. (27 Nov)
- [ ] **7.12 Share on WhatsApp, at most 5 voters.** Decided 12 Nov: this is the only multi-send; there is no bulk message screen and no bulk SMS. On Kutumb Connect (the members) and on Select many, tick up to 5 voters and choose the voter slip or a message (the candidate message from the election settings, editable before sending). The phone's own WhatsApp then opens for each ticked voter who has a mobile number, one after another, with their own slip or the message; the worker presses send each time. A sixth voter cannot be ticked. A family larger than 5 is sent in two rounds. Voters without a mobile are skipped and counted. No WhatsApp API. Files: `A/ui/share/ShareWhatsAppScreen.kt`. Test: 5 ticked voters, one without a mobile, open WhatsApp 4 times with the right slips and report 1 skipped; a sixth tick is refused. (27 Nov)

Portal (teammate): Kutumb Connect view (hand-made, no head), Eligible but Not Registered list, Information Updation (voter history). No bulk message on the portal.

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
- [ ] **9.4 Settings and lists:** `GET/PUT /settings/election` (admin and super admin can both save the election and the candidate, with polling start and end time), `GET/POST/PATCH /masters/{list}` (also the influencer list), `POST /files`. Files: `app/routers/settings.py`, `app/routers/masters.py`, `app/routers/files.py`, tests for each. Test: a renamed colour tag reaches the phone on the next pull; an admin's election save works and a supervisor's gets 403. (28 Nov)
- [ ] **9.5 Team and logs:** `POST/DELETE /announcements`, `GET /problem-reports`, `GET /audit-log`, `GET /reports/worker-activity`, `GET /worker-locations`. Files: `app/routers/admin_logs.py`, `tests/test_admin_logs.py`. (29 Nov)
- [ ] **9.6 Screens: Users & devices, Add user (also Add admin), Booths & karyakartas.** The phone list with approve and block is already built (6.8, `A/ui/admin/PhonesScreen.kt`); Users & devices adds the users and links each to their phones. Files: `A/ui/admin/users/`. Test: a new user made on the phone logs in on a second phone and is approved from the first. (29 Nov)
- [ ] **9.7 Screens: Constituencies, Election & candidate (with polling time), Lists & labels (with the influencer list).** Files: `A/ui/admin/settings/`. (29 Nov)
- [ ] **9.8 Screens: Activity log, Worker activity, Worker locations.** Files: `A/ui/admin/logs/`. (29 Nov)
- [ ] **9.9 Portal files on the server.** Caddy serves the portal's static build at the domain root from `deploy/portal/` (git-ignored, copied like the APK), `index.html` as the fallback for the portal's own routes; same origin as the API, so no CORS entry. Who builds the portal and what it holds is planned later (13 Nov: the teammate may not deliver it). Files: `deploy/Caddyfile`, `deploy/docker-compose.yml`. Test: the portal login page loads from the domain; `/api/v1/health` and the APK download still work. (29 Nov)

Portal (teammate): users, assignments, phones, constituencies, election settings, lists, announcements, activity log, worker activity.

## Step 10 – Matching Engine (roll update) and data quality · 29–30 Nov · branch `step10-roll`

Goal: apply a new roll without losing survey work, and clean the list.

Client, 12 Nov: "Roll update" is called **Matching Engine** and is its own item in the More menu. Only a super admin may change official roll data. Upload, resolve, apply, discard, add, correct, remove and restore answer 403 to everyone else; an admin can still read imports and roll edits (contract in 5.15).

- [ ] **10.1 Worker.** One process that takes queued rows with `FOR UPDATE SKIP LOCKED`. Files: `app/worker.py`, `deploy/docker-compose.yml`, `tests/test_worker.py`. Test: two workers never take the same job. (29 Nov)
- [ ] **10.2 Roll upload and matching** for CSV and Excel: `POST /rolls/imports`, `GET /rolls/imports`, `GET /rolls/imports/{id}`, `.../rows`. Files: `app/routers/rolls.py`, `app/roll_match.py`, `tests/test_roll_import.py`. Test: a fake roll with one changed name, one new and one missing voter gives matched, uncertain, new and absent rows. (29 Nov, two sessions)
- [ ] **10.3 Review and apply:** `.../rows/{row_id}/resolve`, `.../apply`, `.../discard`. Test: after apply, surveys are still linked, the missing voter is "not in current roll" and nobody is marked dead. Files: same. (30 Nov)
- [ ] **10.4 One-voter corrections:** `POST /voters`, `PATCH /voters/{id}/roll`, `.../remove`, `.../restore`, `GET /voters/{id}/roll-edits`. Files: `app/routers/roll_edits.py`, `tests/test_roll_edits.py`. Test: a removed voter is hidden from search and comes back with restore; an admin's correction gets 403. (30 Nov)
- [ ] **10.5 Data quality:** `GET /data-quality/summary`, `/data-quality/duplicates`, `.../resolve`, `POST /mobile-imports`, `GET /mobile-imports/{id}`. Files: `app/routers/data_quality.py`, `tests/test_data_quality.py`. (30 Nov)
- [ ] **10.6 Screens: Data quality, Repeated voters, Matching Engine, Correct roll record, Mobile numbers & contacts.** No Spelling fixes screen (client, 12 Nov). Matching Engine is its own item in the More menu; it and Correct roll record are shown to a super admin (an admin can open Matching Engine to read, not to change). The results screen and the report download are 14.6. Files: `A/ui/quality/`, `A/ui/admin/roll/`. (30 Nov, two sessions)

Portal (teammate): Matching Engine page (roll upload, matching review; super admin only, admin reads), corrections, duplicates, mobile number sheets. No spelling fixes page.

## Step 11 – Reports and exports · 30 Nov · branch `step11-reports`

Goal: charts and printed lists; then hand over the working APK.

- [ ] **11.1 Reports:** `GET /reports/survey-progress`, `/colour-tags`, `/demographics`, `/turnout`. Files: `app/routers/reports.py`, `tests/test_reports.py`. Test: totals equal direct counts; a supervisor gets only own wards. (30 Nov)
- [ ] **11.2 Exports:** `POST /exports`, `GET /exports/{id}`, `.../download`; the worker writes Excel and PDF. Files: `app/routers/exports.py`, `app/export_jobs.py`, `tests/test_exports.py`. Test: an Excel export of a filter has the same rows as `GET /voters` with that filter. (30 Nov)
- [ ] **11.3 Screens: Reports & charts, Print or export a list.** Files: `A/ui/reports/`. (30 Nov)
- [ ] **11.4 Working APK.** Signed release build (key from 6.7) on the server through `publish_apk.py`; link sent to the client. Test: an older build shows Update required and installs the new one. (30 Nov)

Portal (teammate): reports, charts, exports. The client's eight reports at three levels are Step 14.

## Step 12 – Hardening and handover · 1–15 Dec · branch `step12-delivery`

Goal: what the SRS promises for final delivery.

- [ ] **12.2 `GET /voters/{id}/slip`** from the server, for the portal. Files: `app/routers/slips.py`. (3 Dec)
- [ ] **12.3 Fixes from client testing.** The client reports within 3 working days of 30 Nov, so by 3 Dec. One session per group of fixes. (3–10 Dec)
- [ ] **12.4 Load test: 200 users syncing at once** on the server, in a fake workspace. Files: `scripts/loadtest.py`, results in `docs/load_test.md`. Pass mark: no errors and 95% of sync calls under 3 seconds (my figure; the SRS gives none). (5–6 Dec)
- [ ] **12.5 Backups stored away from the server,** and a restore test. An office computer pulls the newest dump over SSH every night (and at next start if it was off) and keeps 14 days, and warns when the newest dump on the server is more than a day old (nothing else notices a failed backup). Bluehost has no snapshots on this plan (checked 13 Nov), so this is the only copy away from the server; until it runs, I copy a dump to the laptop by hand after 6.5 and after each day of client testing. The copy holds real voter data, so it stays in a folder only I can open. Files: `scripts/pull_backup.ps1` (or `.sh`, to match the office computer), `scripts/backup.sh`, `docs/handover.md`. Test: last night's dump, taken from the office computer, restored into a scratch database; counts match. (7 Dec)
- [ ] **12.6 Isolation check.** Every endpoint in `openapi.json` has its other-workspace and other-area test. Files: `tests/test_coverage_of_isolation.py`. (8 Dec)
- [ ] **12.7 Server check.** New secrets, CORS only for the portal domain, API docs page off or admin only (`/api/v1/docs` and `/api/v1/openapi.json` are public since 6.4), demo users switched off (`create_demo_users.py --remove`) and rehearsal surveys gone, kernel updates and reboots (unattended upgrades do not reboot by themselves), disk and log size. Files: `deploy/`. (9 Dec)
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

## Step 14 – Change requests of 12 Nov · 1–9 Dec · branch `step14-change-requests`

Goal: what the client's final list of 12 Nov adds to SRS 1.1 (`docs/change_log.md`). **Nothing here starts before the client approves the app flow** (`docs/app_flow_v2.pdf`) and the time and cost. One migration, `005_change_requests.sql`, holds every schema change of this step.

AC 2 is in Goa: two levels of local body (Village Panchayat, Zilla Panchayat) and Municipal Councils for towns; no gat, gan or Panchayat Samiti. The level between the constituency and the part is "Village Panchayat / Municipal Council".

- [ ] **14.1 Village Panchayat level.** The guessed `ward` level (one per part) becomes Village Panchayat / Municipal Council: the API keeps `ward_id` and `level: ward` (no contract break) and `GET /geo/tree` gains a `kind` on each unit (`village_panchayat` or `municipal_council`); phone and portal show "Village Panchayat". `scripts/set_village_panchayats.py` reads the client's list (part number → panchayat), makes the units, moves the parts under them with their voters, families, new voters and user assignments, and removes the guessed wards; `--dry-run` prints counts only. Supervisors are then assigned panchayats. Blocked for the real data until the client sends the list; built and tested with a fake list. Files: `db/migrations/005_change_requests.sql`, `scripts/set_village_panchayats.py`, `app/routers/geo.py`, `tests/test_village_panchayats.py`, `A/ui/` labels. Test: after the script, every part has one panchayat, voter and survey counts are unchanged, and a supervisor of panchayat A no longer sees a part moved to B on the next pull. (1 Dec)
- [ ] **14.2 Surname search.** `GET /voters?surname=` (the whole last name, any letter case); a Surname field in Filters on the phone, answered from the local database. Files: `app/routers/voters.py`, `tests/test_voters_list.py`, `A/data/local/VoterFts.kt`, `A/ui/search/FiltersScreen.kt`. Test: surname "Naik" does not return "Nayak" or a first name "Naik"; the phone's count equals a direct query. (2 Dec)
- [ ] **14.3 Report numbers.** `GET /reports/area-summary?level=ac|vp|part` (per unit: voters, male, female, third gender, surveyed, influencers, eligible but not registered) and `GET /reports/surnames?level=…` (voters per surname). Filters on both: constituency, panchayat, part, surname, gender, age range, influencer. A surveyor gets the assigned parts, a supervisor the assigned panchayats, an admin the constituency (the SRS gave reports to supervisor and above; a surveyor's own parts are added). Files: `app/routers/reports.py`, `tests/test_reports_levels.py`. Test: the three levels add up to the same total; a surveyor asking for another part gets 404; "third gender" is gender `O`. (3 Dec)
- [ ] **14.4 Report lists and downloads.** The detailed lists (voters of a surname, influencer list, eligible but not registered list) and the summaries of 14.3 as files: `POST /exports` gains the kinds `surname_list`, `surname_summary`, `area_summary`, `gender_count`, `influencer_list`, `eligible_not_registered` and the format `csv` next to `xlsx` and `pdf`. The worker writes them (11.2). A download holds voter data: it is written to the audit log, and a surveyor can download only the assigned parts. Files: `app/export_jobs.py`, `app/routers/exports.py`, `tests/test_exports_reports.py`. Test: the CSV, Excel and PDF of one report have the same rows as the screen; a download leaves an audit row. (4 Dec)
- [ ] **14.5 Screens: Reports and Report view.** Reports lists the eight reports (surname summary, surname list, AC summary, Village Panchayat summary, part summary, gender count, influencer list, eligible but not registered list). Report view shows one report with its level, its filters and a Download button (Excel, PDF, CSV). Needs internet; says so when offline. Files: `A/ui/reports/`. Test: the part summary on the phone equals the home screen counts for that part. (5 Dec)
- [ ] **14.6 Matching Engine results and report.** After a comparison: counts and lists of new, deleted and changed voters (the rows of 10.2 by status), on a results screen, and a download in the three formats (export kind `roll_match`). Survey data stays linked (10.3). Files: `app/routers/rolls.py`, `app/export_jobs.py`, `tests/test_roll_match_report.py`, `A/ui/admin/roll/MatchResultsScreen.kt`. Test: the fake roll of 10.2 gives 1 new, 1 deleted and 1 changed in the screen and in the file. (7 Dec)
- [ ] **14.7 Know My Constituency: server.** Admin and super admin only ("core staff" = super admin); everyone else gets 403. `GET /constituency/geography` (panchayats with their parts, polling station names and voter counts), `GET /constituency/demographics` (total, male, female, third gender, age bands, by panchayat and part), both worked out from the roll already in JANSETU. Previous elections: tables `past_elections` (type MP / AC / ZP, year, name) and `past_election_results` (candidate, party, votes, for the whole constituency or one panchayat or part); `GET/POST/PATCH/DELETE /constituency/elections`. The figures come from the client and are typed in or pasted from a sheet. Files: `app/routers/constituency.py`, `tests/test_constituency.py`. Test: a supervisor gets 403 on every route; the demographics total equals the voter count. (8 Dec)
- [ ] **14.8 Know My Constituency: screens.** An item in the More menu for admin and super admin only: Know My Constituency (three cards), Geography, Demographics, Previous elections (list by MP / AC / ZP, and a form to add results). Files: `A/ui/constituency/`. Test: the menu item is not shown to a supervisor; a result added on the phone shows on the portal. (9 Dec)

Portal (teammate): "Village Panchayat" in every area picker, surname filter, the eight reports with their filters and the three download formats, Matching Engine results and download, Know My Constituency (admin and super admin).

## Client changes of 12 Nov

The client sent changes twice on 12 Nov. The morning list is in SRS version 1.1, which the client approved that day. The evening list (`docs/client_changes_12nov.pdf`, 40 items) replaces it where the two differ and adds change requests. Every item, its status and its decision are in `docs/change_log.md`; this table is the short form.

| Change | Status | Tasks |
|---|---|---|
| No white colour tag; self help group with name; ration card AAY / PHH / NPHH; no two-wheeler or mandal | Built | 5.14, 5.16 |
| Influencer yes / no with the client's 11 entries; **no Important voter field, no positions list**; Influencer filter in place of Important | Replaces what 5.14–5.16 built | 7.13 |
| One shared note per part, synced | Planned | 7.11 |
| Kutumb Connect (the new name for Family): made by the surveyor by hand, free-text name, no head. Not grouped by house number (decided 12 Nov; the client's PDF says automatic, so the app flow asks them to confirm) | Planned | 7.1, 7.2, 7.4 |
| WhatsApp to at most 5 voters at a time, the phone's own WhatsApp; no bulk message screen, no bulk SMS (decided 12 Nov; less than the PDF asks) | Planned | 7.12 |
| "Voter History" is "Information Updation"; every update with what, who, when | Planned | 7.6 |
| "New voter" and "Not registered" are one thing, "Eligible but Not Registered" | Planned | 7.5 |
| Polling time on the voter slip; admin and super admin edit elections and candidates | Planned | 7.7, 9.4 |
| No Spelling fixes; only the super admin changes official roll data (403 for others) | In the contract | 5.15, Step 10 |
| "Roll update" is "Matching Engine", its own menu item | Planned | Step 10 |
| **Change request:** Village Panchayat level between constituency and part | After approval | 14.1 |
| **Change request:** surname search | After approval | 14.2 |
| **Change request:** eight reports at three levels, with filters, as Excel, PDF and CSV | After approval | 14.3–14.5 |
| **Change request:** Matching Engine results screen and report download | After approval | 14.6 |
| **Change request:** Know My Constituency (admin and super admin) | After approval | 14.7, 14.8 |

**First task (12 Nov):** the updated app flow and wireframes for the client to approve, `docs/app_flow_v2.pdf` (source in `docs/app_flow/`). Step 6 goes on meanwhile. 7.13 and Step 14 wait for the approval.

Open with the client (asked in the app flow): Kutumb Connect by hand; WhatsApp to 5 as the bulk option; the parts of each Village Panchayat; the previous election figures; "Up Sarpanch" or "Deputy Sarpanch"; time and cost of the change requests.

## The screens: 42 in SRS 1.1, 51 with the change requests

43 in the first wireframes; the client removed Spelling fixes on 12 Nov. The new names are used below. The new wireframes and the flow are in `docs/app_flow_v2.pdf`.

| Step | Screens | Count |
|---|---|---|
| 5 (demo) | Login, Set password, Device approval, First download, Home, Search, Filters, Voter profile, Voter survey, Sync & list updates | 10 |
| 7 | Kutumb Connect, Walk list, Information Updation, Voter slip, Birthdays, Eligible but Not Registered, Eligible but Not Registered list, Select many voters, More, Terms of use, Update required, Announcements, Help & support | 13 |
| 8 | Polling day, Mark voted, Mark many voted | 3 |
| 9 | Users & devices, Add user, Booths & karyakartas, Constituencies, Election & candidate, Lists & labels, Activity log, Worker activity, Worker locations | 9 |
| 10 | Data quality, Repeated voters, Matching Engine, Correct roll record, Mobile numbers & contacts | 5 |
| 11 | Reports & charts, Print or export a list | 2 |
| 7 (new, small) | Part note, Share on WhatsApp | 2 |
| 14 (change requests) | Report view, Matching results, Know My Constituency, Geography, Demographics, Previous elections, Village Panchayats | 7 |

## SRS items that are risky for the dates

1. **All 42 screens by 30 Nov.** 10 are done by the demo; the other 32, with about 75 endpoints, fall in 26–30 Nov. This is the biggest risk in the plan. If it slips, the last things in line are steps 10 and 11 on the phone, because the portal covers the same work.
2. **Marathi names and search.** The roll has English names only and the SRS excludes automatic conversion. The app will be built and tested for Marathi with fake data, but real Marathi names need a Marathi roll from the client.
3. **Server.** Running since 13 Nov at `https://myjansetu.com` (Bluehost, not the KVM 4 of the SRS, and not in India: the client was told on 13 Nov, see `docs/change_log.md`). Subtask 6.6 is still the fallback for the demo.
4. **Scanned roll PDFs (Step 13).** The election office PDFs have no text, only 115 dpi page images, so they need OCR. 99% on names is not certain at that resolution; EPIC and age are easier. Maharashtra is not being built now. The answer key was made with an AI tool, so its own errors must be told apart from OCR errors. Step 13 adds about 8 sessions in 1–9 Dec on top of Step 12; 13.7 and 13.9 slip first. 13.1 measures before anything more is promised. The SRS promises the reading and the review list, not an accuracy figure.
5. **Roll matching and review.** The SRS describes the result, not the rules for "clear" and "uncertain" matches. I will use: same EPIC = clear; same booth, serial and similar name = clear; anything else similar = uncertain.
6. **PDF lists in Marathi.** Devanagari needs a PDF tool that shapes the letters correctly; to be tried in 11.2 before promising a layout.
7. **Client feedback window.** Problems from the demo arrive up to 28 Nov, in the middle of steps 7–9.
8. **Portal.** The teammate's screens depend on my endpoints; subtask 4.10 gives the full contract by 17 Nov so the portal is not waiting for steps 9–11.
9. **"Existing data will be imported before the demo."** The client has since decided against it; the SRS line should be changed in writing.
10. **Part 4 file is a copy of part 3.** About 688 voters are missing until the client sends the right file.
11. **Content from the client.** The terms of use text and the public website pages come from the client. No website content by 1 Dec means the website pages are dropped.
12. **Client changes of 12 Nov, morning list.** Six more sessions (5.14–5.16, 7.11, 7.12, 12.11); spelling fixes and the house-number script fall away. They are in SRS version 1.1, approved by the client on 12 Nov.
13. **Client changes of 12 Nov, evening list.** One more session before 30 Nov (7.13, which also undoes part of 5.14–5.16) and eight in 1–9 Dec (Step 14). 1–15 Dec then holds Step 12 (10 tasks), Step 13 (8) and Step 14 (8), plus client fixes and training: that is more than the days allow. What slips first, in this order: 13.9, 13.7, 14.8 and 14.7 (Know My Constituency, which also waits for the client's election figures), 14.6. Tell the client when the app flow is sent: the change requests need their approval, their data (panchayat list, election figures) and an agreed date.
14. **Waiting for the app flow approval.** 7.13 and Step 14 do not start before it. If it comes after 23 Nov, the demo still shows the Important voter field the client has removed; say so at the demo.

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
| Backups "stored separately" | One server, no outside paid services. | **Decided:** a nightly pull to an office computer (12.5). Bluehost has no snapshots on this plan (checked 13 Nov). |
| Terms of use | The table is empty. | **Decided:** the text comes from the client. |
| Public website pages (portal) | No content or page list anywhere. | **Decided:** content comes from the client. None by 1 Dec = the pages are dropped. |
| Roll file format for import | The SRS names file types, not columns. | Use the columns of the 51 part files until a sample arrives. |
| 200 users at once | The schema default is 150 concurrent users; nothing enforces it. | Test at 200, as the SRS says. |

## In the screens, schema or API document but not in the SRS: not built

App labels in Marathi or Hindi (the language buttons on the Login screen), voter photos, Bluetooth slip printing, slip by SMS, saved filters, the extra filter chips (society; the influencer filter is task 7.13, client 12 Nov), matching the phone's own contacts, a separate karyakarta list for voters, comparing two days in reports. Each is a change request.

**Decided 11 Nov:** none of this is built. The Login screen has no language buttons. The client's changes of 12 Nov (`docs/change_log.md`) are the only additions. Also not built: a bulk message screen and bulk SMS (decided 12 Nov).
