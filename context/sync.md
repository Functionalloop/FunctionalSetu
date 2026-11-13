# Sync

Design: `docs/02_tech_stack_and_api.md` ("Offline sync"). Server code: `backend/app/sync_pull.py`, `backend/app/sync_push.py`, `backend/app/routers/sync.py`. Phone side: `android/.../data/sync/` (see `context/android.md`).

## Watermark

- `app.sync_watermark()` = xmin of the current snapshot (xid8): every transaction below it has finished. Triggers stamp `sync_xid = pg_current_xact_id()` on every insert/update of synced tables.
- A delta pull `since=W` returns rows with `sync_xid >= W`. Never use `>`: a transaction in flight at W has xid >= W. Rows may come twice; the phone replaces by id.
- Watermarks are transaction numbers of one PostgreSQL server. Restoring a backup onto a **new** server needs `scripts/restore.sh --live`, which moves the new server's counter past the backup's (see `context/deploy.md`, Backups); a plain `pg_restore` there would leave phones never pulling new changes.
- Sent as **text** (a whole number), never a JSON number: xid8 is 64-bit. `since` must match `^[0-9]{1,20}$` (else 422).

## `GET /sync/pull` (built 4.6 + 4.7)

One endpoint, two modes: no `since` = first download; `since=W` = delta pull.

- **Page 1:** new watermark W', `settings`, `lists` (castes, professions, colour tags, custom field labels; inactive included), `areas`, `area_ids`, `total_voters`, `total_surveys`. On a delta: `settings` only if changed (else null), `lists` and `areas` only entries changed since W, but `area_ids` is always the **full current** list.
- **Then phases**, keyset-paged by id, `limit` 1–2000 (default 1000):
  - `voters`: first download = every voter in the area, removed ones left out; delta = voters in the area with `sync_xid >= W`, removed ones **included** (`deleted_at` set).
  - `surveys`: surveys of non-removed voters in the area (delta: `sync_xid >= W`).
  - `families` (7.2): Kutumbs whose **booth** is in the scope (first: not deleted; delta: changed, deleted ones included with `deleted_at`). No member list on the row.
  - `new_voters` (7.5): Eligible but Not Registered whose part (or Village Panchayat when no part) is in the scope; **survey roles only** (a booth agent's pull has none: `pull_page(..., survey_role=)`). First: not deleted; delta: changed since W. Replace by id.
  - `visits` (7.3): visits whose booth is in the scope (first: all; delta: new since W). Not deleted ones only (there is no delete).
  - `members` (7.2): `family_members` rows (`voter_id`, `family_id`, `updated_at`) of non-removed voters in the area. First: only voters in a Kutumb; delta: changed rows, `family_id` null = taken out. Replace by `voter_id`.
  - `turnout` (8.1): `voter_turnout` rows (`TurnoutMark`: voter_id, is_voted, marked_by, marked_at, source) of non-removed voters in the area; **polling roles only** (a surveyor's pull has none: `pull_page(..., polling_role=)`). First: voted ones; delta: changed since W, `is_voted` false = undone. Replace by `voter_id`.
  - `gone` (delta only): ids of voters changed since W that are now **outside** the area (moved booth, area switched off for them). Ids only, never the row.
- Only phases with rows are visited: page 1 counts them and the cursor carries the list. Idle delta = 1 request; a few changes = page 1 + one page per phase with rows.
- Cursor = `[phases_left, last_id, W', since]` (`app/paging.py`); `since` rides in the cursor, so a `since` sent with a cursor is ignored.
- W' is taken once on page 1. Later pages are later transactions; anything written after page 1 has `sync_xid >= W'` and comes again next pull (test: `test_change_during_download_is_at_or_after_the_watermark`).
- Scope is recomputed per page (`app/scope.py`; switched-off areas excluded).
- **Blocked or wiped phone:** 200 with `wipe: true` and nothing else (other data endpoints give it 403 `device_blocked`). Pending phone / password not changed: 403 as usual. The route uses `CurrentUser` and applies the ready checks itself.

## `POST /sync/push` (built 4.8)

- Body `{"items": [...]}`, max 500, applied in order. Item: `id` (phone-made, the same on every retry), `type` (`survey`, `family_new`, `family`, `visit`, `new_voter`, `new_voter_update`, `slip_event`, `part_note`, `voted`, `unvoted`; an unknown one `not_implemented`), `entity_id` (voter id; `family_new`: the Kutumb id), `base_version` (0 = no survey yet), `changed_at`, `data` = the `PUT /voters/{id}/survey` body without `version` (a `version` inside `data` is ignored).
- Result per item, same order: `applied` (`survey` = saved copy with the new version), `conflict` (`survey` = server copy, `conflict_fields`), `rejected` (`error.code`: `forbidden_role`, `validation_error`, `not_found`, ...). `duplicate: true` = this id was seen before; the stored status is returned and nothing is applied again.
- **One bad item never fails the batch** (the outbox would stick): `data` is validated per item. Only a broken envelope (bad `id`, unknown `type`, > 500 items) is a 422 for the whole request.
- Retry safety, two layers: (1) look up `sync_mutations (device_id, client_mutation_id)` first; (2) each item runs in a SAVEPOINT and records its result with `INSERT ... ON CONFLICT DO NOTHING` at the end; if a parallel request recorded the id first, the savepoint is rolled back and the stored result returned. Test `test_parallel_retries_apply_once` fails without layer 2.
- Conflict: nothing written to the survey; one `sync_conflicts` row per differing field (`client_value` / `server_value` jsonb, `status = open`). If the phone's data equals the server copy, it is `applied` with no conflict rows. Review (7.10): `GET /sync/conflicts` and `POST /sync/conflicts/{id}/resolve` (see `context/backend.md`); the phone decides its own conflicts there, supervisors and above also those of their team.
- Needs a phone: a login without a device gets 403 `device_required` (the retry key is per device). Roles are checked per item (`SURVEY_ROLES` for surveys): a booth agent's survey item is `rejected`, not a 403 for the batch.
- Uses the same `write_survey` as `PUT /voters/{id}/survey`, so both follow one set of rules.

### Eligible but Not Registered items (7.5)

- `new_voter`: `entity_id` = the record's id, `data` = `POST /new-voters` body (`id` may be left out), `base_version` 0. A repeat id returns the stored record (first copy kept).
- `new_voter_update`: `entity_id` = the record's id, `data` = `PATCH /new-voters/{id}` body without `version`, `base_version` = the version the phone last had (1 or more; 0 is rejected). Stale: `conflict` with `new_voter` = the server copy and `conflict_fields`; one `sync_conflicts` row per field (`entity_type` `new_voter`). Stale but equal to the server: `applied`. Result `new_voter` = the saved copy.
- Push the `new_voter` before its `new_voter_update` items (an update of a record the server does not have is `rejected` `not_found`).

### Slip events (7.7)

- `part_note` (7.11): `entity_id` = the booth, `data` = `{note}`, `base_version` = the note's version (0 = none yet), survey roles. Stale and different: `conflict` with `part_note` = the server copy and `conflict_fields` `["note"]`, **no `sync_conflicts` row** (that table takes surveys, new voters and Kutumbs only), so the phone decides it alone (keep mine = send again on the server's version). Stale but the same text: `applied`. Pull: phase `part_notes` (all roles, notes of the booths in the area; first: all; delta: changed), `SyncPage.part_notes`, replace by `booth_id`.
- `slip_event`: `entity_id` = the voter, `data` = `POST /voters/{id}/slip-events` body (`{id, channel, at}`), `base_version` 0, **all roles** (booth agents too). The event id makes it safe to resend under a new outbox id. Result: no record (`applied` only). `at` later than the server clock is stored as now.

### Voted marks (8.1)

- `voted`: `entity_id` = the mark request's id, `data` = `POST /turnout/marks` body (`id` may be left out; if given it must equal `entity_id`), `base_version` 0, polling roles (a surveyor's item is `rejected` `forbidden_role`). One item may mark many voters (by ids or booth + serials); one voter outside the area rejects the whole item (`not_found`). The mark id makes it safe to resend under a new outbox id: voters it marked are never marked again, even after an undo.
- `unvoted`: `entity_id` = the voter, `data` = `{}`, `base_version` 0, polling roles.
- Result `turnout` = the current marks of the item's voters (also on a `duplicate`), replace by `voter_id`. A voter someone else marked first comes back with their `marked_by`.
- No conflicts: a voter is voted or not; the last change wins (mark after undo, undo after mark).

### Visit items (7.3)

- `visit`: `entity_id` = the voter, `data` = `POST /voters/{id}/visits` body with the visit's own `id`. The visit id makes it safe to resend under a new outbox id. Result `visit` = the stored visit. A walk-list house mark is a visit on any voter of that house.

### Kutumb items (7.2)

- `family_new`: `data` = `POST /families` body (`id` may be left out; it must equal `entity_id`). `family`: `data` = `PUT /voters/{id}/family` body. `base_version` 0 for both. Same code as the REST routes (`write_new_family`, `write_voter_family`).
- No version and no conflicts: a Kutumb id sent again (even under a new outbox id) returns the stored Kutumb, first name kept; membership is last change wins. Push the `family_new` before the `family` items that use it (one batch is fine: items apply in order); a `family` for a Kutumb the server does not have is `rejected` `not_found`.
- Results carry `family` (`family_new`) or `family_member` (`family`; null when the voter was never in a Kutumb). `sync_mutations.entity_type` = `family` / `family_member`; `operation` `delete` for `leave_family`.

## What the phone must do (step 5)

1. `wipe: true` from the pull, **or** 403 `device_blocked` from any call (refresh and login also give it once the 15-min token is gone): delete the database and go to Login.
2. Save every row of every page (replace by id). A voter with `deleted_at` set: delete it. `gone_voter_ids`: delete those voters and their surveys.
3. `area_ids` (page 1): delete local areas not in it and their voters. If it holds an id the phone does not have (a new assignment), run a **first download** again after this pull (no wipe; rows are replaced). Delta rows cannot bring a new area: its voters have old `sync_xid`.
4. When `next_cursor` is null, store `watermark`; send it as `since` next time. If the app stops mid-pull, re-send the last cursor (5.6) or start the pull again from the stored W (safe: rows replace).
5. Push before pull. Keep each outbox item (with its `id`) until a result arrives: `applied` → update the local version from `survey`; `conflict` → keep the local copy marked as a conflict and show it (the pull brings the server copy); the worker decides it on the server (7.10): the phone lists the record's open rows from its own pushes, resolves them all `kept_client` or `kept_server` (a 422 is tried again after the others; 409 `conflict_resolved` is fine), then drops the item; keep = clear the flags so the next pull brings the new copy; none open any more = the server's copy; `rejected` → drop it and show the error. A network failure → send the same items with the same ids again.

## Real roll (11 Nov, dev DB, server time only)

- First download, admin, whole AC: 31,871 voters, 34 pages of 1000, 1.3 s, slowest page 66 ms, **24.9 MB JSON uncompressed**. One ward: 685 voters, 0.6 MB.
- Push: 500 survey items 3.3 s (6.6 ms/item); the same 500 again as retries 0.8 s, nothing written.
- Voted marks (14 Nov): one `voted` item for a whole part (~600 voters) ~120 ms (one SQL insert; an audit row per voter). Marking all 31,424 voters on the current roll as 50 requests: 6 s. Delta pull of 31,424 marks: 33 pages, 0.45 s.
- Delta: nothing changed 1 page / 0.02 s; 100 voters changed 2 pages / 0.02 s; `since=1` (everything, like after a roll import) 31,871 voters in 33 pages / ~1 s.

## Not built yet / open

- Phone side (7.4, local database version 4): `families`, `family_members` and `visits` are stored in Room; Kutumbs and visits of booths that leave `area_ids` are dropped with their voters. App 0.1.0 ignores the three lists; the update to version 4 starts a full download so nothing made earlier is missed. Details: `context/android.md`.
- Phone side (7.11, local database version 6): `part_notes` stored in Room; a pulled note never overwrites one pending or in conflict; the update to version 6 starts a full download.
- Phone side (7.7): `slip_event` items need no table on the phone; two shares of one voter's slip are two items (two events).
- Phone side (7.5, local database version 5): `new_voters` stored in Room (survey roles); `new_voter` before `new_voter_update` in outbox order; the update to version 5 starts a full download.

- `devices.last_pull_watermark` is not written: `devices` has an audit trigger, so a write per pull = an audit row per phone per sync. Decide when the admin needs "last synced" (maybe from `auth_sessions.last_seen_at`).
- Nothing records that a blocked phone finished wiping (plan gap table: phone reports it on `/devices/me`; not decided).

## Pitfalls

- **Compression:** the API sends plain JSON. Turn on gzip/zstd in Caddy (`encode zstd gzip`, step 6.1); for the laptop fallback (6.6) consider FastAPI's `GZipMiddleware`.
- Areas hold only the scope's areas (no parent above a supervisor's ward), the same as `/geo/tree`.
- A test that a second delta returns *nothing* can flake if another transaction in the cluster holds back xmin; assert "the change comes back" and "old rows below W", not "nothing at all", except where nothing at all changed since the same pull.
