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

- `local.properties` (git-ignored): `sdk.dir=C\:/Users/<you>/AppData/Local/Android/Sdk` (forward slashes: `\t` in a properties file is a tab), and for a real phone on Wi-Fi `jansetu.debugApiUrl=http://<laptop LAN IP>:8000/api/v1/` (then run uvicorn with `--host 0.0.0.0`).
- Emulator reaches the laptop's API as `http://10.0.2.2:8000/api/v1/` (debug default). Run the API from `backend/` with the repo `.venv`: `../.venv/Scripts/python -m uvicorn app.main:app --port 8000`.
- Release build: `jansetu.releaseApiUrl` in `gradle.properties` is a placeholder until the domain exists (step 6). Signing: copy `keystore.properties.example` to `keystore.properties` (git-ignored), keep the `.jks` outside the repo. Without it the release APK is unsigned. The real release key is made in 6.7 (plan); keep its offline copies, a lost key blocks updates.

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
- 12 Nov (5.16): survey fields of the client's changes on the phone: important + searchable position, influencer + type, self help group + name, ration card (AAY / PHH / NPHH); Important filter. A detail is kept only with its yes (`SurveyForm.applyTo`, and again in `surveyPushData`). Positions and influencer types are `list_entries` kinds `position` / `influencer_type`. The white tag is inactive on the server, so the phone no longer offers it.
- 12 Nov: local database version 2 with `fallbackToDestructiveMigrationFrom(1)` (no phone held real data on 1). From version 2 on, write real Room migrations: a destructive one would delete unsent changes.
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

## Real phones (12 Nov) on the laptop's Wi-Fi: vivo I2207 (Android 15, demo.surveyor), Samsung M35 (Android 16, demo.supervisor, wireless debugging)

- The API must be running with `--host 0.0.0.0` before logging in; when nothing listens on port 8000 the login just waits until it times out. Check from the phone's browser: `http://<laptop IP>:8000/api/v1/health`.
- Checked by hand: login, approval, first download, search, voter details, Call / WhatsApp / SMS, the new survey fields. Rehearsal (5.13): survey saved on the vivo in airplane mode, sent on reconnect, then seen on the Samsung after Sync now (Surveyed 1 → 2).
- Fixed after the check: the three contact buttons now share the row equally (SMS was squeezed); Filters is no longer a full-screen `Dialog` but a screen shown in place of the search list (Back closes it). On Android 15-16 the full-screen dialog window was as tall as the screen but started below the status bar, so it spilled under the navigation bar and reported zero insets; neither `safeDrawing` padding nor `decorFitsSystemWindows = false` helped. Do not use full-screen dialogs; use a screen or a route.
- Wireless debugging (no cable): phone Developer options → Wireless debugging → Pair with code; `adb pair <ip>:<pairing port> <code>` then `adb connect <ip>:<port on the main screen>`. Each code has its own pairing port. Turning on airplane mode cuts the adb link.
- Approving a phone without the portal: log in as `demo.admin` through the API, `GET /devices?status=pending`, `POST /devices/{id}/approve`. A fresh `--reset` admin must set its own password first (`password_change_required`).

## Not done yet


- Android 8 check: skipped for now (12 Nov), moved to task 12.11.
- Client changes of 12 Nov still to come on the phone (`docs/change_log.md`): 7.13 (Important voter and positions come out again; Influencer filter; local database version 3 with a real migration; on hold until the client approves `docs/app_flow_v2.pdf`), 7.4 (Kutumb Connect by hand, no head), 7.11 (part notes), 7.12 (WhatsApp to at most 5 voters), new names (Information Updation, Eligible but Not Registered, Matching Engine), Step 14 screens.
- Release minify (R8) is off; turn on with keep rules before the final APK if size matters.
