# context/ – index

One file per section. Read `CLAUDE.md`, this index, and only the file for the section you are working on.

| File | Section | Read it when |
|---|---|---|
| `database.md` | Schema, migrations, RLS, roles, import and seed scripts | touching `db/`, `scripts/`, or anything about tenants, roles, RLS |
| `backend.md` | FastAPI layout, dependencies, error codes, test fixtures, endpoints built | touching `backend/` |
| `sync.md` | Watermark, first download, delta pull, push: server and phone side | touching `/sync/*` or the phone's sync |
| `android.md` | Android app: build, layout, local database, search, sync on the phone | touching `android/` |
| `portal.md` | The contract the portal builds on (I may build the portal myself) | touching `openapi.json` or `portal/` |

Not written yet (create the file the first time a session works on that section):
`deploy.md`.

Rules for these files: current state, decisions with dates, pitfalls, commands. No history of finished work, no copies of `docs/`, no real voter data. Update the file in the same commit as the change.
