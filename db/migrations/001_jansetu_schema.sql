-- =============================================================================
--  JANSETU · PostgreSQL 16 schema · 001 (initial)
-- =============================================================================
--  Covers every screen in the app wireframes and every field in the old
--  VoterApp database export (voters, masters, settings, activation, reports).
--
--  How to run (once, on an empty database, as a superuser such as postgres):
--      createdb jansetu
--      psql -d jansetu -v ON_ERROR_STOP=1 -f 001_jansetu_schema.sql
--  Then set passwords:
--      ALTER ROLE jansetu_owner PASSWORD '...';   -- migrations, imports, nightly jobs
--      ALTER ROLE jansetu_app   PASSWORD '...';   -- the Django/DRF API and Celery
--
--  Tenant isolation (multi-tenant workspaces):
--    * Every tenant-owned table has tenant_id and FORCE ROW LEVEL SECURITY.
--    * The API runs as jansetu_app (NOBYPASSRLS). At the start of EVERY
--      transaction it must call:
--          SELECT app.set_context(:tenant_id, :user_id, :device_id);
--      With no context set, every tenant table returns zero rows (fails closed).
--    * Celery tasks must call app.set_context too.
--    * jansetu_owner has BYPASSRLS. Use it only for migrations, roll imports and
--      platform administration, never from the request path.
--
--  Sync model (Android offline cache):
--    * Synced tables carry sync_xid (the transaction that last wrote the row)
--      and deleted_at (tombstone). A pull is:
--          1. W_new := app.sync_watermark()
--          2. rows in the user's areas WHERE sync_xid >= W_phone
--          3. phone stores W_new
--      This never skips a row from a transaction that was still open during
--      the last pull (a plain sequence number can). A few rows get re-sent,
--      which is harmless because pulls are upserts.
--    * When a user is given a new area, the API sends that area in full.
--    * voter_surveys and new_voters carry `version` for optimistic locking.
--      A push with a stale base version becomes a row in sync_conflicts;
--      nothing is overwritten silently.
--
--  Official roll data (voters) and campaign data (voter_surveys, visits,
--  voter_turnout, slip_events) live in separate tables. Roll updates never
--  touch campaign data and never mark anyone dead.
-- =============================================================================

\set ON_ERROR_STOP on

-- -----------------------------------------------------------------------------
-- 0. Roles, extensions, schema
-- -----------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jansetu_owner') THEN
    CREATE ROLE jansetu_owner LOGIN BYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jansetu_app') THEN
    CREATE ROLE jansetu_app LOGIN NOBYPASSRLS;
  END IF;
  EXECUTE format('GRANT CONNECT, CREATE ON DATABASE %I TO jansetu_owner', current_database());
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO jansetu_app', current_database());
END $$;

CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- fuzzy name search
CREATE EXTENSION IF NOT EXISTS citext;    -- case-insensitive usernames, codes
CREATE EXTENSION IF NOT EXISTS ltree;     -- area hierarchy paths

BEGIN;

SET ROLE jansetu_owner;
CREATE SCHEMA app AUTHORIZATION jansetu_owner;
SET search_path = app, public;

-- -----------------------------------------------------------------------------
-- 1. Types
-- -----------------------------------------------------------------------------
-- super_admin: every constituency in the workspace, adds admins
-- admin: one constituency (local body), adds its users
-- supervisor / surveyor / booth_agent: only the wards and booths assigned to them
CREATE TYPE app.user_role          AS ENUM ('super_admin', 'admin', 'supervisor', 'surveyor', 'booth_agent');
CREATE TYPE app.device_status      AS ENUM ('pending', 'approved', 'blocked', 'wiped');
CREATE TYPE app.geo_level          AS ENUM ('local_body', 'taluka', 'gat', 'gan', 'ward', 'booth', 'section');
CREATE TYPE app.gender             AS ENUM ('M', 'F', 'O');
CREATE TYPE app.relation_type      AS ENUM ('father', 'mother', 'husband', 'wife', 'other');
CREATE TYPE app.roll_status        AS ENUM ('active', 'absent_from_current_roll', 'deleted_in_roll');
CREATE TYPE app.list_type          AS ENUM ('main', 'supplementary', 'draft');
CREATE TYPE app.visit_outcome      AS ENUM ('met', 'not_home', 'revisit', 'shifted');
CREATE TYPE app.form6_status       AS ENUM ('not_applied', 'applied', 'approved', 'rejected');
CREATE TYPE app.match_status       AS ENUM ('matched', 'uncertain', 'possible_duplicate', 'absent_from_current_roll', 'new');
CREATE TYPE app.review_status      AS ENUM ('pending', 'accepted', 'rejected');
CREATE TYPE app.pair_status        AS ENUM ('unchecked', 'same_person', 'different_people');
CREATE TYPE app.conflict_status    AS ENUM ('open', 'kept_client', 'kept_server');
CREATE TYPE app.slip_channel       AS ENUM ('pdf', 'print', 'whatsapp', 'sms', 'bluetooth');
CREATE TYPE app.job_status         AS ENUM ('queued', 'running', 'done', 'failed');
CREATE TYPE app.roll_import_status AS ENUM ('uploaded', 'parsing', 'review', 'applied', 'failed', 'discarded');
CREATE TYPE app.file_kind          AS ENUM ('candidate_photo', 'symbol', 'slip_header', 'whatsapp_slip',
                                            'voter_photo', 'user_photo', 'roll_import', 'mobile_import',
                                            'export', 'other');
CREATE TYPE app.custom_field_key   AS ENUM ('extra_check_1', 'extra_check_2', 'extra_info_1', 'extra_info_2',
                                            'extra_info_3', 'extra_info_4', 'extra_info_5');
CREATE TYPE app.mobile_match_status AS ENUM ('matched', 'needs_review', 'not_found', 'skipped');
CREATE TYPE app.turnout_source     AS ENUM ('single', 'bulk_typed', 'booth_list', 'admin');
CREATE TYPE app.roll_edit_action   AS ENUM ('add', 'correct', 'remove', 'restore');
CREATE TYPE app.lang               AS ENUM ('mr', 'en', 'hi');

-- Indian mobile number, stored as 10 digits without +91 or spaces
CREATE DOMAIN app.mobile_no AS text CHECK (VALUE ~ '^[6-9][0-9]{9}$');

-- -----------------------------------------------------------------------------
-- 2. Context and helper functions
-- -----------------------------------------------------------------------------
CREATE FUNCTION app.current_tenant_id() RETURNS uuid
LANGUAGE sql STABLE PARALLEL SAFE AS $$
  SELECT nullif(current_setting('app.current_tenant_id', true), '')::uuid
$$;

CREATE FUNCTION app.current_user_id() RETURNS uuid
LANGUAGE sql STABLE PARALLEL SAFE AS $$
  SELECT nullif(current_setting('app.current_user_id', true), '')::uuid
$$;

CREATE FUNCTION app.current_device_id() RETURNS uuid
LANGUAGE sql STABLE PARALLEL SAFE AS $$
  SELECT nullif(current_setting('app.current_device_id', true), '')::uuid
$$;

-- Call at the start of every API / Celery transaction. Values last until COMMIT.
CREATE FUNCTION app.set_context(p_tenant uuid, p_user uuid DEFAULT NULL, p_device uuid DEFAULT NULL)
RETURNS void LANGUAGE sql AS $$
  SELECT set_config('app.current_tenant_id', coalesce(p_tenant::text, ''), true),
         set_config('app.current_user_id',   coalesce(p_user::text, ''),   true),
         set_config('app.current_device_id', coalesce(p_device::text, ''), true);
$$;

-- Delta-sync watermark: every transaction older than this has finished.
CREATE FUNCTION app.sync_watermark() RETURNS xid8
LANGUAGE sql VOLATILE AS $$
  SELECT pg_snapshot_xmin(pg_current_snapshot())
$$;

-- updated_at + sync_xid on tenant tables; tenant_id may never change
CREATE FUNCTION app.touch_row() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND NEW.tenant_id IS DISTINCT FROM OLD.tenant_id THEN
    RAISE EXCEPTION 'tenant_id cannot be changed on %', TG_TABLE_NAME;
  END IF;
  NEW.updated_at := now();
  NEW.sync_xid   := pg_current_xact_id();
  RETURN NEW;
END $$;

-- updated_at only (global tables)
CREATE FUNCTION app.touch_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$;

-- optimistic-lock counter for rows edited offline
CREATE FUNCTION app.bump_version() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.version := OLD.version + 1;
  RETURN NEW;
END $$;

-- -----------------------------------------------------------------------------
-- 3. Tenants, platform, files, settings
-- -----------------------------------------------------------------------------
CREATE TABLE app.tenants (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code                  citext NOT NULL UNIQUE CHECK (code ~ '^[a-z0-9][a-z0-9-]{2,39}$'),
  name_en               text NOT NULL,
  name_mr               text,
  status                text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'archived')),
  max_users             int  NOT NULL DEFAULT 200 CHECK (max_users > 0),
  max_concurrent_users  int  NOT NULL DEFAULT 150 CHECK (max_concurrent_users > 0),
  max_local_bodies      int  NOT NULL DEFAULT 5   CHECK (max_local_bodies > 0),
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE app.tenants IS 'One workspace per client campaign (white-label). Limits from Schedule A3: 200 users, 150 concurrent.';

-- Vendor staff who create tenants. Not visible to jansetu_app.
CREATE TABLE app.platform_admins (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  username       citext NOT NULL UNIQUE,
  full_name      text NOT NULL,
  password_hash  text NOT NULL,
  is_active      boolean NOT NULL DEFAULT true,
  last_login_at  timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now()
);

-- Every uploaded or generated file. Files live on the server disk, never on an outside service.
CREATE TABLE app.files (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      uuid NOT NULL REFERENCES app.tenants(id),
  kind           app.file_kind NOT NULL,
  storage_path   text NOT NULL,
  original_name  text,
  mime_type      text NOT NULL,
  size_bytes     bigint NOT NULL CHECK (size_bytes >= 0),
  sha256         char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  created_by     uuid,
  created_at     timestamptz NOT NULL DEFAULT now(),
  deleted_at     timestamptz,
  UNIQUE (tenant_id, id)
);

CREATE TABLE app.tenant_settings (
  tenant_id                   uuid PRIMARY KEY REFERENCES app.tenants(id),
  -- election
  election_code               text,
  election_name_mr            text,
  election_name_en            text,
  election_type               text CHECK (election_type IN ('nagarpalika', 'nagar_panchayat', 'municipal_corporation',
                                         'zilla_parishad', 'panchayat_samiti', 'gram_panchayat',
                                         'vidhan_sabha', 'lok_sabha', 'other')),
  polling_date                date,
  -- candidate (hidden everywhere while code_of_conduct_mode is on)
  candidate_name_mr           text,
  candidate_name_en           text,
  party_name_mr               text,
  party_name_en               text,
  candidate_photo_file_id     uuid,
  symbol_file_id              uuid,
  candidate_message_mr        text,
  candidate_message_en        text,
  -- message text added to every WhatsApp / SMS
  message_start_mr            text,
  message_start_en            text,
  message_end_mr              text,
  message_end_en              text,
  contact_no                  app.mobile_no,
  -- slip images
  slip_header_file_id         uuid,
  whatsapp_slip_file_id       uuid,
  code_of_conduct_mode        boolean NOT NULL DEFAULT false,
  -- feature switches
  feature_voter_photos        boolean NOT NULL DEFAULT true,
  feature_survey              boolean NOT NULL DEFAULT true,
  feature_slips               boolean NOT NULL DEFAULT true,
  feature_workers_edit_slip   boolean NOT NULL DEFAULT false,
  feature_mobile_import       boolean NOT NULL DEFAULT true,
  feature_surname_first       boolean NOT NULL DEFAULT true,
  feature_bluetooth_printer   boolean NOT NULL DEFAULT false,   -- Phase 2
  -- what the slip and the SMS show
  slip_show_election_name     boolean NOT NULL DEFAULT true,
  slip_show_booth_address     boolean NOT NULL DEFAULT true,
  slip_show_assembly_mapping  boolean NOT NULL DEFAULT true,
  slip_show_candidate         boolean NOT NULL DEFAULT false,
  sms_fields                  text[] NOT NULL DEFAULT ARRAY['election_name', 'booth_address']
                              CHECK (sms_fields <@ ARRAY['election_name', 'middle_name', 'booth_address',
                                                         'candidate_info', 'party_name', 'symbol']),
  -- app behaviour
  default_language            app.lang NOT NULL DEFAULT 'mr',
  min_app_version_code        int NOT NULL DEFAULT 1 CHECK (min_app_version_code > 0),
  sync_interval_minutes       int NOT NULL DEFAULT 15 CHECK (sync_interval_minutes BETWEEN 5 AND 240),
  middle_name_separator       text,
  updated_by                  uuid,
  updated_at                  timestamptz NOT NULL DEFAULT now(),
  sync_xid                    xid8   NOT NULL DEFAULT '0',
  FOREIGN KEY (tenant_id, candidate_photo_file_id) REFERENCES app.files (tenant_id, id),
  FOREIGN KEY (tenant_id, symbol_file_id)          REFERENCES app.files (tenant_id, id),
  FOREIGN KEY (tenant_id, slip_header_file_id)     REFERENCES app.files (tenant_id, id),
  FOREIGN KEY (tenant_id, whatsapp_slip_file_id)   REFERENCES app.files (tenant_id, id)
);

-- -----------------------------------------------------------------------------
-- 4. Area hierarchy: local body -> (taluka / gat / gan) -> ward -> booth -> section
-- -----------------------------------------------------------------------------
CREATE TABLE app.geo_units (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES app.tenants(id),
  parent_id    uuid,
  level        app.geo_level NOT NULL,
  code         text NOT NULL,              -- source code: local body 177, ward 1, booth 1001, section 133-2
  number       int,                        -- ward no. / booth no. within ward / section no.
  name_mr      text NOT NULL,
  name_en      text,
  address_mr   text,                       -- polling station address (booth level)
  address_en   text,
  ac_no        int,                        -- real Vidhan Sabha constituency (local_body level), e.g. 270
  path         ltree NOT NULL,             -- set by trigger
  sort_order   int NOT NULL DEFAULT 0,
  is_active    boolean NOT NULL DEFAULT true,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  sync_xid     xid8   NOT NULL DEFAULT '0',
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, parent_id) REFERENCES app.geo_units (tenant_id, id),
  CHECK ((level = 'local_body') = (parent_id IS NULL))
);
CREATE UNIQUE INDEX geo_units_code_uq ON app.geo_units
  (tenant_id, coalesce(parent_id, '00000000-0000-0000-0000-000000000000'::uuid), level, code);
CREATE INDEX geo_units_path_gist ON app.geo_units USING gist (path);
CREATE INDEX geo_units_parent_idx ON app.geo_units (tenant_id, parent_id);
CREATE INDEX geo_units_level_idx ON app.geo_units (tenant_id, level);

CREATE FUNCTION app.geo_level_rank(l app.geo_level) RETURNS int
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE l WHEN 'local_body' THEN 1 WHEN 'taluka' THEN 2 WHEN 'gat' THEN 3
                WHEN 'gan' THEN 4 WHEN 'ward' THEN 5 WHEN 'booth' THEN 6 WHEN 'section' THEN 7 END
$$;

CREATE FUNCTION app.geo_units_set_path() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  p_path  ltree;
  p_level app.geo_level;
  n_local int;
  n_max   int;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF NEW.parent_id IS DISTINCT FROM OLD.parent_id OR NEW.level <> OLD.level THEN
      RAISE EXCEPTION 'geo_units: parent and level cannot change; create a new unit instead';
    END IF;
    NEW.path := OLD.path;
    RETURN NEW;
  END IF;

  IF NEW.parent_id IS NULL THEN
    -- Schedule A3 limit on constituencies / local bodies per tenant
    PERFORM pg_advisory_xact_lock(hashtextextended('geo_limit:' || NEW.tenant_id::text, 0));
    SELECT max_local_bodies INTO n_max FROM app.tenants WHERE id = NEW.tenant_id;
    SELECT count(*) INTO n_local FROM app.geo_units
      WHERE tenant_id = NEW.tenant_id AND level = 'local_body' AND is_active;
    IF n_local >= n_max THEN
      RAISE EXCEPTION 'tenant limit reached: % local bodies', n_max;
    END IF;
    NEW.path := text2ltree('u' || replace(NEW.id::text, '-', ''));
  ELSE
    SELECT path, level INTO p_path, p_level FROM app.geo_units
      WHERE tenant_id = NEW.tenant_id AND id = NEW.parent_id;
    IF p_path IS NULL THEN
      RAISE EXCEPTION 'geo_units: parent % not found', NEW.parent_id;
    END IF;
    IF app.geo_level_rank(NEW.level) <= app.geo_level_rank(p_level) THEN
      RAISE EXCEPTION 'geo_units: a % cannot sit under a %', NEW.level, p_level;
    END IF;
    NEW.path := p_path || text2ltree('u' || replace(NEW.id::text, '-', ''));
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER geo_units_path BEFORE INSERT OR UPDATE ON app.geo_units
  FOR EACH ROW EXECUTE FUNCTION app.geo_units_set_path();

-- -----------------------------------------------------------------------------
-- 5. Users, karyakartas, area assignments, devices, sessions
-- -----------------------------------------------------------------------------
CREATE TABLE app.users (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id             uuid NOT NULL REFERENCES app.tenants(id),
  username              citext NOT NULL CHECK (username ~ '^[A-Za-z0-9._-]{3,40}$'),
  mobile                app.mobile_no,
  full_name_en          text NOT NULL,
  full_name_mr          text,
  role                  app.user_role NOT NULL,
  local_body_id         uuid,                          -- constituency; NULL only for super_admin
  password_hash         text NOT NULL,                 -- Argon2id. Login is user ID + password only (no OTP).
  must_change_password  boolean NOT NULL DEFAULT true,
  is_active             boolean NOT NULL DEFAULT true,
  failed_login_count    int NOT NULL DEFAULT 0,
  locked_until          timestamptz,
  last_login_at         timestamptz,
  terms_version         int,
  terms_accepted_at     timestamptz,
  photo_file_id         uuid,
  preferred_language    app.lang NOT NULL DEFAULT 'mr',
  created_by            uuid,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  deleted_at            timestamptz,
  sync_xid              xid8   NOT NULL DEFAULT '0',
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, photo_file_id) REFERENCES app.files (tenant_id, id),
  FOREIGN KEY (tenant_id, local_body_id) REFERENCES app.geo_units (tenant_id, id),
  CHECK ((role = 'super_admin') = (local_body_id IS NULL))
);
CREATE INDEX users_local_body_idx ON app.users (tenant_id, local_body_id) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX users_username_uq ON app.users (tenant_id, username) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX users_mobile_uq   ON app.users (tenant_id, mobile)   WHERE deleted_at IS NULL AND mobile IS NOT NULL;
CREATE INDEX users_role_idx ON app.users (tenant_id, role) WHERE deleted_at IS NULL;

ALTER TABLE app.files ADD FOREIGN KEY (tenant_id, created_by) REFERENCES app.users (tenant_id, id);

-- Schedule A3: at most max_users accounts per tenant
CREATE FUNCTION app.users_check_limit() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE n int; n_max int;
BEGIN
  IF NEW.deleted_at IS NOT NULL OR NOT NEW.is_active THEN RETURN NEW; END IF;
  IF TG_OP = 'UPDATE' AND OLD.deleted_at IS NULL AND OLD.is_active THEN RETURN NEW; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('user_limit:' || NEW.tenant_id::text, 0));
  SELECT max_users INTO n_max FROM app.tenants WHERE id = NEW.tenant_id;
  SELECT count(*) INTO n FROM app.users
    WHERE tenant_id = NEW.tenant_id AND deleted_at IS NULL AND is_active AND id <> NEW.id;
  IF n >= n_max THEN
    RAISE EXCEPTION 'tenant limit reached: % active users', n_max;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER users_limit BEFORE INSERT OR UPDATE OF is_active, deleted_at ON app.users
  FOR EACH ROW EXECUTE FUNCTION app.users_check_limit();

-- local_body_id must point to a constituency (local body), not a ward or booth
CREATE FUNCTION app.users_check_scope() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.local_body_id IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM app.geo_units g
       WHERE g.tenant_id = NEW.tenant_id AND g.id = NEW.local_body_id AND g.level = 'local_body') THEN
    RAISE EXCEPTION 'users.local_body_id must point to a local body';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER users_scope BEFORE INSERT OR UPDATE OF local_body_id ON app.users
  FOR EACH ROW EXECUTE FUNCTION app.users_check_scope();

-- Party workers voters are assigned to. May or may not have an app login.
CREATE TABLE app.karyakartas (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES app.tenants(id),
  user_id      uuid,
  name_en      text NOT NULL,
  name_mr      text,
  mobile       app.mobile_no,
  ward_id      uuid,
  is_active    boolean NOT NULL DEFAULT true,
  notes        text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  deleted_at   timestamptz,
  sync_xid     xid8   NOT NULL DEFAULT '0',
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, user_id) REFERENCES app.users (tenant_id, id),
  FOREIGN KEY (tenant_id, ward_id) REFERENCES app.geo_units (tenant_id, id)
);
CREATE INDEX karyakartas_ward_idx ON app.karyakartas (tenant_id, ward_id) WHERE deleted_at IS NULL;

-- Which wards / booths each user may download and edit (A8: scoped cache)
CREATE TABLE app.user_area_assignments (
  tenant_id    uuid NOT NULL REFERENCES app.tenants(id),
  user_id      uuid NOT NULL,
  geo_unit_id  uuid NOT NULL,
  assigned_by  uuid,
  assigned_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, user_id, geo_unit_id),
  FOREIGN KEY (tenant_id, user_id)     REFERENCES app.users (tenant_id, id),
  FOREIGN KEY (tenant_id, geo_unit_id) REFERENCES app.geo_units (tenant_id, id),
  FOREIGN KEY (tenant_id, assigned_by) REFERENCES app.users (tenant_id, id)
);
CREATE INDEX uaa_geo_idx ON app.user_area_assignments (tenant_id, geo_unit_id);

-- Device binding, approval, block and remote wipe
CREATE TABLE app.devices (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           uuid NOT NULL REFERENCES app.tenants(id),
  user_id             uuid NOT NULL,
  device_uid_hash     char(64) NOT NULL,            -- SHA-256 of the Android ID + app salt
  model               text,
  os_version          text,
  app_version_code    int,
  status              app.device_status NOT NULL DEFAULT 'pending',
  requested_at        timestamptz NOT NULL DEFAULT now(),
  decided_by          uuid,
  decided_at          timestamptz,
  blocked_reason      text,
  wipe_requested_at   timestamptz,
  wipe_confirmed_at   timestamptz,
  last_seen_at        timestamptz,
  last_pull_watermark xid8 NOT NULL DEFAULT '0',
  last_push_at        timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  sync_xid            xid8   NOT NULL DEFAULT '0',
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, user_id, device_uid_hash),
  FOREIGN KEY (tenant_id, user_id)    REFERENCES app.users (tenant_id, id),
  FOREIGN KEY (tenant_id, decided_by) REFERENCES app.users (tenant_id, id),
  CHECK (status <> 'blocked' OR wipe_requested_at IS NOT NULL)
);
CREATE INDEX devices_status_idx ON app.devices (tenant_id, status);

-- Refresh tokens. "Online now" = sessions seen in the last few minutes (limit 150).
CREATE TABLE app.auth_sessions (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           uuid NOT NULL REFERENCES app.tenants(id),
  user_id             uuid NOT NULL,
  device_id           uuid,
  refresh_token_hash  char(64) NOT NULL UNIQUE,
  issued_at           timestamptz NOT NULL DEFAULT now(),
  expires_at          timestamptz NOT NULL,
  last_seen_at        timestamptz NOT NULL DEFAULT now(),
  revoked_at          timestamptz,
  revoke_reason       text,
  ip                  inet,
  user_agent          text,
  FOREIGN KEY (tenant_id, user_id)   REFERENCES app.users (tenant_id, id),
  FOREIGN KEY (tenant_id, device_id) REFERENCES app.devices (tenant_id, id),
  CHECK (expires_at > issued_at)
);
CREATE INDEX auth_sessions_live_idx ON app.auth_sessions (tenant_id, last_seen_at) WHERE revoked_at IS NULL;
CREATE INDEX auth_sessions_user_idx ON app.auth_sessions (tenant_id, user_id);

-- -----------------------------------------------------------------------------
-- 6. Masters and labels
-- -----------------------------------------------------------------------------
CREATE TABLE app.castes (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES app.tenants(id),
  name_mr      text NOT NULL,
  name_en      text,
  name_hi      text,
  sort_order   int NOT NULL DEFAULT 0,
  is_active    boolean NOT NULL DEFAULT true,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  sync_xid     xid8   NOT NULL DEFAULT '0',
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, name_mr)
);

CREATE TABLE app.professions (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES app.tenants(id),
  name_mr      text NOT NULL,
  name_en      text,
  name_hi      text,
  sort_order   int NOT NULL DEFAULT 0,
  is_active    boolean NOT NULL DEFAULT true,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  sync_xid     xid8   NOT NULL DEFAULT '0',
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, name_mr)
);

CREATE TABLE app.color_tags (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES app.tenants(id),
  code         text NOT NULL CHECK (code ~ '^[a-z_]{2,20}$'),
  hex          char(7) NOT NULL CHECK (hex ~ '^#[0-9A-Fa-f]{6}$'),
  label_mr     text NOT NULL,
  label_en     text NOT NULL,
  label_hi     text,
  is_default   boolean NOT NULL DEFAULT false,
  sort_order   int NOT NULL DEFAULT 0,
  is_active    boolean NOT NULL DEFAULT true,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  sync_xid     xid8   NOT NULL DEFAULT '0',
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, code)
);
CREATE UNIQUE INDEX color_tags_one_default ON app.color_tags (tenant_id) WHERE is_default;

-- Names for Extra Check 1-2 and Extra Info 1-5. Disabled fields are hidden in the survey.
CREATE TABLE app.custom_field_labels (
  tenant_id    uuid NOT NULL REFERENCES app.tenants(id),
  field_key    app.custom_field_key NOT NULL,
  label_mr     text,
  label_en     text,
  label_hi     text,
  is_enabled   boolean NOT NULL DEFAULT false,
  updated_at   timestamptz NOT NULL DEFAULT now(),
  sync_xid     xid8   NOT NULL DEFAULT '0',
  PRIMARY KEY (tenant_id, field_key),
  CHECK (NOT is_enabled OR coalesce(label_mr, label_en) IS NOT NULL)
);

-- Screen text shipped with the app (global), plus per-tenant overrides
CREATE TABLE app.ui_labels (
  key          text PRIMARY KEY CHECK (key ~ '^[a-z0-9_.]{2,80}$'),
  label_mr     text NOT NULL,
  label_hi     text,
  label_en     text NOT NULL,
  updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.ui_label_overrides (
  tenant_id    uuid NOT NULL REFERENCES app.tenants(id),
  key          text NOT NULL REFERENCES app.ui_labels(key),
  label_mr     text,
  label_hi     text,
  label_en     text,
  updated_at   timestamptz NOT NULL DEFAULT now(),
  sync_xid     xid8   NOT NULL DEFAULT '0',
  PRIMARY KEY (tenant_id, key)
);

-- -----------------------------------------------------------------------------
-- 7. Electoral roll (official data only)
-- -----------------------------------------------------------------------------
CREATE TABLE app.roll_versions (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES app.tenants(id),
  local_body_id    uuid NOT NULL,
  list_type        app.list_type NOT NULL,
  title            text NOT NULL,
  published_on     date,
  source_file_id   uuid,
  status           app.roll_import_status NOT NULL DEFAULT 'uploaded',
  stats            jsonb NOT NULL DEFAULT '{}'::jsonb,   -- matched / new / changed / absent / uncertain counts
  imported_by      uuid,
  applied_by       uuid,
  applied_at       timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  sync_xid         xid8   NOT NULL DEFAULT '0',
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, local_body_id)  REFERENCES app.geo_units (tenant_id, id),
  FOREIGN KEY (tenant_id, source_file_id) REFERENCES app.files (tenant_id, id),
  FOREIGN KEY (tenant_id, imported_by)    REFERENCES app.users (tenant_id, id),
  FOREIGN KEY (tenant_id, applied_by)     REFERENCES app.users (tenant_id, id)
);

-- Current list version per ward, shown as "List v20, 8 Oct 2025" and used for "new list available"
CREATE TABLE app.roll_part_versions (
  tenant_id        uuid NOT NULL REFERENCES app.tenants(id),
  ward_id          uuid NOT NULL,
  data_version     int  NOT NULL CHECK (data_version > 0),
  photo_version    int  NOT NULL DEFAULT 0,
  published_on     date,
  roll_version_id  uuid,
  updated_at       timestamptz NOT NULL DEFAULT now(),
  sync_xid         xid8   NOT NULL DEFAULT '0',
  PRIMARY KEY (tenant_id, ward_id),
  FOREIGN KEY (tenant_id, ward_id)         REFERENCES app.geo_units (tenant_id, id),
  FOREIGN KEY (tenant_id, roll_version_id) REFERENCES app.roll_versions (tenant_id, id)
);

CREATE TABLE app.voters (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),   -- internal voter id, never changes or gets reused
  tenant_id              uuid NOT NULL REFERENCES app.tenants(id),
  local_body_id          uuid NOT NULL,
  ward_id                uuid NOT NULL,
  booth_id               uuid NOT NULL,
  section_id             uuid,
  geo_path               ltree NOT NULL,                              -- booth path, set by trigger
  part_no                int NOT NULL,                                -- ward / part no. as printed in the roll
  booth_no               smallint,                                    -- 1-3 within the ward
  serial_no              int NOT NULL CHECK (serial_no > 0),          -- restarts in every booth
  draft_serial_no        int,
  epic_no                text CHECK (epic_no ~ '^[A-Z0-9/]{6,20}$'),
  first_name_mr          text,
  middle_name_mr         text,
  last_name_mr           text,
  first_name_en          text,                                        -- machine transliteration, may be misspelt
  middle_name_en         text,
  last_name_en           text,
  relation_type          app.relation_type,
  relative_name_mr       text,
  relative_name_en       text,
  gender                 app.gender NOT NULL,
  age                    smallint CHECK (age BETWEEN 18 AND 125),
  age_as_of              date,
  house_no               text,
  address_mr             text,                                        -- roll section text
  address_en             text,
  assembly_mapping       text CHECK (assembly_mapping ~ '^[0-9]+/[0-9]+/[0-9]+$'),  -- e.g. 270/133/255
  list_type              app.list_type NOT NULL DEFAULT 'main',
  roll_status            app.roll_status NOT NULL DEFAULT 'active',
  deletion_reason        text CHECK (deletion_reason IN ('shifted', 'dead', 'duplicate', 'other')),  -- only as printed in the roll
  is_repeated_in_roll    boolean NOT NULL DEFAULT false,
  photo_file_id          uuid,
  first_roll_version_id  uuid,
  last_roll_version_id   uuid,
  legacy_id              text,                                        -- id from the old app, e.g. 17700100100046
  full_name_en           text GENERATED ALWAYS AS (
                           btrim(coalesce(last_name_en, '') || ' ' || coalesce(first_name_en, '') || ' ' || coalesce(middle_name_en, ''))
                         ) STORED,
  full_name_mr           text GENERATED ALWAYS AS (
                           btrim(coalesce(last_name_mr, '') || ' ' || coalesce(first_name_mr, '') || ' ' || coalesce(middle_name_mr, ''))
                         ) STORED,
  search_text            text GENERATED ALWAYS AS (
                           lower(coalesce(last_name_en, '') || ' ' || coalesce(first_name_en, '') || ' ' || coalesce(middle_name_en, '') || ' ' ||
                                 coalesce(last_name_mr, '') || ' ' || coalesce(first_name_mr, '') || ' ' || coalesce(middle_name_mr, '') || ' ' ||
                                 coalesce(epic_no, '') || ' ' || coalesce(house_no, ''))
                         ) STORED,
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now(),
  deleted_at             timestamptz,
  sync_xid               xid8   NOT NULL DEFAULT '0',
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, local_body_id)         REFERENCES app.geo_units (tenant_id, id),
  FOREIGN KEY (tenant_id, ward_id)               REFERENCES app.geo_units (tenant_id, id),
  FOREIGN KEY (tenant_id, booth_id)              REFERENCES app.geo_units (tenant_id, id),
  FOREIGN KEY (tenant_id, section_id)            REFERENCES app.geo_units (tenant_id, id),
  FOREIGN KEY (tenant_id, photo_file_id)         REFERENCES app.files (tenant_id, id),
  FOREIGN KEY (tenant_id, first_roll_version_id) REFERENCES app.roll_versions (tenant_id, id),
  FOREIGN KEY (tenant_id, last_roll_version_id)  REFERENCES app.roll_versions (tenant_id, id),
  CHECK (deletion_reason IS NULL OR roll_status = 'deleted_in_roll'),
  CHECK (coalesce(first_name_mr, last_name_mr, first_name_en, last_name_en) IS NOT NULL)
);
COMMENT ON COLUMN app.voters.id IS 'Immutable internal voter id. Roll updates match onto it; it is never overwritten.';
COMMENT ON COLUMN app.voters.roll_status IS 'absent_from_current_roll is NEVER treated as dead.';

CREATE UNIQUE INDEX voters_booth_serial_uq ON app.voters (tenant_id, booth_id, serial_no)
  WHERE roll_status = 'active' AND deleted_at IS NULL;
CREATE UNIQUE INDEX voters_epic_uq ON app.voters (tenant_id, epic_no)
  WHERE epic_no IS NOT NULL AND deleted_at IS NULL;
CREATE INDEX voters_ward_idx      ON app.voters (tenant_id, ward_id, booth_id, serial_no);
CREATE INDEX voters_house_idx     ON app.voters (tenant_id, booth_id, house_no);
CREATE INDEX voters_geo_gist      ON app.voters USING gist (geo_path);
CREATE INDEX voters_search_trgm   ON app.voters USING gin (search_text gin_trgm_ops);
CREATE INDEX voters_last_name_idx ON app.voters (tenant_id, last_name_en);
CREATE INDEX voters_age_idx       ON app.voters (tenant_id, age);
CREATE INDEX voters_sync_idx      ON app.voters (tenant_id, sync_xid);
CREATE INDEX voters_legacy_idx    ON app.voters (tenant_id, legacy_id) WHERE legacy_id IS NOT NULL;

-- Keep geo_path in step with the booth, check the ward and local body match the booth,
-- and forbid changing the internal id.
CREATE FUNCTION app.voters_check_geo() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE b_path ltree; b_level app.geo_level;
BEGIN
  IF TG_OP = 'UPDATE' AND NEW.id <> OLD.id THEN
    RAISE EXCEPTION 'voters.id is immutable';
  END IF;
  IF TG_OP = 'INSERT' OR NEW.booth_id IS DISTINCT FROM OLD.booth_id
     OR NEW.ward_id IS DISTINCT FROM OLD.ward_id OR NEW.local_body_id IS DISTINCT FROM OLD.local_body_id THEN
    SELECT path, level INTO b_path, b_level FROM app.geo_units
      WHERE tenant_id = NEW.tenant_id AND id = NEW.booth_id;
    IF b_level IS DISTINCT FROM 'booth' THEN
      RAISE EXCEPTION 'voters.booth_id must point to a booth';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM app.geo_units g WHERE g.tenant_id = NEW.tenant_id AND g.id = NEW.ward_id
                   AND g.level = 'ward' AND g.path @> b_path) THEN
      RAISE EXCEPTION 'voters.ward_id is not the ward of this booth';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM app.geo_units g WHERE g.tenant_id = NEW.tenant_id AND g.id = NEW.local_body_id
                   AND g.level = 'local_body' AND g.path @> b_path) THEN
      RAISE EXCEPTION 'voters.local_body_id is not the local body of this booth';
    END IF;
    NEW.geo_path := b_path;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER voters_geo BEFORE INSERT OR UPDATE ON app.voters
  FOR EACH ROW EXECUTE FUNCTION app.voters_check_geo();

-- Households. Start from the roll grouping; workers create, split, move and merge.
CREATE TABLE app.families (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      uuid NOT NULL REFERENCES app.tenants(id),
  ward_id        uuid NOT NULL,
  booth_id       uuid,
  house_no       text,
  label          text,
  head_voter_id  uuid,
  source         text NOT NULL DEFAULT 'manual' CHECK (source IN ('roll_import', 'manual', 'name_suggestion')),
  legacy_family_key text,                                -- old app familyid (an EPIC)
  created_by     uuid,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  deleted_at     timestamptz,
  sync_xid       xid8   NOT NULL DEFAULT '0',
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, ward_id)       REFERENCES app.geo_units (tenant_id, id),
  FOREIGN KEY (tenant_id, booth_id)      REFERENCES app.geo_units (tenant_id, id),
  FOREIGN KEY (tenant_id, head_voter_id) REFERENCES app.voters (tenant_id, id),
  FOREIGN KEY (tenant_id, created_by)    REFERENCES app.users (tenant_id, id)
);
CREATE INDEX families_house_idx ON app.families (tenant_id, booth_id, house_no) WHERE deleted_at IS NULL;
CREATE INDEX families_sync_idx ON app.families (tenant_id, sync_xid);
CREATE UNIQUE INDEX families_legacy_uq ON app.families (tenant_id, legacy_family_key) WHERE legacy_family_key IS NOT NULL;

-- -----------------------------------------------------------------------------
-- 8. Campaign data (kept apart from the official roll)
-- -----------------------------------------------------------------------------
CREATE TABLE app.voter_surveys (
  voter_id               uuid PRIMARY KEY,
  tenant_id              uuid NOT NULL REFERENCES app.tenants(id),
  family_id              uuid,
  mobile_1               app.mobile_no,
  mobile_2               app.mobile_no,
  email                  citext CHECK (email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'),
  dob                    date CHECK (dob BETWEEN DATE '1900-01-01' AND DATE '2100-01-01'),
  caste_id               uuid,
  profession_id          uuid,
  society                text,
  flat_no                text,
  has_new_address        boolean NOT NULL DEFAULT false,
  new_address_mr         text,
  new_address_en         text,
  demands                text,
  notes                  text CHECK (length(notes) <= 2000),       -- free notes about the voter, shared with the team
  color_tag_id           uuid,
  is_important           boolean NOT NULL DEFAULT false,
  is_influencer          boolean NOT NULL DEFAULT false,
  karyakarta_id          uuid,
  dead_marked            boolean NOT NULL DEFAULT false,              -- by a worker; never set by roll updates
  dead_marked_by         uuid,
  dead_marked_at         timestamptz,
  dead_confirmed_by      uuid,                                        -- supervisor confirmation
  dead_confirmed_at      timestamptz,
  last_visit_outcome     app.visit_outcome,
  last_visit_at          timestamptz,
  last_visited_by        uuid,
  extra_check_1          boolean,
  extra_check_2          boolean,
  extra_info_1           text,
  extra_info_2           text,
  extra_info_3           text,
  extra_info_4           text,
  extra_info_5           text,
  lat                    numeric(9,6) CHECK (lat BETWEEN -90 AND 90),
  lng                    numeric(9,6) CHECK (lng BETWEEN -180 AND 180),
  location_accuracy_m    real CHECK (location_accuracy_m >= 0),
  location_captured_at   timestamptz,
  is_surveyed            boolean NOT NULL DEFAULT false,
  surveyed_at            timestamptz,
  version                int NOT NULL DEFAULT 1,                      -- optimistic lock for offline edits
  updated_by             uuid,
  updated_device_id      uuid,
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now(),
  sync_xid               xid8   NOT NULL DEFAULT '0',
  FOREIGN KEY (tenant_id, voter_id)          REFERENCES app.voters (tenant_id, id),
  FOREIGN KEY (tenant_id, family_id)         REFERENCES app.families (tenant_id, id),
  FOREIGN KEY (tenant_id, caste_id)          REFERENCES app.castes (tenant_id, id),
  FOREIGN KEY (tenant_id, profession_id)     REFERENCES app.professions (tenant_id, id),
  FOREIGN KEY (tenant_id, color_tag_id)      REFERENCES app.color_tags (tenant_id, id),
  FOREIGN KEY (tenant_id, karyakarta_id)     REFERENCES app.karyakartas (tenant_id, id),
  FOREIGN KEY (tenant_id, dead_marked_by)    REFERENCES app.users (tenant_id, id),
  FOREIGN KEY (tenant_id, dead_confirmed_by) REFERENCES app.users (tenant_id, id),
  FOREIGN KEY (tenant_id, last_visited_by)   REFERENCES app.users (tenant_id, id),
  FOREIGN KEY (tenant_id, updated_by)        REFERENCES app.users (tenant_id, id),
  FOREIGN KEY (tenant_id, updated_device_id) REFERENCES app.devices (tenant_id, id),
  CHECK ((lat IS NULL) = (lng IS NULL)),
  CHECK (dead_confirmed_at IS NULL OR dead_marked),
  CHECK (mobile_2 IS NULL OR mobile_1 IS NOT NULL)
);
CREATE INDEX vs_family_idx      ON app.voter_surveys (tenant_id, family_id);
CREATE INDEX vs_color_idx       ON app.voter_surveys (tenant_id, color_tag_id);
CREATE INDEX vs_karyakarta_idx  ON app.voter_surveys (tenant_id, karyakarta_id);
CREATE INDEX vs_caste_idx       ON app.voter_surveys (tenant_id, caste_id);
CREATE INDEX vs_profession_idx  ON app.voter_surveys (tenant_id, profession_id);
CREATE INDEX vs_mobile_idx      ON app.voter_surveys (tenant_id, mobile_1) WHERE mobile_1 IS NOT NULL;
CREATE INDEX vs_birthday_idx    ON app.voter_surveys (tenant_id, (extract(month FROM dob)), (extract(day FROM dob))) WHERE dob IS NOT NULL;
CREATE INDEX vs_important_idx   ON app.voter_surveys (tenant_id) WHERE is_important;
CREATE INDEX vs_influencer_idx  ON app.voter_surveys (tenant_id) WHERE is_influencer;
CREATE INDEX vs_dead_idx        ON app.voter_surveys (tenant_id) WHERE dead_marked;
CREATE INDEX vs_sync_idx        ON app.voter_surveys (tenant_id, sync_xid);

-- "Fix spelling" requests for machine-transliterated English names
CREATE TABLE app.voter_name_corrections (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES app.tenants(id),
  voter_id      uuid NOT NULL,
  first_name_en text,
  middle_name_en text,
  last_name_en  text,
  status        app.review_status NOT NULL DEFAULT 'pending',
  requested_by  uuid NOT NULL,
  requested_at  timestamptz NOT NULL DEFAULT now(),
  reviewed_by   uuid,
  reviewed_at   timestamptz,
  updated_at    timestamptz NOT NULL DEFAULT now(),
  sync_xid      xid8   NOT NULL DEFAULT '0',
  FOREIGN KEY (tenant_id, voter_id)     REFERENCES app.voters (tenant_id, id),
  FOREIGN KEY (tenant_id, requested_by) REFERENCES app.users (tenant_id, id),
  FOREIGN KEY (tenant_id, reviewed_by)  REFERENCES app.users (tenant_id, id),
  CHECK (coalesce(first_name_en, middle_name_en, last_name_en) IS NOT NULL)
);
CREATE INDEX vnc_status_idx ON app.voter_name_corrections (tenant_id, status);

-- Door-to-door visits. Also the source for "Worker locations" (location only saved with a visit or survey).
CREATE TABLE app.visits (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           uuid NOT NULL REFERENCES app.tenants(id),
  booth_id            uuid NOT NULL,
  house_no            text,
  family_id           uuid,
  voter_id            uuid,
  outcome             app.visit_outcome NOT NULL,
  revisit_at          timestamptz,
  note                text,
  lat                 numeric(9,6) CHECK (lat BETWEEN -90 AND 90),
  lng                 numeric(9,6) CHECK (lng BETWEEN -180 AND 180),
  accuracy_m          real CHECK (accuracy_m >= 0),
  visited_by          uuid NOT NULL,
  device_id           uuid,
  visited_at          timestamptz NOT NULL,
  client_mutation_id  uuid NOT NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  deleted_at          timestamptz,
  sync_xid            xid8   NOT NULL DEFAULT '0',
  UNIQUE (tenant_id, client_mutation_id),
  FOREIGN KEY (tenant_id, booth_id)   REFERENCES app.geo_units (tenant_id, id),
  FOREIGN KEY (tenant_id, family_id)  REFERENCES app.families (tenant_id, id),
  FOREIGN KEY (tenant_id, voter_id)   REFERENCES app.voters (tenant_id, id),
  FOREIGN KEY (tenant_id, visited_by) REFERENCES app.users (tenant_id, id),
  FOREIGN KEY (tenant_id, device_id)  REFERENCES app.devices (tenant_id, id),
  CHECK ((lat IS NULL) = (lng IS NULL)),
  CHECK (house_no IS NOT NULL OR family_id IS NOT NULL OR voter_id IS NOT NULL)
);
CREATE INDEX visits_house_idx  ON app.visits (tenant_id, booth_id, house_no, visited_at DESC);
CREATE INDEX visits_worker_idx ON app.visits (tenant_id, visited_by, visited_at DESC);
CREATE INDEX visits_revisit_idx ON app.visits (tenant_id, revisit_at) WHERE outcome = 'revisit' AND deleted_at IS NULL;
CREATE INDEX visits_sync_idx   ON app.visits (tenant_id, sync_xid);

-- Polling day: who has voted (turnout only, never who they voted for)
CREATE TABLE app.voter_turnout (
  voter_id            uuid PRIMARY KEY,
  tenant_id           uuid NOT NULL REFERENCES app.tenants(id),
  is_voted            boolean NOT NULL DEFAULT true,
  marked_by           uuid NOT NULL,
  marked_at           timestamptz NOT NULL DEFAULT now(),
  device_id           uuid,
  source              app.turnout_source NOT NULL DEFAULT 'single',
  client_mutation_id  uuid,
  cleared_by          uuid,
  cleared_at          timestamptz,
  updated_at          timestamptz NOT NULL DEFAULT now(),
  sync_xid            xid8   NOT NULL DEFAULT '0',
  FOREIGN KEY (tenant_id, voter_id)   REFERENCES app.voters (tenant_id, id),
  FOREIGN KEY (tenant_id, marked_by)  REFERENCES app.users (tenant_id, id),
  FOREIGN KEY (tenant_id, cleared_by) REFERENCES app.users (tenant_id, id),
  FOREIGN KEY (tenant_id, device_id)  REFERENCES app.devices (tenant_id, id),
  CHECK (is_voted OR cleared_at IS NOT NULL)
);
CREATE INDEX turnout_time_idx ON app.voter_turnout (tenant_id, marked_at) WHERE is_voted;
CREATE INDEX turnout_by_idx   ON app.voter_turnout (tenant_id, marked_by) WHERE is_voted;
CREATE INDEX turnout_sync_idx ON app.voter_turnout (tenant_id, sync_xid);
CREATE UNIQUE INDEX turnout_mutation_uq ON app.voter_turnout (tenant_id, client_mutation_id) WHERE client_mutation_id IS NOT NULL;

-- Every slip printed or shared ("Slip printed", "Printed by")
CREATE TABLE app.slip_events (
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id           uuid NOT NULL REFERENCES app.tenants(id),
  voter_id            uuid NOT NULL,
  channel             app.slip_channel NOT NULL,
  created_by          uuid NOT NULL,
  device_id           uuid,
  created_at          timestamptz NOT NULL DEFAULT now(),
  client_mutation_id  uuid,
  FOREIGN KEY (tenant_id, voter_id)   REFERENCES app.voters (tenant_id, id),
  FOREIGN KEY (tenant_id, created_by) REFERENCES app.users (tenant_id, id),
  FOREIGN KEY (tenant_id, device_id)  REFERENCES app.devices (tenant_id, id)
);
CREATE INDEX slip_events_voter_idx ON app.slip_events (tenant_id, voter_id, created_at DESC);
CREATE INDEX slip_events_by_idx    ON app.slip_events (tenant_id, created_by, created_at DESC);
CREATE UNIQUE INDEX slip_events_mutation_uq ON app.slip_events (tenant_id, client_mutation_id) WHERE client_mutation_id IS NOT NULL;

-- People not on the roll yet (e.g. turning 18)
CREATE TABLE app.new_voters (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           uuid NOT NULL REFERENCES app.tenants(id),
  full_name_en        text,
  full_name_mr        text,
  relative_name       text,
  dob                 date,
  gender              app.gender,
  mobile              app.mobile_no,
  address             text,
  ward_id             uuid NOT NULL,
  booth_id            uuid,
  family_id           uuid,
  form6_status        app.form6_status NOT NULL DEFAULT 'not_applied',
  notes               text,
  matched_voter_id    uuid,                         -- set when the person appears in a new roll
  matched_at          timestamptz,
  created_by          uuid NOT NULL,
  device_id           uuid,
  client_mutation_id  uuid,
  version             int NOT NULL DEFAULT 1,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  deleted_at          timestamptz,
  sync_xid            xid8   NOT NULL DEFAULT '0',
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, ward_id)          REFERENCES app.geo_units (tenant_id, id),
  FOREIGN KEY (tenant_id, booth_id)         REFERENCES app.geo_units (tenant_id, id),
  FOREIGN KEY (tenant_id, family_id)        REFERENCES app.families (tenant_id, id),
  FOREIGN KEY (tenant_id, matched_voter_id) REFERENCES app.voters (tenant_id, id),
  FOREIGN KEY (tenant_id, created_by)       REFERENCES app.users (tenant_id, id),
  FOREIGN KEY (tenant_id, device_id)        REFERENCES app.devices (tenant_id, id),
  CHECK (coalesce(full_name_en, full_name_mr) IS NOT NULL)
);
CREATE INDEX new_voters_ward_idx ON app.new_voters (tenant_id, ward_id) WHERE deleted_at IS NULL;
CREATE INDEX new_voters_sync_idx ON app.new_voters (tenant_id, sync_xid);
CREATE UNIQUE INDEX new_voters_mutation_uq ON app.new_voters (tenant_id, client_mutation_id) WHERE client_mutation_id IS NOT NULL;

-- -----------------------------------------------------------------------------
-- 9. Roll import, matching and repeated voters
-- -----------------------------------------------------------------------------
CREATE TABLE app.roll_import_rows (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id          uuid NOT NULL REFERENCES app.tenants(id),
  roll_version_id    uuid NOT NULL,
  row_no             int NOT NULL,
  raw                jsonb NOT NULL,
  part_no            int,
  booth_code         text,
  serial_no          int,
  epic_no            text,
  first_name_mr      text,
  middle_name_mr     text,
  last_name_mr       text,
  first_name_en      text,
  middle_name_en     text,
  last_name_en       text,
  relative_name_mr   text,
  gender             app.gender,
  age                smallint,
  house_no           text,
  address_mr         text,
  assembly_mapping   text,
  deletion_reason    text,
  is_repeated        boolean,
  match_status       app.match_status,
  matched_voter_id   uuid,
  similarity         numeric(4,3) CHECK (similarity BETWEEN 0 AND 1),
  match_notes        text,
  review_status      app.review_status NOT NULL DEFAULT 'pending',
  reviewed_by        uuid,
  reviewed_at        timestamptz,
  created_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, roll_version_id, row_no),
  FOREIGN KEY (tenant_id, roll_version_id)  REFERENCES app.roll_versions (tenant_id, id),
  FOREIGN KEY (tenant_id, matched_voter_id) REFERENCES app.voters (tenant_id, id),
  FOREIGN KEY (tenant_id, reviewed_by)      REFERENCES app.users (tenant_id, id)
);
CREATE INDEX rir_status_idx ON app.roll_import_rows (tenant_id, roll_version_id, match_status, review_status);

-- Same person listed twice ("Repeated voters", "Possible duplicates")
CREATE TABLE app.voter_duplicate_pairs (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES app.tenants(id),
  voter_a_id    uuid NOT NULL,
  voter_b_id    uuid NOT NULL,
  source        text NOT NULL CHECK (source IN ('roll_flag', 'fuzzy_match', 'roll_update')),
  similarity    numeric(4,3) CHECK (similarity BETWEEN 0 AND 1),
  status        app.pair_status NOT NULL DEFAULT 'unchecked',
  reviewed_by   uuid,
  reviewed_at   timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  sync_xid      xid8   NOT NULL DEFAULT '0',
  UNIQUE (tenant_id, voter_a_id, voter_b_id),
  FOREIGN KEY (tenant_id, voter_a_id)  REFERENCES app.voters (tenant_id, id),
  FOREIGN KEY (tenant_id, voter_b_id)  REFERENCES app.voters (tenant_id, id),
  FOREIGN KEY (tenant_id, reviewed_by) REFERENCES app.users (tenant_id, id),
  CHECK (voter_a_id < voter_b_id)
);
CREATE INDEX vdp_b_idx      ON app.voter_duplicate_pairs (tenant_id, voter_b_id);
CREATE INDEX vdp_status_idx ON app.voter_duplicate_pairs (tenant_id, status);

-- Pairs where both entries are marked voted (polling-day warning)
CREATE VIEW app.voted_twice WITH (security_invoker = true) AS
SELECT p.tenant_id, p.id AS pair_id, p.voter_a_id, p.voter_b_id,
       ta.marked_at AS a_marked_at, ta.marked_by AS a_marked_by,
       tb.marked_at AS b_marked_at, tb.marked_by AS b_marked_by
FROM app.voter_duplicate_pairs p
JOIN app.voter_turnout ta ON ta.tenant_id = p.tenant_id AND ta.voter_id = p.voter_a_id AND ta.is_voted
JOIN app.voter_turnout tb ON tb.tenant_id = p.tenant_id AND tb.voter_id = p.voter_b_id AND tb.is_voted
WHERE p.status <> 'different_people';

-- One-voter roll changes made by an admin (add by hand, correct, remove, restore).
-- Removing hides the voter (roll_status = deleted_in_roll); nothing is erased.
CREATE TABLE app.voter_roll_edits (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id      uuid NOT NULL REFERENCES app.tenants(id),
  voter_id       uuid NOT NULL,
  action         app.roll_edit_action NOT NULL,
  reason         text NOT NULL CHECK (reason IN ('supplementary_list', 'typing_mistake', 'booth_changed',
                                                  'shifted', 'duplicate', 'deleted_in_new_roll', 'dead', 'other')),
  reference      text,                      -- list no. / date
  old_values     jsonb,
  new_values     jsonb,
  edited_by      uuid NOT NULL,
  device_id      uuid,
  edited_at      timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, voter_id)  REFERENCES app.voters (tenant_id, id),
  FOREIGN KEY (tenant_id, edited_by) REFERENCES app.users (tenant_id, id),
  FOREIGN KEY (tenant_id, device_id) REFERENCES app.devices (tenant_id, id)
);
CREATE INDEX vre_voter_idx ON app.voter_roll_edits (tenant_id, voter_id, edited_at DESC);

-- "Report a problem" from Help & support
CREATE TABLE app.problem_reports (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          uuid NOT NULL REFERENCES app.tenants(id),
  user_id            uuid NOT NULL,
  device_id          uuid,
  body               text NOT NULL CHECK (length(body) BETWEEN 1 AND 2000),
  app_version_code   int,
  phone_model        text,
  status             text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done')),
  handled_by         uuid,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, user_id)    REFERENCES app.users (tenant_id, id),
  FOREIGN KEY (tenant_id, device_id)  REFERENCES app.devices (tenant_id, id),
  FOREIGN KEY (tenant_id, handled_by) REFERENCES app.users (tenant_id, id)
);
CREATE INDEX problem_reports_open_idx ON app.problem_reports (tenant_id, created_at DESC) WHERE status = 'open';

-- -----------------------------------------------------------------------------
-- 10. Sync
-- -----------------------------------------------------------------------------
-- Idempotency: a phone retrying the same push gets the same result
CREATE TABLE app.sync_mutations (
  tenant_id           uuid NOT NULL REFERENCES app.tenants(id),
  device_id           uuid NOT NULL,
  client_mutation_id  uuid NOT NULL,
  entity_type         text NOT NULL,
  entity_id           uuid,
  operation           text NOT NULL CHECK (operation IN ('insert', 'update', 'delete')),
  base_version        int,
  status              text NOT NULL CHECK (status IN ('applied', 'conflict', 'rejected')),
  error               text,
  received_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, device_id, client_mutation_id),
  FOREIGN KEY (tenant_id, device_id) REFERENCES app.devices (tenant_id, id)
);
CREATE INDEX sync_mutations_time_idx ON app.sync_mutations (tenant_id, received_at);

-- "Needs your decision": field-level conflicts, never overwritten silently
CREATE TABLE app.sync_conflicts (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          uuid NOT NULL REFERENCES app.tenants(id),
  entity_type        text NOT NULL CHECK (entity_type IN ('voter_survey', 'new_voter', 'family')),
  entity_id          uuid NOT NULL,
  field_name         text NOT NULL,
  client_value       jsonb,
  server_value       jsonb,
  client_user_id     uuid NOT NULL,
  client_device_id   uuid,
  client_changed_at  timestamptz,
  server_user_id     uuid,
  server_changed_at  timestamptz,
  status             app.conflict_status NOT NULL DEFAULT 'open',
  resolved_by        uuid,
  resolved_at        timestamptz,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  sync_xid           xid8   NOT NULL DEFAULT '0',
  FOREIGN KEY (tenant_id, client_user_id)   REFERENCES app.users (tenant_id, id),
  FOREIGN KEY (tenant_id, client_device_id) REFERENCES app.devices (tenant_id, id),
  FOREIGN KEY (tenant_id, server_user_id)   REFERENCES app.users (tenant_id, id),
  FOREIGN KEY (tenant_id, resolved_by)      REFERENCES app.users (tenant_id, id),
  CHECK ((status = 'open') = (resolved_at IS NULL))
);
CREATE INDEX sync_conflicts_open_idx ON app.sync_conflicts (tenant_id, client_user_id) WHERE status = 'open';

-- -----------------------------------------------------------------------------
-- 11. Team communication, templates, saved filters
-- -----------------------------------------------------------------------------
CREATE TABLE app.announcements (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES app.tenants(id),
  body          text NOT NULL CHECK (length(body) BETWEEN 1 AND 2000),
  audience_geo_id uuid,                       -- NULL = all workers
  created_by    uuid NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz,
  updated_at    timestamptz NOT NULL DEFAULT now(),
  deleted_at    timestamptz,
  sync_xid      xid8   NOT NULL DEFAULT '0',
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, audience_geo_id) REFERENCES app.geo_units (tenant_id, id),
  FOREIGN KEY (tenant_id, created_by)      REFERENCES app.users (tenant_id, id)
);
CREATE INDEX announcements_time_idx ON app.announcements (tenant_id, created_at DESC) WHERE deleted_at IS NULL;

CREATE TABLE app.announcement_reads (
  tenant_id        uuid NOT NULL REFERENCES app.tenants(id),
  announcement_id  uuid NOT NULL,
  user_id          uuid NOT NULL,
  read_at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, announcement_id, user_id),
  FOREIGN KEY (tenant_id, announcement_id) REFERENCES app.announcements (tenant_id, id),
  FOREIGN KEY (tenant_id, user_id)         REFERENCES app.users (tenant_id, id)
);

CREATE TABLE app.message_templates (
  tenant_id    uuid NOT NULL REFERENCES app.tenants(id),
  kind         text NOT NULL CHECK (kind IN ('birthday', 'slip_whatsapp', 'slip_sms', 'general')),
  body_mr      text,
  body_en      text,
  body_hi      text,
  updated_by   uuid,
  updated_at   timestamptz NOT NULL DEFAULT now(),
  sync_xid     xid8   NOT NULL DEFAULT '0',
  PRIMARY KEY (tenant_id, kind),
  FOREIGN KEY (tenant_id, updated_by) REFERENCES app.users (tenant_id, id)
);

CREATE TABLE app.saved_filters (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES app.tenants(id),
  user_id      uuid,                          -- NULL = shared by an admin with everyone
  name         text NOT NULL,
  filter       jsonb NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  deleted_at   timestamptz,
  sync_xid     xid8   NOT NULL DEFAULT '0',
  FOREIGN KEY (tenant_id, user_id) REFERENCES app.users (tenant_id, id)
);
CREATE UNIQUE INDEX saved_filters_name_uq ON app.saved_filters
  (tenant_id, coalesce(user_id, '00000000-0000-0000-0000-000000000000'::uuid), name) WHERE deleted_at IS NULL;

-- -----------------------------------------------------------------------------
-- 12. Mobile number import, exports, daily reports
-- -----------------------------------------------------------------------------
CREATE TABLE app.mobile_import_batches (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES app.tenants(id),
  source           text NOT NULL CHECK (source IN ('file', 'phone_contacts')),
  file_id          uuid,
  status           app.job_status NOT NULL DEFAULT 'queued',
  matched_count    int NOT NULL DEFAULT 0,
  review_count     int NOT NULL DEFAULT 0,
  not_found_count  int NOT NULL DEFAULT 0,
  created_by       uuid NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  finished_at      timestamptz,
  error            text,
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, file_id)    REFERENCES app.files (tenant_id, id),
  FOREIGN KEY (tenant_id, created_by) REFERENCES app.users (tenant_id, id),
  CHECK (source = 'phone_contacts' OR file_id IS NOT NULL)
);

CREATE TABLE app.mobile_import_rows (
  id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id            uuid NOT NULL REFERENCES app.tenants(id),
  batch_id             uuid NOT NULL,
  row_no               int NOT NULL,
  name                 text,
  mobile               text NOT NULL,
  address_text         text,
  status               app.mobile_match_status NOT NULL,
  matched_voter_id     uuid,
  candidate_voter_ids  uuid[] NOT NULL DEFAULT '{}',
  reviewed_by          uuid,
  reviewed_at          timestamptz,
  UNIQUE (tenant_id, batch_id, row_no),
  FOREIGN KEY (tenant_id, batch_id)         REFERENCES app.mobile_import_batches (tenant_id, id),
  FOREIGN KEY (tenant_id, matched_voter_id) REFERENCES app.voters (tenant_id, id),
  FOREIGN KEY (tenant_id, reviewed_by)      REFERENCES app.users (tenant_id, id)
);
CREATE INDEX mir_status_idx ON app.mobile_import_rows (tenant_id, batch_id, status);

CREATE TABLE app.exports (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES app.tenants(id),
  kind         text NOT NULL CHECK (kind IN ('voter_list', 'report', 'turnout', 'mobile_list')),
  format       text NOT NULL CHECK (format IN ('pdf', 'xlsx')),
  language     app.lang NOT NULL DEFAULT 'mr',
  filter       jsonb NOT NULL DEFAULT '{}'::jsonb,
  columns      text[] NOT NULL DEFAULT '{}',
  options      jsonb NOT NULL DEFAULT '{}'::jsonb,       -- paper, text size, group by house, header
  status       app.job_status NOT NULL DEFAULT 'queued',
  file_id      uuid,
  row_count    int,
  page_count   int,
  error        text,
  created_by   uuid NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  finished_at  timestamptz,
  FOREIGN KEY (tenant_id, file_id)    REFERENCES app.files (tenant_id, id),
  FOREIGN KEY (tenant_id, created_by) REFERENCES app.users (tenant_id, id)
);
CREATE INDEX exports_user_idx ON app.exports (tenant_id, created_by, created_at DESC);

-- Nightly snapshot per booth (the old app's daily_report), for "compare any two days"
CREATE TABLE app.daily_booth_stats (
  tenant_id        uuid NOT NULL REFERENCES app.tenants(id),
  report_date      date NOT NULL,
  booth_id         uuid NOT NULL,
  ward_id          uuid NOT NULL,
  total_voters     int NOT NULL DEFAULT 0,
  surveyed         int NOT NULL DEFAULT 0,
  mobile_1         int NOT NULL DEFAULT 0,
  mobile_2         int NOT NULL DEFAULT 0,
  dob              int NOT NULL DEFAULT 0,
  email            int NOT NULL DEFAULT 0,
  caste            int NOT NULL DEFAULT 0,
  profession       int NOT NULL DEFAULT 0,
  demands          int NOT NULL DEFAULT 0,
  society          int NOT NULL DEFAULT 0,
  new_address      int NOT NULL DEFAULT 0,
  color_tagged     int NOT NULL DEFAULT 0,
  important        int NOT NULL DEFAULT 0,
  influencers      int NOT NULL DEFAULT 0,
  karyakarta_assigned int NOT NULL DEFAULT 0,
  dead_marked      int NOT NULL DEFAULT 0,
  slip_printed     int NOT NULL DEFAULT 0,
  voted            int NOT NULL DEFAULT 0,
  custom_fields    int NOT NULL DEFAULT 0,
  visits           int NOT NULL DEFAULT 0,
  by_color         jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {"green": 120, ...}
  generated_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, report_date, booth_id),
  FOREIGN KEY (tenant_id, booth_id) REFERENCES app.geo_units (tenant_id, id),
  FOREIGN KEY (tenant_id, ward_id)  REFERENCES app.geo_units (tenant_id, id)
);

-- -----------------------------------------------------------------------------
-- 13. Activity log (append-only)
-- -----------------------------------------------------------------------------
CREATE TABLE app.audit_log (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id      uuid NOT NULL REFERENCES app.tenants(id),
  occurred_at    timestamptz NOT NULL DEFAULT now(),
  actor_user_id  uuid,
  device_id      uuid,
  action         text NOT NULL,           -- insert / update / delete, or an API action such as login, export
  entity_type    text NOT NULL,
  entity_id      text,
  old_values     jsonb,
  new_values     jsonb,
  ip             inet
);
CREATE INDEX audit_time_idx   ON app.audit_log (tenant_id, occurred_at DESC);
CREATE INDEX audit_entity_idx ON app.audit_log (tenant_id, entity_type, entity_id);
CREATE INDEX audit_actor_idx  ON app.audit_log (tenant_id, actor_user_id, occurred_at DESC);

CREATE FUNCTION app.audit_log_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit_log is append-only';
END $$;
CREATE TRIGGER audit_log_no_update BEFORE UPDATE OR DELETE ON app.audit_log
  FOR EACH ROW EXECUTE FUNCTION app.audit_log_immutable();

-- Generic change recorder. Stores only the columns that changed.
-- Bulk roll imports by jansetu_owner may skip it with SET LOCAL app.skip_audit = 'on'.
CREATE FUNCTION app.audit_changes() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  o jsonb; n jsonb; changed_old jsonb; changed_new jsonb; ent_id text;
BEGIN
  IF current_setting('app.skip_audit', true) = 'on'
     AND pg_has_role(current_user, 'jansetu_owner', 'MEMBER') THEN
    RETURN NULL;
  END IF;
  o := CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN to_jsonb(OLD) END;
  n := CASE WHEN TG_OP IN ('UPDATE', 'INSERT') THEN to_jsonb(NEW) END;
  IF TG_OP = 'UPDATE' THEN
    SELECT jsonb_object_agg(k, o -> k), jsonb_object_agg(k, n -> k)
      INTO changed_old, changed_new
      FROM jsonb_object_keys(n) AS k
     WHERE (o -> k) IS DISTINCT FROM (n -> k)
       AND k NOT IN ('updated_at', 'sync_xid', 'version', 'search_text', 'full_name_en', 'full_name_mr');
    IF changed_new IS NULL THEN RETURN NULL; END IF;
  ELSE
    changed_old := o; changed_new := n;
  END IF;
  ent_id := coalesce(n ->> 'id', o ->> 'id', n ->> 'voter_id', o ->> 'voter_id',
                     n ->> 'user_id', o ->> 'user_id', n ->> 'field_key', o ->> 'field_key',
                     n ->> 'kind', o ->> 'kind', n ->> 'tenant_id', o ->> 'tenant_id');
  INSERT INTO app.audit_log (tenant_id, actor_user_id, device_id, action, entity_type, entity_id, old_values, new_values)
  VALUES (coalesce((n ->> 'tenant_id')::uuid, (o ->> 'tenant_id')::uuid),
          app.current_user_id(), app.current_device_id(),
          lower(TG_OP), TG_TABLE_NAME, ent_id, changed_old, changed_new);
  RETURN NULL;
END $$;

-- -----------------------------------------------------------------------------
-- 14. Global: app releases (APK from our own server) and terms
-- -----------------------------------------------------------------------------
CREATE TABLE app.app_releases (
  version_code       int PRIMARY KEY CHECK (version_code > 0),
  version_name       text NOT NULL,
  apk_path           text NOT NULL,          -- served by Nginx from the KVM 4 server
  apk_sha256         char(64) NOT NULL CHECK (apk_sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes         bigint NOT NULL,
  is_required        boolean NOT NULL DEFAULT false,
  notes_mr           text,
  notes_en           text,
  released_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.terms_versions (
  version        int PRIMARY KEY,
  body_mr        text NOT NULL,
  body_en        text NOT NULL,
  published_at   timestamptz NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- 15. Late foreign keys
-- -----------------------------------------------------------------------------
ALTER TABLE app.tenant_settings ADD FOREIGN KEY (tenant_id, updated_by) REFERENCES app.users (tenant_id, id);
ALTER TABLE app.users ADD FOREIGN KEY (tenant_id, created_by) REFERENCES app.users (tenant_id, id);
ALTER TABLE app.users ADD FOREIGN KEY (terms_version) REFERENCES app.terms_versions (version);

-- -----------------------------------------------------------------------------
-- 16. Triggers: touch_row, version, audit
-- -----------------------------------------------------------------------------
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'tenant_settings', 'geo_units', 'users', 'karyakartas', 'devices',
    'castes', 'professions', 'color_tags', 'custom_field_labels', 'ui_label_overrides',
    'roll_versions', 'roll_part_versions', 'voters', 'families', 'voter_surveys',
    'voter_name_corrections', 'visits', 'voter_turnout', 'new_voters',
    'voter_duplicate_pairs', 'sync_conflicts', 'announcements', 'message_templates', 'saved_filters'
  ] LOOP
    EXECUTE format('CREATE TRIGGER %I BEFORE INSERT OR UPDATE ON app.%I
                    FOR EACH ROW EXECUTE FUNCTION app.touch_row()', t || '_touch', t);
  END LOOP;
END $$;

CREATE TRIGGER tenants_touch BEFORE UPDATE ON app.tenants
  FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
CREATE TRIGGER ui_labels_touch BEFORE UPDATE ON app.ui_labels
  FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();

CREATE TRIGGER voter_surveys_version BEFORE UPDATE ON app.voter_surveys
  FOR EACH ROW EXECUTE FUNCTION app.bump_version();
CREATE TRIGGER new_voters_version BEFORE UPDATE ON app.new_voters
  FOR EACH ROW EXECUTE FUNCTION app.bump_version();

DO $$
DECLARE t text;
BEGIN
  -- full insert/update/delete history
  FOREACH t IN ARRAY ARRAY[
    'tenant_settings', 'users', 'karyakartas', 'devices', 'user_area_assignments',
    'castes', 'professions', 'color_tags', 'custom_field_labels',
    'families', 'voter_surveys', 'voter_name_corrections', 'voter_turnout', 'new_voters',
    'voter_duplicate_pairs', 'sync_conflicts', 'announcements', 'message_templates', 'roll_versions'
  ] LOOP
    EXECUTE format('CREATE TRIGGER %I AFTER INSERT OR UPDATE OR DELETE ON app.%I
                    FOR EACH ROW EXECUTE FUNCTION app.audit_changes()', t || '_audit', t);
  END LOOP;
END $$;
-- voters: full history for the History tab; bulk roll imports by jansetu_owner skip it with app.skip_audit
CREATE TRIGGER voters_audit AFTER INSERT OR UPDATE OR DELETE ON app.voters
  FOR EACH ROW EXECUTE FUNCTION app.audit_changes();

-- -----------------------------------------------------------------------------
-- 17. Row-level security
-- -----------------------------------------------------------------------------
ALTER TABLE app.tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.tenants FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_self ON app.tenants USING (id = app.current_tenant_id());

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'files', 'tenant_settings', 'geo_units', 'users', 'karyakartas', 'user_area_assignments',
    'devices', 'auth_sessions', 'castes', 'professions', 'color_tags', 'custom_field_labels',
    'ui_label_overrides', 'roll_versions', 'roll_part_versions', 'voters', 'families',
    'voter_surveys', 'voter_name_corrections', 'visits', 'voter_turnout', 'slip_events',
    'new_voters', 'roll_import_rows', 'voter_duplicate_pairs', 'sync_mutations', 'sync_conflicts',
    'announcements', 'announcement_reads', 'message_templates', 'saved_filters',
    'mobile_import_batches', 'mobile_import_rows', 'exports', 'daily_booth_stats', 'audit_log',
    'voter_roll_edits', 'problem_reports'
  ] LOOP
    EXECUTE format('ALTER TABLE app.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE app.%I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY tenant_isolation ON app.%I
                    USING (tenant_id = app.current_tenant_id())
                    WITH CHECK (tenant_id = app.current_tenant_id())', t);
  END LOOP;
END $$;

-- -----------------------------------------------------------------------------
-- 18. Login lookup (before a tenant context exists)
-- -----------------------------------------------------------------------------
CREATE FUNCTION app.login_lookup(p_tenant_code text, p_username text)
RETURNS TABLE (user_id uuid, tenant_id uuid, password_hash text, role app.user_role,
               is_active boolean, locked_until timestamptz, must_change_password boolean,
               tenant_status text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, public, pg_temp AS $$
  SELECT u.id, u.tenant_id, u.password_hash, u.role, u.is_active, u.locked_until,
         u.must_change_password, t.status
  FROM app.tenants t
  JOIN app.users u ON u.tenant_id = t.id
  WHERE t.code = p_tenant_code::citext
    AND u.username = p_username::citext
    AND u.deleted_at IS NULL
$$;
REVOKE ALL ON FUNCTION app.login_lookup(text, text) FROM PUBLIC;

-- -----------------------------------------------------------------------------
-- 19. New-tenant defaults (colour tags, custom fields, templates)
-- -----------------------------------------------------------------------------
CREATE FUNCTION app.seed_tenant_defaults(p_tenant uuid) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  -- Run as jansetu_owner when a tenant is created.
  INSERT INTO app.tenant_settings (tenant_id) VALUES (p_tenant) ON CONFLICT DO NOTHING;

  -- Labels as used in the old app; admins can rename them in "Lists & labels"
  INSERT INTO app.color_tags (tenant_id, code, hex, label_mr, label_en, label_hi, is_default, sort_order) VALUES
    (p_tenant, 'green',  '#2E8B57', 'आपले',    'Ours',     'हमारे',   false, 1),
    (p_tenant, 'red',    '#C8382E', 'विरोधी',  'Opposite', 'विरोधी',  false, 2),
    (p_tenant, 'yellow', '#E0B000', 'संदिग्ध', 'Doubtful', 'संदिग्ध', false, 3),
    (p_tenant, 'white',  '#FFFFFF', 'इतर',     'Other',    'इतर',     true,  4)
  ON CONFLICT DO NOTHING;

  INSERT INTO app.custom_field_labels (tenant_id, field_key)
  SELECT p_tenant, k FROM unnest(enum_range(NULL::app.custom_field_key)) AS k
  ON CONFLICT DO NOTHING;

  INSERT INTO app.message_templates (tenant_id, kind, body_mr, body_en) VALUES
    (p_tenant, 'birthday',
     'वाढदिवसाच्या हार्दिक शुभेच्छा, {name}! आपले आयुष्य आनंदी आणि आरोग्यदायी जावो.',
     'Happy birthday, {name}! Wishing you a happy and healthy year.')
  ON CONFLICT DO NOTHING;
END $$;

-- -----------------------------------------------------------------------------
-- 20. Privileges
-- -----------------------------------------------------------------------------
REVOKE ALL ON SCHEMA app FROM PUBLIC;
GRANT USAGE ON SCHEMA app TO jansetu_app;

GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA app TO jansetu_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO jansetu_app;

-- read-only for the API
REVOKE INSERT, UPDATE ON app.tenants, app.app_releases, app.terms_versions, app.ui_labels FROM jansetu_app;
-- not visible to the API at all
REVOKE ALL ON app.platform_admins FROM jansetu_app;
-- append-only
REVOKE UPDATE ON app.audit_log, app.slip_events, app.sync_mutations, app.voter_roll_edits FROM jansetu_app;
-- the only hard deletes the API may do; everything else is soft-deleted
GRANT DELETE ON app.user_area_assignments, app.saved_filters, app.announcement_reads,
                app.auth_sessions, app.ui_label_overrides TO jansetu_app;

GRANT EXECUTE ON FUNCTION app.login_lookup(text, text) TO jansetu_app;
GRANT EXECUTE ON FUNCTION app.set_context(uuid, uuid, uuid) TO jansetu_app;
GRANT EXECUTE ON FUNCTION app.sync_watermark() TO jansetu_app;
REVOKE EXECUTE ON FUNCTION app.seed_tenant_defaults(uuid) FROM PUBLIC;

ALTER DEFAULT PRIVILEGES FOR ROLE jansetu_owner IN SCHEMA app
  GRANT SELECT, INSERT, UPDATE ON TABLES TO jansetu_app;
ALTER DEFAULT PRIVILEGES FOR ROLE jansetu_owner IN SCHEMA app
  GRANT USAGE, SELECT ON SEQUENCES TO jansetu_app;

RESET ROLE;
COMMIT;
