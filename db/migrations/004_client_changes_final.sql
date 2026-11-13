-- =============================================================================
-- JANSETU – 004: the client's final list of 12 Nov, survey part (plan task 7.13)
-- The client approved the updated app flow on 13 Nov 2026.
-- Runs inside migrate.py's transaction (no BEGIN / COMMIT here).
--
--   1. No Important voter field and no positions list: voter_surveys.position_id and
--      app.positions are dropped. voter_surveys.is_important stays as a column (old
--      values kept) but the API no longer reads or writes it.
--   2. Influencer types: the client's 11 entries replace the placeholders of 002.
--      A placeholder that a survey uses is switched off (old surveys keep showing it);
--      an unused one is deleted. "Social worker" is kept and renamed, so its surveys stay.
-- =============================================================================

SET LOCAL ROLE jansetu_owner;
SET LOCAL search_path = app, public;

-- -----------------------------------------------------------------------------
-- 1. Positions out (the column's foreign key and CHECK go with it)
-- -----------------------------------------------------------------------------
ALTER TABLE app.voter_surveys DROP COLUMN position_id;
DROP TABLE app.positions;
COMMENT ON COLUMN app.voter_surveys.is_important IS
  'Not used since 7.13 (client, 12 Nov: no Important voter field). Old values kept; the API neither reads nor writes it.';

-- -----------------------------------------------------------------------------
-- 2. The client's influencer list. Same signature as in 002 (grants and REVOKE stay).
--    Marathi names are ours (the client wrote English); admins can rename them later.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.seed_client_lists(p_tenant uuid) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO app.influencer_types (tenant_id, name_mr, name_en, sort_order) VALUES
    (p_tenant, 'सरपंच',                      'Sarpanch',                 1),
    (p_tenant, 'पंच सदस्य',                   'Panch Member',             2),
    (p_tenant, 'उपसरपंच',                    'Up Sarpanch',              3),
    (p_tenant, 'जिल्हा पंचायत सदस्य',          'ZP Member',                4),
    (p_tenant, 'माजी जिल्हा पंचायत सदस्य',     'Ex. ZP Member',            5),
    (p_tenant, 'आमदार',                      'MLA',                      6),
    (p_tenant, 'माजी आमदार',                  'Ex. MLA',                  7),
    (p_tenant, 'स्वयंसेवी संस्था',             'NGO',                      8),
    (p_tenant, 'सामाजिक कार्यकर्ते',           'Social Worker',            9),
    (p_tenant, 'पत्रकार',                     'News Reporter',            10),
    (p_tenant, 'सोशल मीडिया इन्फ्लुएन्सर',      'Social Media Influencer',  11)
  ON CONFLICT (tenant_id, name_mr) DO UPDATE
    SET name_en = EXCLUDED.name_en, sort_order = EXCLUDED.sort_order, is_active = true;
END $$;
REVOKE EXECUTE ON FUNCTION app.seed_client_lists(uuid) FROM PUBLIC;

-- Existing workspaces: add the 11 (Social worker is updated in place) ...
SELECT app.seed_client_lists(id) FROM app.tenants;

-- ... and retire the other placeholders of 002.
CREATE TEMP TABLE old_placeholders (name_mr text) ON COMMIT DROP;
INSERT INTO old_placeholders VALUES
  ('धार्मिक नेते'), ('शिक्षक'), ('डॉक्टर'), ('व्यापारी'), ('युवा नेते'), ('महिला बचत गट प्रमुख'), ('इतर');

DELETE FROM app.influencer_types t
 USING old_placeholders o
 WHERE t.name_mr = o.name_mr
   AND NOT EXISTS (SELECT 1 FROM app.voter_surveys s WHERE s.tenant_id = t.tenant_id AND s.influencer_type_id = t.id);

UPDATE app.influencer_types t SET is_active = false
  FROM old_placeholders o
 WHERE t.name_mr = o.name_mr AND t.is_active;

RESET ROLE;
