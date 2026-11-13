# Android app

Code: `android/` (package `com.jansetu.app`; plan's `A/` = `android/app/src/main/java/com/jansetu/app/`). Sync rules the phone follows: `context/sync.md` ("What the phone must do").

## Commands

```
cd android
export JAVA_HOME="/c/Program Files/Android/Android Studio/jbr"   # JDK 21; the PATH JDK 24 is too new for Gradle 8.10
./gradlew assembleDebug                      # app/build/outputs/apk/debug/app-debug.apk
./gradlew testDebugUnitTest                  # JVM tests (API client against MockWebServer)
./gradlew connectedDebugAndroidTest          # device tests (database, search speed, sync) on a running emulator/phone
```

- `local.properties` (git-ignored): `sdk.dir=C\:/Users/<you>/AppData/Local/Android/Sdk` (forward slashes: `	` in a properties file is a tab). Since 6.6 a real phone does not need `jansetu.debugApiUrl` there: the debug Login screen has **Server > Change** (type e.g. `192.168.1.7:8000`; `ServerSetting`, own prefs file, survives logout; `ServerAddressInterceptor` rewrites every call). The release build ignores it and always uses `jansetu.releaseApiUrl`.
- Emulator reaches the laptop's API as `http://10.0.2.2:8000/api/v1/` (debug default). Run the API from `backend/` with the repo `.venv`: `../.venv/Scripts/python -m uvicorn app.main:app --port 8000`.
- Release build (6.7, 13 Nov): `jansetu.releaseApiUrl=https://myjansetu.com/api/v1/` in `gradle.properties`; `gradlew assembleRelease` signs it with the release key through `android/keystore.properties` (git-ignored). Key: `C:/Users/taish/jansetu-keys/jansetu-release.jks` (PKCS12, RSA 4096, alias `jansetu`, CN=JANSETU, valid 10,000 days), password in `passwords.txt` in the same folder; SHA-256 of the certificate `18:3B:BB:17:...:EC:FC:6A:0A`. Two offline copies (pen drive + password manager), never on the server or in git: a lost key means phones cannot update without uninstalling, which deletes unsent surveys. Signed with APK Signature Scheme v2 only (fine from Android 7; minSdk 26). Before each new release raise `versionCode` (and `versionName`) in `app/build.gradle.kts`.

## Layout

| Path | What |
|---|---|
| `data/local/` | Room + SQLCipher. `LocalDb` opens/wipes the file; `DbKey` = 32 random bytes wrapped by an Android Keystore AES key (`KeystoreCipher`), passed as a raw key `x'..'` (no slow KDF). `owner` / `first_sync_done` kept in prefs next to the file |
| `data/local/VoterFts.kt` | FTS4 search index, rowid = voter's rowid; `VoterQuery` builds list + count SQL for search and filters |
| `data/remote/` | Retrofit API, `ApiResult` (Ok / Err with server code+message / Offline), `TokenAuthenticator` (refresh once on 401 `token_expired`), `AuthInterceptor` (403 `device_blocked` → `SessionEvent.Blocked`) |
| `data/SessionStore.kt` | tokens encrypted with a Keystore key; session (user, workspace, device status, first sync done) as JSON |
| `data/SessionRepository.kt` | login, set password, device status, logout |
| `data/OutboxRepository.kt` | survey save = local row + outbox item in one transaction |
| `data/sync/` | `SyncRepository` (pull/push), `PullWorker` (first download), `SyncWorker` (every 15 min + Sync now), `WipeHandler` |
| `ui/admin/PhonesScreen.kt` | More > Phones (admin, super admin; 6.8): `GET /devices` by status, approve, block with reason; Waiting list refreshes every 10 s; no Block on your own phone. Needs internet |
| `ui/nav/AppRoot.kt` | screen chosen from the session: Login → Set password → Waiting for approval → First download → main (Home, Search, Sync, More) |

## Decisions

- 11 Nov: one Keystore wrapper (`KeystoreCipher`) for the DB key and the tokens; `security-crypto` not used (deprecated).
- 11 Nov: FTS4 with the `simple` tokenizer (keeps Devanagari words whole; `unicode61` may split at vowel signs). Prefix indexes 2 and 3 (a 1-letter index made loading 3x slower). Text search starts at 2 characters; a number also finds the serial (`UNION` on `serial_no`).
- 11 Nov: the list query carries the total (`count(*) OVER ()`), so search runs one query, not list + count.
- 11 Nov: pull saves each page and the cursor after it in one transaction, so a first download resumes after the app is killed. `optimize` on the FTS index after a first download.
- 11 Nov: outbox: one queued item per voter; a second save before sending replaces the unsent item's data (same id). Once sent (attempts > 0), a new edit is a new item; push sends at most one item per voter per batch and rebases the next one on the version the server returns.
- 11 Nov: a pulled survey never overwrites a local copy that is pending or in conflict. Conflict: Sync screen offers "Use server copy" or "Send mine again" (new item on top of the server version). Who resolves conflicts for real is still open with the client.
- 12 Nov: `SessionStore.signOut(notice)` writes the Login notice before clearing the session (clearing it shows Login at once; the notice was lost before).
- 11 Nov (confirmed 12 Nov: every login downloads again): logout deletes the database (next user must not see this area); warns when changes are unsent. A dead refresh token (`LoggedOut`) keeps the database: the same user logging in again keeps unsent work; a different user wipes it.
- 11 Nov: `device_uid` = `ANDROID_ID` (same across reinstalls), so a reinstalled blocked phone stays blocked.
- 13 Nov: `ANDROID_ID` depends on the app's signing key (Android 8+), so the debug app (debug key) and the release app (release key) on one handset are two phones to the server: each needs its own approval, and blocking one does not block the other. A reinstall signed with the same key keeps the same id.
- 12 Nov (5.16), 13 Nov (7.13): survey fields of the client's changes on the phone: influencer + searchable type (the client's 11), self help group + name, ration card (AAY / PHH / NPHH); Influencer filter. No Important voter field or position (removed in 7.13). A detail is kept only with its yes (`SurveyForm.applyTo`, and again in `surveyPushData`). Influencer types are `list_entries` kind `influencer_type`. The white tag is inactive on the server, so the phone no longer offers it.
- 12 Nov: local database version 2 with `fallbackToDestructiveMigrationFrom(1)` (no phone held real data on 1). From version 2 on, write real Room migrations: a destructive one would delete unsent changes.
- 13 Nov (7.13): version 3 = `AutoMigration(2, 3, Migration2To3)` in `AppDatabase.kt`: `@DeleteColumn` drops `surveys.is_important` / `position_id` (Room rebuilds the table, rows and pending flags kept); `onPostMigrate` deletes `list_entries` of kind `position` and takes the two keys out of every survey outbox item's JSON (the server now refuses them, and a refused item is dropped). Test: `MigrationTest` (`room-testing`, schemas folder added as androidTest assets); passed on the Samsung M35 (13 Nov).
- Pitfall: the first build after raising the database version writes `schemas/.../N.json` after the test assets are packed, so `MigrationTest` fails with "Cannot find the schema file"; build the androidTest APK once more.
- Every survey field the phone knows must go into `surveyPushData`: the server replaces the whole survey, so a field left out is cleared on the server.
- 11 Nov: location: plain `LocationManager`, read once at survey save (8 s, else last fix under 5 min); no Play services.

## Pitfalls

- OkHttp: the refresh call must be a blocking `execute()`; an enqueued refresh deadlocks once 5 calls to the host wait for it (test `parallelCallsShareOneRefresh`).
- FTS4 finds rows only by `rowid = ?`; `rowid IN (...)` scans the whole index (made loading quadratic).
- Emulator timings swing 10x with laptop load (RAM was down to 0.6 GB free with Docker + emulator + Gradle). Quiet run, 12 Nov, API 35 emulator, 32,000 fake voters: load 13 s; "ram pat" 4 ms, "रम पा" 3 ms, number 7 ms, "sun" + 2 filters 49 ms, "su" (8,002 hits) 98 ms. Loaded run: load 112 s, broad searches up to 1 s. Hard limit in `SearchSpeedTest`: English and Marathi prefix < 200 ms (median of 3); measure the rest on the real phone.
- On a loaded emulator, a freshly installed debug APK can fail to start in time ("Process crashed" / ANR "failed to complete startup"). Install, then `adb shell cmd package compile -m speed -f com.jansetu.app.debug` (and `.debug.test`), then `adb shell am instrument -w com.jansetu.app.debug.test/androidx.test.runner.AndroidJUnitRunner`.
- Git Bash rewrites `/sdcard/...` in adb commands: `export MSYS_NO_PATHCONV=1`.
- Expedited WorkManager jobs need a foreground notification below Android 12; not used.

## Manual check on the emulator (12 Nov, local API, workspace naik, demo.surveyor parts 1-2)

Done: wrong password shows the server message; Set password; Waiting screen moves on by itself after the admin approves; first download 872 voters (= server count); Home counts and Search work in airplane mode; survey saved offline with location ("Not sent yet" 1); on reconnect the push applied (server version 1, mobile, location, colour tag) and the pull brought it back; block → Sync now → database files gone, Login shows the blocked notice.

- Afterwards: delete the test survey from the dev database (`notes = 'app_test_note'` and its `sync_mutations` row) and run `scripts/create_demo_users.py --reset`.
- A surveyor's phone has only its booths (no ward row), so the Ward line and the Ward filter are empty for a surveyor.
- Driving the emulator with adb: Gboard opens a stylus tutorial on the first text field (`adb shell settings put secure stylus_handwriting_enabled 0`); an open keyboard moves buttons, so close it (`input keyevent 4`) and read bounds from `uiautomator dump`. `demo_users.txt` gets a new block on every `--reset`: take the last line per user. Quote passwords for the device shell (`adb shell "input text '...'"`) and never put them where an error can echo them.
- No screenshots of voter screens (they show real names); use filtered UI dumps.

## Laptop fallback (6.6, 13 Nov)

- Laptop: `powershell -ExecutionPolicy Bypass -File scriptsallback.ps1 [-ResetDemoUsers]` (dev database + API on 0.0.0.0:8000, prints the addresses; warns when Windows calls the network Public, which blocks the phones). Phone: debug build, Login > Server > Change.
- Checked 13 Nov on both phones over the laptop's Wi-Fi with the address typed: admin login + `approve_phone.py`, first download 31,871 in 51 s; surveyor approved from the admin's Phones screen, moved on in 16 s, 872 voters; search answers offline; survey saved with the laptop API stopped (Not sent yet 1), sent after the API came back; admin's Sync now: Surveyed 4 → 5. The hotspot itself (laptop Mobile hotspot = `192.168.137.1`) is the same path with another address; try it once before the demo.
- The fallback uses the laptop's data and passwords (`jansetu-private/demo_users.txt`), not the server's; nothing done on it reaches the server.
- Never print UI dumps of voter screens: filter dumps to an allow-list of labels and counts (13 Nov: a loose filter showed names in the session log).

## Real phones (12 Nov) on the laptop's Wi-Fi: vivo I2207 (Android 15, demo.surveyor), Samsung M35 (Android 16, demo.supervisor, wireless debugging)

- The API must be running with `--host 0.0.0.0` before logging in; when nothing listens on port 8000 the login just waits until it times out. Check from the phone's browser: `http://<laptop IP>:8000/api/v1/health`.
- Checked by hand: login, approval, first download, search, voter details, Call / WhatsApp / SMS, the new survey fields. Rehearsal (5.13): survey saved on the vivo in airplane mode, sent on reconnect, then seen on the Samsung after Sync now (Surveyed 1 → 2).
- Fixed after the check: the three contact buttons now share the row equally (SMS was squeezed); Filters is no longer a full-screen `Dialog` but a screen shown in place of the search list (Back closes it). On Android 15-16 the full-screen dialog window was as tall as the screen but started below the status bar, so it spilled under the navigation bar and reported zero insets; neither `safeDrawing` padding nor `decorFitsSystemWindows = false` helped. Do not use full-screen dialogs; use a screen or a route.
- Wireless debugging: `adb mdns services` finds nothing on this laptop, so the phone's connect port must be read off its screen. If the pairing popup hides it, scan for it (one open port in the range shown, e.g. 41000-41999, with a Python socket loop) and `adb connect`. 13 Nov: Samsung M35 `192.168.1.3`, vivo `192.168.1.8` (ports change each time wireless debugging is switched on).
- Clean start on a phone for a check: `adb shell pm clear com.jansetu.app.debug` (deletes the app's local database and login; dev only).
- Phones check (6.8, 13 Nov): Samsung as demo.admin (approved with `approve_phone.py`, first download 31,871), vivo as demo.surveyor waiting; approved from the Samsung's Phones screen, the vivo moved on within 5 s and downloaded 872. New passwords set on the phones are in `jansetu-private/demo_phone_passwords.txt`.
- Wireless debugging (no cable): phone Developer options → Wireless debugging → Pair with code; `adb pair <ip>:<pairing port> <code>` then `adb connect <ip>:<port on the main screen>`. Each code has its own pairing port. Turning on airplane mode cuts the adb link.
- Approving a phone without the portal: log in as `demo.admin` through the API, `GET /devices?status=pending`, `POST /devices/{id}/approve`. A fresh `--reset` admin must set its own password first (`password_change_required`).

## Not done yet


- Android 8 check: skipped for now (12 Nov), moved to task 12.11.
- Client changes of 12 Nov still to come on the phone (`docs/change_log.md`): 7.4 (Kutumb Connect by hand, no head), 7.11 (part notes), 7.12 (WhatsApp to at most 5 voters), new names (Information Updation, Eligible but Not Registered, Matching Engine), Step 14 screens.
- Release minify (R8) is off; turn on with keep rules before the final APK if size matters.
