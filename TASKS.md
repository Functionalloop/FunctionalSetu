# JANSETU – implementation tracker

Generated from `docs/plan.md` by `scripts/tasks.py`. Full task text, files and tests are in the plan.
Tick with `python scripts/tasks.py done 4.1` (or tick a box here and run `python scripts/tasks.py sync`).

**Overall: 42 / 99 done (42%)** `████████░░░░░░░░░░░░`

| Section | Done | Progress |
|---|---|---|
| Step 4 – Demo API | 12 / 12 | `██████████` |
| Step 5 – Android demo app | 16 / 16 | `██████████` |
| Step 6 – Server | 8 / 8 | `██████████` |
| Demo | 0 / 2 | `░░░░░░░░░░` |
| Step 7 – Field screens | 6 / 13 | `█████░░░░░` |
| Step 8 – Polling day | 0 / 3 | `░░░░░░░░░░` |
| Step 9 – Admin | 0 / 9 | `░░░░░░░░░░` |
| Step 10 – Matching Engine (roll update) and data quality | 0 / 6 | `░░░░░░░░░░` |
| Step 11 – Reports and exports | 0 / 4 | `░░░░░░░░░░` |
| Step 12 – Hardening and handover | 0 / 10 | `░░░░░░░░░░` |
| Step 13 – Scanned roll PDFs (OCR) | 0 / 8 | `░░░░░░░░░░` |
| Step 14 – Change requests of 12 Nov | 0 / 8 | `░░░░░░░░░░` |

## Step 4 – Demo API · 12–17 Nov · branch `step4-demo-api` — 12/12

- [x] **4.0** Merge step 3 into `main` · due 12 Nov · done 2026-11-11 · `baae929`
- [x] **4.1** Area scope helper · due 12 Nov · done 2026-11-11 · `ae6f6b8`
- [x] **4.2** `GET /geo/tree` · due 12 Nov · done 2026-11-11 · `b298568`
- [x] **4.3** `GET /voters` · due 13 Nov · done 2026-11-11 · `b8b95de`
- [x] **4.11** Generic endpoint checks · due 11 Nov · done 2026-11-11 · `db508b2`
- [x] **4.4** `GET /voters/{id}` and `PUT /voters/{id}/survey` · due 13 Nov · done 2026-11-11 · `ad838da`
- [x] **4.5** `GET /devices` · due 13 Nov · done 2026-11-11 · `fa5f825`
- [x] **4.6** `GET /sync/pull`, first download · due 14 Nov · done 2026-11-11 · `76e32db`
- [x] **4.7** `GET /sync/pull?since=W` · due 14 Nov · done 2026-11-11 · `e3cabf4`
- [x] **4.8** `POST /sync/push` · due 15 Nov · done 2026-11-11 · `54ca991`
- [x] **4.9** Demo users · due 15 Nov · done 2026-11-11 · `40ff705`
- [x] **4.10** Contract for the remaining endpoints · due 16–17 Nov, two sessions · done 2026-11-11 · `9f7ab97`

## Step 5 – Android demo app · 14–23 Nov · branch `step5-android-demo` — 16/16

- [x] **5.1** Project · due 14 Nov · done 2026-11-12 · `9ee861d`
- [x] **5.2** Local database · due 15 Nov · done 2026-11-12 · `1f62e80`
- [x] **5.3** Search · due 16 Nov · done 2026-11-12 · `8e5bfe2`
- [x] **5.4** API client · due 17 Nov · done 2026-11-12 · `1230213`
- [x] **5.5** Login, Set password, Device approval · due 17–18 Nov · done 2026-11-12 · `4b239c2`
- [x] **5.6** First download · due 18–19 Nov · done 2026-11-12 · `4b239c2`
- [x] **5.7** Home, bottom bar, More menu shell · due 19 Nov · done 2026-11-12 · `4b239c2`
- [x] **5.8** Filters · due 20 Nov · done 2026-11-12 · `7e617df`
- [x] **5.9** Voter profile, Details tab, · due 20 Nov · done 2026-11-12 · `1a240e6`
- [x] **5.10** Survey tab · due 21 Nov · done 2026-11-12 · `4b239c2`
- [x] **5.11** Push, delta pull and the Sync screen · due 21–22 Nov · done 2026-11-12 · `4b239c2`
- [x] **5.12** Blocked phone and logout · due 22 Nov · done 2026-11-12 · `7e617df`
- [x] **5.14** Client changes: database and survey API · due 13 Nov · done 2026-11-12 · `ef6772d`
- [x] **5.15** Client changes: contract · due 13 Nov · done 2026-11-12 · `d06dc16`
- [x] **5.16** Client changes: Survey screen and Important filter · due 14 Nov · done 2026-11-12 · `6ad84a7`
- [x] **5.13** Rehearsal on a real phone · due 23 Nov · done 2026-11-12 · `9e08481`

## Step 6 – Server · 19–23 Nov · branch `step6-server` — 8/8

- [x] **6.1** Production containers, · due 19 Nov · done 2026-11-13 · `18dba3c`
- [x] **6.2** Nightly backup · due 19 Nov · done 2026-11-13 · `591247d`
- [x] **6.3** APK download and `GET /app/version` · due 20 Nov · done 2026-11-13 · `1e0d9c8`
- [x] **6.4** Server setup · due 20–21 Nov · done 2026-11-13 · `fc71f2f`
- [x] **6.5** Data on the server · due 21 Nov · done 2026-11-13 · `3eacb72`
- [x] **6.6** Laptop fallback · due 22 Nov · done 2026-11-13 · `39cb65b`
- [x] **6.7** Release keystore and first published APK · due 23 Nov · done 2026-11-13 · `adfbe9e`
- [x] **6.8** Phones screen in the app · due 13 Nov · done 2026-11-13 · `c171e7c`

## Demo · 24–25 Nov — 0/2

- [ ] **D.1** 24 Nov: freeze
- [ ] **D.2** 25 Nov: demo script

## Step 7 – Field screens · 26–27 Nov · branch `step7-field` — 6/13

- [x] **7.13** Survey: influencer only · due 26 Nov · done 2026-11-13 · `18f27b7`
- [x] **7.1** Kutumb Connect, made by hand · due 26 Nov · done 2026-11-13 · `3c731ec`
- [x] **7.2** Kutumb Connect in sync · due 26 Nov · done 2026-11-13 · `06ecb0b`
- [x] **7.3** Visits API · due 26 Nov · done 2026-11-13 · `5e65a64`
- [x] **7.4** Screens: Kutumb Connect, Walk list · due 26 Nov · done 2026-11-13 · `4a3ddea`
- [x] **7.5** Eligible but Not Registered · due 26 Nov · done 2026-11-13 · `d921963`
- [ ] **7.6** Information Updation · due 27 Nov
- [ ] **7.7** Voter slip · due 27 Nov
- [ ] **7.8** Birthdays and Select many · due 27 Nov
- [ ] **7.9** More menu items · due 27 Nov
- [ ] **7.10** Conflict review · due 27 Nov
- [ ] **7.11** Part notes · due 27 Nov
- [ ] **7.12** Share on WhatsApp, at most 5 voters · due 27 Nov

## Step 8 – Polling day · 27–28 Nov · branch `step8-polling-day` — 0/3

- [ ] **8.1** Turnout API · due 27 Nov
- [ ] **8.2** Screens: Polling day, Mark voted · due 28 Nov
- [ ] **8.3** Screen: Mark many voted · due 28 Nov

## Step 9 – Admin · 28–29 Nov · branch `step9-admin` — 0/9

- [ ] **9.1** Users · due 28 Nov
- [ ] **9.2** Assignments · due 28 Nov
- [ ] **9.3** Constituencies · due 28 Nov
- [ ] **9.4** Settings and lists · due 28 Nov
- [ ] **9.5** Team and logs · due 29 Nov
- [ ] **9.6** Screens: Users & devices, Add user (also Add admin), Booths & karyakartas · due 29 Nov
- [ ] **9.7** Screens: Constituencies, Election & candidate (with polling time), Lists & labels (with the influencer list) · due 29 Nov
- [ ] **9.8** Screens: Activity log, Worker activity, Worker locations · due 29 Nov
- [ ] **9.9** Portal files on the server · due 29 Nov

## Step 10 – Matching Engine (roll update) and data quality · 29–30 Nov · branch `step10-roll` — 0/6

- [ ] **10.1** Worker · due 29 Nov
- [ ] **10.2** Roll upload and matching · due 29 Nov, two sessions
- [ ] **10.3** Review and apply · due 30 Nov
- [ ] **10.4** One-voter corrections · due 30 Nov
- [ ] **10.5** Data quality · due 30 Nov
- [ ] **10.6** Screens: Data quality, Repeated voters, Matching Engine, Correct roll record, Mobile numbers & contacts · due 30 Nov, two sessions

## Step 11 – Reports and exports · 30 Nov · branch `step11-reports` — 0/4

- [ ] **11.1** Reports · due 30 Nov
- [ ] **11.2** Exports · due 30 Nov
- [ ] **11.3** Screens: Reports & charts, Print or export a list · due 30 Nov
- [ ] **11.4** Working APK · due 30 Nov

## Step 12 – Hardening and handover · 1–15 Dec · branch `step12-delivery` — 0/10

- [ ] **12.2** `GET /voters/{id}/slip` · due 3 Dec
- [ ] **12.3** Fixes from client testing · due 3–10 Dec
- [ ] **12.4** Load test: 200 users syncing at once · due 5–6 Dec
- [ ] **12.5** Backups stored away from the server, · due 7 Dec
- [ ] **12.6** Isolation check · due 8 Dec
- [ ] **12.7** Server check · due 9 Dec
- [ ] **12.8** Handover notes · due 10–11 Dec
- [ ] **12.9** Admin training · due 12–14 Dec
- [ ] **12.11** Android 8 check · due 4 Dec
- [ ] **12.10** Final delivery · due 15 Dec

## Step 13 – Scanned roll PDFs (OCR) · 1–9 Dec · branch `step13-roll-ocr` — 0/8

- [ ] **13.1** Measure first · due 1 Dec
- [ ] **13.2** Page and box cutter · due 2 Dec
- [ ] **13.3** Field reading and rules · due 3 Dec
- [ ] **13.4** Better reading · due 4–5 Dec, two sessions
- [ ] **13.5** Checks, CSV, review file, accuracy test · due 6 Dec
- [ ] **13.6** Batch tool · due 7 Dec
- [ ] **13.7** Admin upload · due 8 Dec
- [ ] **13.9** Local AI helper (optional, off by default) · due 9 Dec

## Step 14 – Change requests of 12 Nov · 1–9 Dec · branch `step14-change-requests` — 0/8

- [ ] **14.1** Village Panchayat level · due 1 Dec
- [ ] **14.2** Surname search · due 2 Dec
- [ ] **14.3** Report numbers · due 3 Dec
- [ ] **14.4** Report lists and downloads · due 4 Dec
- [ ] **14.5** Screens: Reports and Report view · due 5 Dec
- [ ] **14.6** Matching Engine results and report · due 7 Dec
- [ ] **14.7** Know My Constituency: server · due 8 Dec
- [ ] **14.8** Know My Constituency: screens · due 9 Dec
