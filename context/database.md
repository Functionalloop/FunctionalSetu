# Database

Schema: `db/migrations/001_jansetu_schema.sql` (PostgreSQL 16, schema `app`) plus `002_client_changes.sql` (12 Nov: every schema change for the client's list; do not add another `002`) and `003_kutumb_members.sql` (7.1, 13 Nov). Next: `004_client_changes_final.sql` (7.13), `005_change_requests.sql` (Step 14). Treat them as the data model. Do not edit an applied migration; add `002_...sql`. Its comments that mention Django, Celery or Nginx are out of date.

## Roles

| Role | Used by | RLS |
|---|---|---|
| `postgres` (superuser) | `scripts/migrate.py` only (creates roles, extensions) | n/a |
| `jansetu_owner` | imports, seed, `create_super_admin.py`, test setup | `BYPASSRLS` |
| `jansetu_app` | the API and the future worker | applies |

The API must never connect as owner or superuser. Passwords come from `deploy/.env` (`JANSETU_OWNER_PASSWORD`, `JANSETU_APP_PASSWORD`); `migrate.py` sets them after migrating.

## Row-level security

- Every tenant table has `tenant_id` and `FORCE ROW LEVEL SECURITY`.
- Each request runs `SELECT app.set_context(tenant, user, device)` first. Values are transaction-local. With no context every tenant table reads as empty (fails closed).
- Login runs with no tenant and finds the user through the `SECURITY DEFINER` function `app.login_lookup(tenant_code, username)`.
- Other helpers: `app.sync_watermark()` (xid8), `app.seed_tenant_defaults(tenant)` (colour tags, templates), `app.skip_audit` (bulk imports).
- Triggers stamp `sync_xid`, bump `version` (`voter_surveys`, `new_voters`) and write `audit_log`. Never write these by hand. `audit_log` is immutable.
- Limits enforced by trigger: 200 users per workspace; user scope check (`users_check_scope`).

## Tables (names only)

Tenancy/auth: `tenants`, `users`, `devices`, `auth_sessions`, `user_area_assignments`, `karyakartas`, `platform_admins`.
Geography: `geo_units` (levels local_body > ward > booth, `path` set by trigger).
Roll: `voters`, `roll_versions`, `roll_part_versions`, `roll_import_rows`, `voter_roll_edits`, `voter_duplicate_pairs`, `voter_name_corrections`.
Campaign: `voter_surveys`, `families`, `family_members` (003), `visits`, `voter_turnout`, `slip_events`, `new_voters`.
Masters/settings: `castes`, `professions`, `color_tags`, `custom_field_labels`, `ui_labels`, `ui_label_overrides`, `tenant_settings`, `message_templates`, `saved_filters`, `files`, `terms_versions`, `app_releases`.
Sync: `sync_mutations`, `sync_conflicts`. Admin: `announcements`, `announcement_reads`, `problem_reports`, `mobile_import_batches`, `mobile_import_rows`, `exports`, `daily_booth_stats`, `audit_log`.

## Scripts (run from the repo root, settings from `deploy/.env`)

```
docker compose -f deploy/docker-compose.dev.yml up -d     # dev DB on 127.0.0.1:5442
python scripts/migrate.py [--status]                      # apply pending migrations (SHA-256 recorded in public.schema_migrations)
python db/seed/seed.py                                    # FAKE data, workspace "demo" (stops if it exists)
python scripts/import_roll_parts.py --parts "DIR/S05A02P*.csv" [--dry-run] [--tenant-code naik] [--errors PATH]
python scripts/create_super_admin.py --username X --name "Full Name"   # prints a one-time temp password
python scripts/create_super_admin.py --username X --reset              # existing super admin: new temp password, sessions ended, phones pending
python scripts/approve_phone.py --username X                       # first admin phone (nobody can approve it in the app yet)
python scripts/create_demo_users.py [--parts 1,2] [--reset | --remove]  # demo.* users; passwords -> jansetu-private/demo_users.txt
python scripts/export_openapi.py                          # rewrites docs/openapi.json
python scripts/check_dev_data.py                          # end-of-step check on the real roll (read-only / rolled back)
```

## State (11 Nov 2026)

- Dev database `jansetu` holds the real roll: workspace `naik`, AC 2, 31,871 voters. Mapping: one ward per roll part (50), one booth per part. Dev DB is Docker volume `pgdata`.
- Users in `naik` (11 Nov): only the four demo users from `create_demo_users.py` (demo.superadmin, demo.admin, demo.supervisor = wards of parts 1-2, demo.surveyor = booths of parts 1-2, 872 voters). All must change their temporary password at first login. **No real super admin yet**: create it with `create_super_admin.py` when the client names the person; switch the demo users off after the demo (`--remove`).
- `--reset` before each rehearsal: new temporary passwords, sessions ended, demo phones back to pending.
- 002 (12 Nov): white colour tag switched off in every workspace and no longer seeded; tables `positions`, `influencer_types` (placeholder entries from `app.seed_client_lists`, also run for existing workspaces), `part_notes` (one row per booth, `version`); survey columns for position, influencer type, self help group, ration card; `tenant_settings.polling_start_time` / `polling_end_time`.
- 003 (13 Nov): `family_members` (PK `voter_id` = one Kutumb at most; `family_id` NULL = taken out, the row stays so a delta pull sees it; touch, audit, RLS). `voter_surveys.family_id` and `families.head_voter_id` stay in the schema **unused**: membership in `voter_surveys` would raise the survey version (false 409s) and create survey rows.
- Not imported (decided): the old VoterappDB data. `scripts/import_legacy.py` is not run; `import_roll_parts.py` reuses its helpers.
- Import leaves: no Marathi names, no `voter_surveys` rows (first survey save creates it), no `families`.
- Re-running an import skips voters already present (EPIC, or booth + serial).

## Pitfalls

- Real voter data: show counts and shapes only, never names, EPICs or mobiles. Import error files go to `../jansetu-private/`.
- `migrate.py` hashes migrations with CRLF read as LF (13 Nov): git on Windows checks files out with CRLF (`core.autocrlf`), which changed the SHA-256 of 002 on the laptop. `.gitattributes` now keeps `*.sql` and `*.sh` LF everywhere. Test: `tests/test_migrate_digest.py`.
- `migrate.py`: a file with its own `BEGIN/COMMIT` (like 001) runs as written; any other file runs in one transaction with its record. Prefer the second form from 002 on.
- A new migration must start with `SET LOCAL ROLE jansetu_owner;` (as 002 does): migrate.py connects as the superuser, and only objects owned by `jansetu_owner` get the default grants to `jansetu_app`. New tables also need their `touch_row` / `audit_changes` triggers and the RLS policy (002's loop).
- Port 5442 is used so it does not clash with other local PostgreSQL containers.
- The tests use `jansetu_test` or `jansetu_test_<runner>` (see `backend.md`); never point them at `jansetu`.
