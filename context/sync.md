# Sync

Design: `docs/02_tech_stack_and_api.md` ("Offline sync"). Server code: `backend/app/sync_pull.py`, `backend/app/routers/sync.py`. Phone side: not built yet (step 5).

## Watermark

- `app.sync_watermark()` = xmin of the current snapshot (xid8): every transaction below it has finished. Triggers stamp `sync_xid = pg_current_xact_id()` on every insert/update of synced tables.
- A delta pull `since=W` returns rows with `sync_xid >= W`. Rows may come twice; the phone replaces by id, so that is fine. Never use `>`: a transaction in flight at W has xid >= W.
- Sent as **text** (a whole number), never a JSON number: xid8 is 64-bit.

## First download (`GET /sync/pull` without `since`) – built 4.6

- Page 1: `settings`, `lists` (castes, professions, colour tags, custom field labels, inactive included), `areas` (the user's scope, flat, active only), `total_voters`, `total_surveys`, and W taken now.
- Then voters (keyset on `v.id`), then surveys (keyset on `voter_id`), `limit` 1–2000 (default 1000) rows per page. Removed voters and their surveys are not sent.
- Cursor = `[phase, last_id, W]` (`app/paging.py`). W is taken once on page 1 and repeated on every page: later pages see everything committed since, and anything changed during the download has `sync_xid >= W`, so the first delta pull catches it (test: `test_change_during_download_is_at_or_after_the_watermark`).
- Each page is its own request and transaction; the scope is recomputed per page.
- Every role may pull (ReadyUser), scope from `app/scope.py` (switched-off areas excluded).
- The phone: replace rows by id; when `next_cursor` is null, store `watermark`. To resume after the app was closed, re-send the last cursor (5.6).

Real roll (11 Nov): admin, whole AC: 31,871 voters, 34 pages of 1000, 1.3 s server time, slowest page 66 ms, **24.9 MB JSON uncompressed**; one ward: 685 voters, 0.6 MB.

## Not built yet

- 4.7 delta pull `since=W`: changed rows, removed voters (`deleted_at` set), current assigned area ids (phone drops the rest), wipe signal. A blocked phone gets 403 `device_blocked` from ReadyUser today: 4.7 must let the pull answer `wipe` instead.
- 4.8 push.
- `devices.last_pull_watermark` is not updated: the `devices` table has an audit trigger, so writing it on every pull would add an audit row per phone per sync. Decide in 4.7.

## Pitfalls

- **Compression:** the API sends plain JSON. Turn on gzip/zstd in Caddy (`encode zstd gzip`, step 6.1), and for the laptop fallback (6.6) consider FastAPI's `GZipMiddleware`.
- Areas list holds only the scope's areas (no parent above a supervisor's ward), the same as `/geo/tree`.
