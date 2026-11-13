-- =============================================================================
-- JANSETU – 003: Kutumb Connect members (plan task 7.1, decided 13 Nov 2026)
-- Runs inside migrate.py's transaction (no BEGIN / COMMIT here).
--
-- A Kutumb (app.families) is made by hand by a surveyor: free-text name, one booth,
-- no head. Its members live in their own table, not in voter_surveys.family_id:
-- that row carries the survey's version, and every membership change would raise
-- it and give false 409s on survey saves (and create survey rows for voters who
-- were never surveyed). voter_surveys.family_id and families.head_voter_id stay
-- in the schema, unused.
--
-- One row per voter who was ever put in a Kutumb. Taking a voter out sets
-- family_id to NULL instead of deleting the row, so a delta pull (7.2) sees it.
-- =============================================================================

SET LOCAL ROLE jansetu_owner;
SET LOCAL search_path = app, public;

CREATE TABLE app.family_members (
  voter_id           uuid PRIMARY KEY,                       -- a voter is in one Kutumb at most
  tenant_id          uuid NOT NULL REFERENCES app.tenants(id),
  family_id          uuid,                                   -- NULL = taken out, in no Kutumb now
  updated_by         uuid,
  updated_device_id  uuid,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  sync_xid           xid8   NOT NULL DEFAULT '0',
  FOREIGN KEY (tenant_id, voter_id)          REFERENCES app.voters (tenant_id, id),
  FOREIGN KEY (tenant_id, family_id)         REFERENCES app.families (tenant_id, id),
  FOREIGN KEY (tenant_id, updated_by)        REFERENCES app.users (tenant_id, id),
  FOREIGN KEY (tenant_id, updated_device_id) REFERENCES app.devices (tenant_id, id)
);
COMMENT ON TABLE app.family_members IS 'Kutumb Connect: which hand-made family (Kutumb) a voter is in (client, 12 Nov). family_id NULL = taken out.';
CREATE INDEX family_members_family_idx ON app.family_members (tenant_id, family_id) WHERE family_id IS NOT NULL;
CREATE INDEX family_members_sync_idx ON app.family_members (tenant_id, sync_xid);

-- Kutumbs of a booth by name (GET /booths/{id}/families)
CREATE INDEX families_booth_label_idx ON app.families (tenant_id, booth_id, lower(label), id) WHERE deleted_at IS NULL;

-- -----------------------------------------------------------------------------
-- Triggers and row-level security, as in 001 sections 16 and 17
-- -----------------------------------------------------------------------------
CREATE TRIGGER family_members_touch BEFORE INSERT OR UPDATE ON app.family_members
  FOR EACH ROW EXECUTE FUNCTION app.touch_row();
CREATE TRIGGER family_members_audit AFTER INSERT OR UPDATE OR DELETE ON app.family_members
  FOR EACH ROW EXECUTE FUNCTION app.audit_changes();
ALTER TABLE app.family_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.family_members FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON app.family_members
  USING (tenant_id = app.current_tenant_id())
  WITH CHECK (tenant_id = app.current_tenant_id());

RESET ROLE;
