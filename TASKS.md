# JANSETU – implementation tracker

Generated from `docs/plan.md` by `scripts/tasks.py`. Full task text, files and tests are in the plan.
Tick with `python scripts/tasks.py done 4.1` (or tick a box here and run `python scripts/tasks.py sync`).

**Overall: 9 / 74 done (12%)** `██░░░░░░░░░░░░░░░░░░`

| Section | Done | Progress |
|---|---|---|
| Step 4 – Demo API | 9 / 12 | `████████░░` |
| Step 5 – Android demo app | 0 / 13 | `░░░░░░░░░░` |
| Step 6 – Server | 0 / 6 | `░░░░░░░░░░` |
| Demo | 0 / 2 | `░░░░░░░░░░` |
| Step 7 – Field screens | 0 / 9 | `░░░░░░░░░░` |
| Step 8 – Polling day | 0 / 3 | `░░░░░░░░░░` |
| Step 9 – Admin | 0 / 9 | `░░░░░░░░░░` |
| Step 10 – Roll update and data quality | 0 / 6 | `░░░░░░░░░░` |
| Step 11 – Reports and exports | 0 / 4 | `░░░░░░░░░░` |
| Step 12 – Hardening and handover | 0 / 10 | `░░░░░░░░░░` |

## Step 4 – Demo API · 12–17 Nov · branch `step4-demo-api` — 9/12

- [x] **4.0** Merge step 3 into `main` · due 12 Nov · done 2026-11-11 · `baae929`
- [x] **4.1** Area scope helper · due 12 Nov · done 2026-11-11 · `ae6f6b8`
- [x] **4.2** `GET /geo/tree` · due 12 Nov · done 2026-11-11 · `b298568`
- [x] **4.3** `GET /voters` · due 13 Nov · done 2026-11-11 · `b8b95de`
- [x] **4.11** Generic endpoint checks · due 11 Nov · done 2026-11-11 · `db508b2`
- [x] **4.4** `GET /voters/{id}` and `PUT /voters/{id}/survey` · due 13 Nov · done 2026-11-11 · `ad838da`
- [x] **4.5** `GET /devices` · due 13 Nov · done 2026-11-11 · `fa5f825`
- [x] **4.6** `GET /sync/pull`, first download · due 14 Nov · done 2026-11-11 · `76e32db`
- [x] **4.7** `GET /sync/pull?since=W` · due 14 Nov · done 2026-11-11 · `e3cabf4`
- [ ] **4.8** `POST /sync/push` · due 15 Nov
- [ ] **4.9** Demo users · due 15 Nov
- [ ] **4.10** Contract for the remaining endpoints · due 16–17 Nov, two sessions

## Step 5 – Android demo app · 14–23 Nov · branch `step5-android-demo` — 0/13

- [ ] **5.1** Project · due 14 Nov
- [ ] **5.2** Local database · due 15 Nov
- [ ] **5.3** Search · due 16 Nov
- [ ] **5.4** API client · due 17 Nov
- [ ] **5.5** Login, Set password, Device approval · due 17–18 Nov
- [ ] **5.6** First download · due 18–19 Nov
- [ ] **5.7** Home, bottom bar, More menu shell · due 19 Nov
- [ ] **5.8** Filters · due 20 Nov
- [ ] **5.9** Voter profile, Details tab, · due 20 Nov
- [ ] **5.10** Survey tab · due 21 Nov
- [ ] **5.11** Push, delta pull and the Sync screen · due 21–22 Nov
- [ ] **5.12** Blocked phone and logout · due 22 Nov
- [ ] **5.13** Rehearsal on a real phone · due 23 Nov

## Step 6 – Server · 19–23 Nov · branch `step6-server` — 0/6

- [ ] **6.1** Production containers, · due 19 Nov
- [ ] **6.2** Nightly backup · due 19 Nov
- [ ] **6.3** APK download and `GET /app/version` · due 20 Nov
- [ ] **6.4** Server setup · due 20–21 Nov
- [ ] **6.5** Data on the server · due 21 Nov
- [ ] **6.6** Laptop fallback · due 22 Nov

## Demo · 24–25 Nov — 0/2

- [ ] **D.1** 24 Nov: freeze
- [ ] **D.2** 25 Nov: demo script

## Step 7 – Field screens · 26–27 Nov · branch `step7-field` — 0/9

- [ ] **7.1** Families from house numbers · due 26 Nov
- [ ] **7.2** Family and walk list API · due 26 Nov
- [ ] **7.3** Visits API · due 26 Nov
- [ ] **7.4** Screens: Family, Walk list · due 26 Nov
- [ ] **7.5** New voters · due 26 Nov
- [ ] **7.6** History · due 27 Nov
- [ ] **7.7** Voter slip · due 27 Nov
- [ ] **7.8** Birthdays and Select many · due 27 Nov
- [ ] **7.9** More menu items · due 27 Nov

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
- [ ] **9.7** Screens: Constituencies, Election & candidate, Lists & labels · due 29 Nov
- [ ] **9.8** Screens: Activity log, Worker activity, Worker locations · due 29 Nov
- [ ] **9.9** Portal files on the server · due 29 Nov

## Step 10 – Roll update and data quality · 29–30 Nov · branch `step10-roll` — 0/6

- [ ] **10.1** Worker · due 29 Nov
- [ ] **10.2** Roll upload and matching · due 29 Nov, two sessions
- [ ] **10.3** Review and apply · due 30 Nov
- [ ] **10.4** One-voter corrections · due 30 Nov
- [ ] **10.5** Data quality · due 30 Nov
- [ ] **10.6** Screens: Data quality, Repeated voters, Spelling fixes, Roll update, Correct roll record, Mobile numbers & contacts · due 30 Nov, two sessions

## Step 11 – Reports and exports · 30 Nov · branch `step11-reports` — 0/4

- [ ] **11.1** Reports · due 30 Nov
- [ ] **11.2** Exports · due 30 Nov
- [ ] **11.3** Screens: Reports & charts, Print or export a list · due 30 Nov
- [ ] **11.4** Working APK · due 30 Nov

## Step 12 – Hardening and handover · 1–15 Dec · branch `step12-delivery` — 0/10

- [ ] **12.1** Roll import from text PDF · due 1–3 Dec
- [ ] **12.2** `GET /voters/{id}/slip` · due 3 Dec
- [ ] **12.3** Fixes from client testing · due 3–10 Dec
- [ ] **12.4** Load test: 200 users syncing at once · due 5–6 Dec
- [ ] **12.5** Backups stored away from the server, · due 7 Dec
- [ ] **12.6** Isolation check · due 8 Dec
- [ ] **12.7** Server check · due 9 Dec
- [ ] **12.8** Handover notes · due 10–11 Dec
- [ ] **12.9** Admin training · due 12–14 Dec
- [ ] **12.10** Final delivery · due 15 Dec
