-- =============================================================================
-- JANSETU – 005: job queue for the background worker (plan task 10.1, 14 Nov 2026)
-- Runs inside migrate.py's transaction (no BEGIN / COMMIT here).
--
-- The API queues a job row (roll import 10.2, mobile numbers 10.5, export 11.2);
-- the worker (backend/app/worker.py) takes it. The worker connects as jansetu_app,
-- so RLS hides every workspace's rows until app.set_context runs. app.claim_job is
-- the one place that looks across workspaces: it takes the oldest ready job with
-- FOR UPDATE SKIP LOCKED (two workers never take the same job), marks it running
-- and returns it; the worker then does the work in that job's workspace with RLS.
--
-- No sync_xid / audit triggers: jobs are bookkeeping, never sent to phones, and
-- the work they do writes its own audit rows.
-- (Step 14's schema changes move to 006_change_requests.sql.)
-- =============================================================================

SET LOCAL ROLE jansetu_owner;
SET LOCAL search_path = app, public;

CREATE TABLE app.jobs (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES app.tenants(id),
  kind          text NOT NULL CHECK (kind ~ '^[a-z0-9_]{1,40}$'),  -- handler name: roll_import, mobile_import, export, ...
  ref_id        uuid,                       -- the row the job works on (roll_versions, mobile_import_batches, exports)
  payload       jsonb NOT NULL DEFAULT '{}'::jsonb,
  status        app.job_status NOT NULL DEFAULT 'queued',
  attempts      int NOT NULL DEFAULT 0,     -- raised by every claim
  run_after     timestamptz NOT NULL DEFAULT now(),   -- a retry waits until then
  claim_token   uuid,                       -- new on every claim; the worker finishes only while it still matches
  locked_until  timestamptz,                -- lease: a running job past it is taken again (worker died)
  error         text,
  created_by    uuid,
  created_at    timestamptz NOT NULL DEFAULT now(),
  started_at    timestamptz,
  finished_at   timestamptz,
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, created_by) REFERENCES app.users (tenant_id, id)
);
CREATE INDEX jobs_todo_idx ON app.jobs (created_at, id) WHERE status IN ('queued', 'running');
CREATE INDEX jobs_ref_idx  ON app.jobs (tenant_id, ref_id);

ALTER TABLE app.jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.jobs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON app.jobs
  USING (tenant_id = app.current_tenant_id())
  WITH CHECK (tenant_id = app.current_tenant_id());

-- The oldest job of one of p_kinds that is queued and due, or running with its lease
-- run out. A row another transaction holds (a worker busy with it) is skipped.
-- Returns no row when there is nothing to do.
CREATE FUNCTION app.claim_job(p_kinds text[], p_lease_seconds int DEFAULT 300)
RETURNS SETOF app.jobs
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = app, public, pg_temp AS $$
  WITH next AS (
    SELECT j.id
      FROM app.jobs j
     WHERE j.status IN ('queued', 'running')
       AND j.kind = ANY (p_kinds)
       AND ((j.status = 'queued'  AND j.run_after <= now())
         OR (j.status = 'running' AND j.locked_until < now()))
     ORDER BY j.created_at, j.id
     LIMIT 1
     FOR UPDATE SKIP LOCKED
  )
  UPDATE app.jobs j
     SET status       = 'running',
         attempts     = j.attempts + 1,
         claim_token  = gen_random_uuid(),
         started_at   = now(),
         locked_until = now() + make_interval(secs => greatest(p_lease_seconds, 10))
    FROM next
   WHERE j.id = next.id
  RETURNING j.*;
$$;
REVOKE ALL ON FUNCTION app.claim_job(text[], int) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.claim_job(text[], int) TO jansetu_app;

RESET ROLE;
