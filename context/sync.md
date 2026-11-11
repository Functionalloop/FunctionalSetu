# Sync

Design: `docs/02_tech_stack_and_api.md` ("Offline sync"). Server code: `backend/app/sync_pull.py`, `backend/app/routers/sync.py`. Phone side: not built yet (step 5).

## Watermark

- `app.sync_watermark()` = xmin of the current snapshot (xid8): every transaction below it has finished. Triggers stamp `sync_xid = pg_current_xact_id()` on every insert/update of synced tables.
- A delta pull `since=W` returns rows with `sync_xid >= W`. Never use `>`: a transaction in flight at W has xid >= W. Rows may come twice; the phone replaces by id.
- Sent as **text** (a whole number), never a JSON number: xid8 is 64-bit. `since` must match `^[0-9]{1,20}$` (else 422).

## `GET /sync/pull` (built 4.6 + 4.7)

One endpoint, two modes: no `since` = first download; `since=W` = delta pull.

- **Page 1:** new watermark W', `settings`, `lists` (castes, professions, colour tags, custom field labels; inactive included), `areas`, `area_ids`, `total_voters`, `total_surveys`. On a delta: `settings` only if changed (else null), `lists` and `areas` only entries changed since W, but `area_ids` is always the **full current** list.
- **Then phases**, keyset-paged by id, `limit` 1–2000 (default 1000):
  - `voters`: first download = every voter in the area, removed ones left out; delta = voters in the area with `sync_xid >= W`, removed ones **included** (`deleted_at` set).
  - `surveys`: surveys of non-removed voters in the area (delta: `sync_xid >= W`).
  - `gone` (delta only): ids of voters changed since W that are now **outside** the area (moved booth, area switched off for them). Ids only, never the row.
- Only phases with rows are visited: page 1 counts them and the cursor carries the list. Idle delta = 1 request; a few changes = page 1 + one page per phase with rows.
- Cursor = `[phases_left, last_id, W', since]` (`app/paging.py`); `since` rides in the cursor, so a `since` sent with a cursor is ignored.
- W' is taken once on page 1. Later pages are later transactions; anything written after page 1 has `sync_xid >= W'` and comes again next pull (test: `test_change_during_download_is_at_or_after_the_watermark`).
- Scope is recomputed per page (`app/scope.py`; switched-off areas excluded).
- **Blocked or wiped phone:** 200 with `wipe: true` and nothing else (other data endpoints give it 403 `device_blocked`). Pending phone / password not changed: 403 as usual. The route uses `CurrentUser` and applies the ready checks itself.

## What the phone must do (step 5)

1. `wipe: true` from the pull, **or** 403 `device_blocked` from any call (refresh and login also give it once the 15-min token is gone): delete the database and go to Login.
2. Save every row of every page (replace by id). A voter with `deleted_at` set: delete it. `gone_voter_ids`: delete those voters and their surveys.
3. `area_ids` (page 1): delete local areas not in it and their voters. If it holds an id the phone does not have (a new assignment), run a **first download** again after this pull (no wipe; rows are replaced). Delta rows cannot bring a new area: its voters have old `sync_xid`.
4. When `next_cursor` is null, store `watermark`; send it as `since` next time. If the app stops mid-pull, re-send the last cursor (5.6) or start the pull again from the stored W (safe: rows replace).

## Real roll (11 Nov, dev DB, server time only)

- First download, admin, whole AC: 31,871 voters, 34 pages of 1000, 1.3 s, slowest page 66 ms, **24.9 MB JSON uncompressed**. One ward: 685 voters, 0.6 MB.
- Delta: nothing changed 1 page / 0.02 s; 100 voters changed 2 pages / 0.02 s; `since=1` (everything, like after a roll import) 31,871 voters in 33 pages / ~1 s.

## Not built yet / open

- 4.8 push.
- `devices.last_pull_watermark` is not written: `devices` has an audit trigger, so a write per pull = an audit row per phone per sync. Decide when the admin needs "last synced" (maybe from `auth_sessions.last_seen_at`).
- Nothing records that a blocked phone finished wiping (plan gap table: phone reports it on `/devices/me`; not decided).

## Pitfalls

- **Compression:** the API sends plain JSON. Turn on gzip/zstd in Caddy (`encode zstd gzip`, step 6.1); for the laptop fallback (6.6) consider FastAPI's `GZipMiddleware`.
- Areas hold only the scope's areas (no parent above a supervisor's ward), the same as `/geo/tree`.
- A test that a second delta returns *nothing* can flake if another transaction in the cluster holds back xmin; assert "the change comes back" and "old rows below W", not "nothing at all", except where nothing at all changed since the same pull.
