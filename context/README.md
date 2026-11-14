# context/ – index

One file per section. Read `CLAUDE.md`, this index, and only the file for the section you are working on.

| File | Section | Read it when |
|---|---|---|
| `database.md` | Schema, migrations, RLS, roles, import and seed scripts | touching `db/`, `scripts/`, or anything about tenants, roles, RLS |
| `backend.md` | FastAPI layout, dependencies, error codes, test fixtures, endpoints built | touching `backend/` |
| `sync.md` | Watermark, first download, delta pull, push: server and phone side | touching `/sync/*` or the phone's sync |
| `android.md` | Android app: build, layout, local database, search, sync on the phone | touching `android/` |
| `roll_ocr.md` | Reading scanned roll PDFs into the import CSV (Step 13) | touching `app/roll_ocr/`, `scripts/roll_ocr.py` or roll PDFs |
| `deploy.md` | Server (Bluehost VPS), Docker Compose, Caddy, backups, APK publishing | touching `deploy/`, `scripts/backup.sh`, the server or HTTPS |
| `portal.md` | Web portal (Step 15, built by me since 14 Nov): safety rules, stack, pages by task, contract notes | touching `portal/`, `openapi.json`, or Caddy for the portal |

Rules for these files: current state, decisions with dates, pitfalls, commands. No history of finished work, no copies of `docs/`, no real voter data. Update the file in the same commit as the change.
