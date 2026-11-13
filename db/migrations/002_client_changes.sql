-- =============================================================================
-- JANSETU – 002: the client's changes of 12 Nov 2026 (SRS version 1.1)
-- All schema changes for that list live in this one file (plan task 5.14).
-- Runs inside migrate.py's transaction (no BEGIN / COMMIT here).
--
--   1. Colour tags: the white "Other" tag is switched off and no longer seeded.
--   2. Lists `positions` (important voters) and `influencer_types`, with placeholder entries.
--   3. Survey: position, influencer type, self help group, ration card.
--   4. Part notes: one shared note per part (= the part's booth), with a version.
--   5. Election settings: polling start and end time (shown on voter slips).
-- =============================================================================

-- Objects belong to jansetu_owner (as in 001), so its default privileges give jansetu_app
-- SELECT / INSERT / UPDATE on the new tables.
SET LOCAL ROLE jansetu_owner;
SET LOCAL search_path = app, public;

-- -----------------------------------------------------------------------------
-- 1. No white colour tag. A voter without a tag simply has none.
--    Kept as an inactive row (old surveys may point at it); new saves refuse it.
-- -----------------------------------------------------------------------------
UPDATE app.color_tags SET is_active = false, is_default = false WHERE code = 'white';

-- -----------------------------------------------------------------------------
-- 2. Positions of important voters, and influencer types. Same shape as castes.
-- -----------------------------------------------------------------------------
CREATE TABLE app.positions (
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
COMMENT ON TABLE app.positions IS 'Position of an important voter (e.g. sarpanch). Placeholder entries until the client sends the list.';

CREATE TABLE app.influencer_types (
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
COMMENT ON TABLE app.influencer_types IS 'Kind of influencer (e.g. religious leader). Placeholder entries until the client sends the list.';

-- -----------------------------------------------------------------------------
-- 3. Survey fields
-- -----------------------------------------------------------------------------
ALTER TABLE app.voter_surveys
  ADD COLUMN position_id          uuid,
  ADD COLUMN influencer_type_id   uuid,
  ADD COLUMN in_self_help_group   boolean NOT NULL DEFAULT false,
  ADD COLUMN self_help_group_name text CHECK (length(self_help_group_name) <= 200),
  ADD COLUMN ration_card          text CHECK (ration_card IN ('AAY', 'PHH', 'NPHH')),
  ADD FOREIGN KEY (tenant_id, position_id)        REFERENCES app.positions (tenant_id, id),
  ADD FOREIGN KEY (tenant_id, influencer_type_id) REFERENCES app.influencer_types (tenant_id, id),
  ADD CHECK (position_id IS NULL OR is_important),
  ADD CHECK (influencer_type_id IS NULL OR is_influencer),
  ADD CHECK (self_help_group_name IS NULL OR in_self_help_group);
COMMENT ON COLUMN app.voter_surveys.ration_card IS 'AAY, PHH or NPHH (client, 12 Nov); null = not asked / none';

-- -----------------------------------------------------------------------------
-- 4. Part notes: one shared note per part. A part's voters are in one booth
--    (import_roll_parts.py), so the note hangs on the booth.
-- -----------------------------------------------------------------------------
CREATE TABLE app.part_notes (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          uuid NOT NULL REFERENCES app.tenants(id),
  booth_id           uuid NOT NULL,
  note               text NOT NULL DEFAULT '' CHECK (length(note) <= 2000),
  version            int NOT NULL DEFAULT 1,                  -- optimistic lock for offline edits
  updated_by         uuid,
  updated_device_id  uuid,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  sync_xid           xid8   NOT NULL DEFAULT '0',
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, booth_id),
  FOREIGN KEY (tenant_id, booth_id)          REFERENCES app.geo_units (tenant_id, id),
  FOREIGN KEY (tenant_id, updated_by)        REFERENCES app.users (tenant_id, id),
  FOREIGN KEY (tenant_id, updated_device_id) REFERENCES app.devices (tenant_id, id)
);
COMMENT ON TABLE app.part_notes IS 'One shared note per roll part (its booth), synced to everyone working there (client, 12 Nov).';
CREATE INDEX part_notes_sync_idx ON app.part_notes (tenant_id, sync_xid);

-- -----------------------------------------------------------------------------
-- 5. Polling time (voter slips)
-- -----------------------------------------------------------------------------
ALTER TABLE app.tenant_settings
  ADD COLUMN polling_start_time time,
  ADD COLUMN polling_end_time   time,
  ADD CHECK (polling_end_time IS NULL OR polling_start_time IS NULL OR polling_end_time > polling_start_time);

-- -----------------------------------------------------------------------------
-- Triggers and row-level security, as in 001 sections 16 and 17
-- -----------------------------------------------------------------------------
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['positions', 'influencer_types', 'part_notes'] LOOP
    EXECUTE format('CREATE TRIGGER %I BEFORE INSERT OR UPDATE ON app.%I
                    FOR EACH ROW EXECUTE FUNCTION app.touch_row()', t || '_touch', t);
    EXECUTE format('CREATE TRIGGER %I AFTER INSERT OR UPDATE OR DELETE ON app.%I
                    FOR EACH ROW EXECUTE FUNCTION app.audit_changes()', t || '_audit', t);
    EXECUTE format('ALTER TABLE app.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE app.%I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY tenant_isolation ON app.%I
                    USING (tenant_id = app.current_tenant_id())
                    WITH CHECK (tenant_id = app.current_tenant_id())', t);
  END LOOP;
END $$;

CREATE TRIGGER part_notes_version BEFORE UPDATE ON app.part_notes
  FOR EACH ROW EXECUTE FUNCTION app.bump_version();

-- -----------------------------------------------------------------------------
-- New-workspace defaults: no white tag; placeholder positions and influencer types.
-- Same signature as in 001, so the existing grants and the REVOKE stay.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.seed_client_lists(p_tenant uuid) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  -- Placeholders ("use dummy searchable options for now", client 12 Nov). Admins rename them in Lists & labels.
  INSERT INTO app.positions (tenant_id, name_mr, name_en, sort_order) VALUES
    (p_tenant, 'सरपंच',                'Sarpanch',                  1),
    (p_tenant, 'उपसरपंच',              'Deputy Sarpanch',           2),
    (p_tenant, 'ग्रामपंचायत सदस्य',     'Gram Panchayat member',     3),
    (p_tenant, 'नगरसेवक',              'Corporator',                4),
    (p_tenant, 'सोसायटी अध्यक्ष',       'Society chairman',          5),
    (p_tenant, 'पक्ष पदाधिकारी',        'Party office bearer',       6),
    (p_tenant, 'माजी लोकप्रतिनिधी',     'Former elected member',     7),
    (p_tenant, 'इतर',                  'Other',                     99)
  ON CONFLICT DO NOTHING;

  INSERT INTO app.influencer_types (tenant_id, name_mr, name_en, sort_order) VALUES
    (p_tenant, 'धार्मिक नेते',          'Religious leader',          1),
    (p_tenant, 'शिक्षक',               'Teacher',                   2),
    (p_tenant, 'डॉक्टर',               'Doctor',                    3),
    (p_tenant, 'व्यापारी',             'Business owner',            4),
    (p_tenant, 'सामाजिक कार्यकर्ते',    'Social worker',             5),
    (p_tenant, 'युवा नेते',            'Youth leader',              6),
    (p_tenant, 'महिला बचत गट प्रमुख',   'Self help group leader',    7),
    (p_tenant, 'इतर',                  'Other',                     99)
  ON CONFLICT DO NOTHING;
END $$;
REVOKE EXECUTE ON FUNCTION app.seed_client_lists(uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION app.seed_tenant_defaults(p_tenant uuid) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  -- Run as jansetu_owner when a tenant is created.
  INSERT INTO app.tenant_settings (tenant_id) VALUES (p_tenant) ON CONFLICT DO NOTHING;

  -- Labels as used in the old app; admins can rename them in "Lists & labels".
  -- No white "Other" tag (client, 12 Nov): a voter without a tag has none.
  INSERT INTO app.color_tags (tenant_id, code, hex, label_mr, label_en, label_hi, is_default, sort_order) VALUES
    (p_tenant, 'green',  '#2E8B57', 'आपले',    'Ours',     'हमारे',   false, 1),
    (p_tenant, 'red',    '#C8382E', 'विरोधी',  'Opposite', 'विरोधी',  false, 2),
    (p_tenant, 'yellow', '#E0B000', 'संदिग्ध', 'Doubtful', 'संदिग्ध', false, 3)
  ON CONFLICT DO NOTHING;

  INSERT INTO app.custom_field_labels (tenant_id, field_key)
  SELECT p_tenant, k FROM unnest(enum_range(NULL::app.custom_field_key)) AS k
  ON CONFLICT DO NOTHING;

  INSERT INTO app.message_templates (tenant_id, kind, body_mr, body_en) VALUES
    (p_tenant, 'birthday',
     'वाढदिवसाच्या हार्दिक शुभेच्छा, {name}! आपले आयुष्य आनंदी आणि आरोग्यदायी जावो.',
     'Happy birthday, {name}! Wishing you a happy and healthy year.')
  ON CONFLICT DO NOTHING;

  PERFORM app.seed_client_lists(p_tenant);
END $$;

-- Existing workspaces get the placeholder lists too.
SELECT app.seed_client_lists(id) FROM app.tenants;

RESET ROLE;
