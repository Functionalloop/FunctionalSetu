# context/ – index

One file per section. Read `CLAUDE.md`, this index, and only the file for the section you are working on.

| File | Section | Read it when |
|---|---|---|
| `database.md` | Schema, migrations, RLS, roles, import and seed scripts | touching `db/`, `scripts/`, or anything about tenants, roles, RLS |
| `backend.md` | FastAPI layout, dependencies, error codes, test fixtures, endpoints built | touching `backend/` |

Not written yet (create the file the first time a session works on that section):
`sync.md`, `android.md`, `deploy.md`, `portal.md`.

Rules for these files: current state, decisions with dates, pitfalls, commands. No history of finished work, no copies of `docs/`, no real voter data. Update the file in the same commit as the change.
