"""Background worker (plan 10.1): one process that runs the jobs queued in app.jobs.

    python -m app.worker           # from backend/; in Docker the `worker` service
    python -m app.worker --once    # run the jobs that are ready now, then stop

The API queues a job with `enqueue(conn, kind, ref_id)` inside its request transaction
and answers at once; clients poll the job's own row (roll import, export, ...).

How one job runs:
 1. Claim (own transaction): `app.claim_job(kinds, lease)` takes the oldest ready job
    of a kind this worker has a handler for, with FOR UPDATE SKIP LOCKED, marks it
    running with a new claim_token and a lease, and commits. Two workers never take
    the same job. It is the only query that looks across workspaces (SECURITY DEFINER);
    the worker connects as jansetu_app like the API.
 2. Run (own transaction, the job's workspace and user set, so RLS and the audit work
    as for a request): lock the job row (only while the claim_token is still ours),
    run the handler, mark the job done, commit. Holding the lock means no other
    worker can take the job while it runs, however long it takes; if this process
    dies, the lock goes with it and the job is taken again once the lease runs out.
 3. Fail: the handler's writes are rolled back. JobFailed (a bad file, ...) fails the
    job at once with its message; any other error queues it again after a pause and
    fails it after MAX_ATTEMPTS tries. The handler's `on_fail` then marks its own row
    (e.g. the roll import's status) in the same transaction as the job's `failed`.

Handlers are registered by their modules, imported in `load_handlers`: roll import
(10.2, app/roll_match.py); later mobile numbers (10.5) and exports (11.2).
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, text

from .config import get_settings
from .db import transaction

log = logging.getLogger("jansetu.worker")

MAX_ATTEMPTS = 3
RETRY_AFTER_SECONDS = (30, 120)   # pause after failed try 1, 2, ...
ERROR_CHARS = 500


class JobFailed(Exception):
    """A job that cannot succeed (bad file, row gone): failed at once, not tried again.
    The message is stored on the job and shown to the user, so keep it plain."""


@dataclass(frozen=True)
class Job:
    id: uuid.UUID
    tenant_id: uuid.UUID
    kind: str
    ref_id: uuid.UUID | None
    payload: dict[str, Any]
    created_by: uuid.UUID | None
    attempts: int
    claim_token: uuid.UUID


Run = Callable[[Connection, Job], None]
OnFail = Callable[[Connection, Job, str], None]


@dataclass(frozen=True)
class Handler:
    run: Run                          # does the work inside the job's transaction
    on_fail: OnFail | None = field(default=None)   # marks the job's own row failed


HANDLERS: dict[str, Handler] = {}


def register(kind: str, run: Run, on_fail: OnFail | None = None) -> None:
    HANDLERS[kind] = Handler(run, on_fail)


def enqueue(conn: Connection, kind: str, ref_id: uuid.UUID | None = None,
            payload: dict[str, Any] | None = None) -> uuid.UUID:
    """Queue a job in the caller's transaction; workspace and user come from app.set_context.
    The worker sees it after COMMIT."""
    return conn.execute(text(
        """INSERT INTO app.jobs (tenant_id, kind, ref_id, payload, created_by)
           VALUES (app.current_tenant_id(), :kind, :ref, CAST(:payload AS jsonb), app.current_user_id())
           RETURNING id"""),
        {"kind": kind, "ref": ref_id, "payload": json.dumps(payload or {})}).scalar_one()


# --- one job ----------------------------------------------------------------------
def claim(kinds: list[str], lease_seconds: int) -> Job | None:
    """Take the next ready job of these kinds (committed as running), or None."""
    if not kinds:
        return None
    with transaction() as conn:
        row = conn.execute(text("SELECT * FROM app.claim_job(CAST(:kinds AS text[]), :lease)"),
                           {"kinds": kinds, "lease": lease_seconds}).mappings().first()
    if row is None:
        return None
    return Job(id=row["id"], tenant_id=row["tenant_id"], kind=row["kind"], ref_id=row["ref_id"],
               payload=row["payload"] or {}, created_by=row["created_by"], attempts=row["attempts"],
               claim_token=row["claim_token"])


def _hold(conn: Connection, job: Job) -> bool:
    """Lock the job row for this transaction, if our claim still stands."""
    return conn.execute(text(
        """SELECT 1 FROM app.jobs
            WHERE id = :id AND claim_token = :token AND status = 'running'
              FOR UPDATE"""), {"id": job.id, "token": job.claim_token}).first() is not None


def run_job(job: Job, handlers: Mapping[str, Handler] | None = None) -> None:
    """Run a claimed job: done, queued again, or failed."""
    handlers = HANDLERS if handlers is None else handlers
    handler = handlers.get(job.kind)
    started = time.monotonic()
    try:
        if handler is None:
            raise JobFailed(f"no handler for job kind {job.kind!r}")
        if job.attempts > MAX_ATTEMPTS:   # its worker died during every try
            raise JobFailed(f"stopped after {MAX_ATTEMPTS} tries")
        with transaction(job.tenant_id, job.created_by) as conn:
            if not _hold(conn, job):
                log.warning("job %s (%s): claim lost, skipped", job.id, job.kind)
                return
            handler.run(conn, job)
            conn.execute(text(
                """UPDATE app.jobs SET status = 'done', finished_at = now(), locked_until = NULL, error = NULL
                    WHERE id = :id"""), {"id": job.id})
    except JobFailed as e:
        log.warning("job %s (%s) failed: %s", job.id, job.kind, e)
        _fail(job, handler, str(e), retry=False)
    except Exception as e:
        log.exception("job %s (%s) try %d raised", job.id, job.kind, job.attempts)
        _fail(job, handler, f"{type(e).__name__}: {e}", retry=job.attempts < MAX_ATTEMPTS)
    else:
        log.info("job %s (%s) done in %.1f s", job.id, job.kind, time.monotonic() - started)


def _fail(job: Job, handler: Handler | None, message: str, retry: bool) -> None:
    message = message[:ERROR_CHARS]
    with transaction(job.tenant_id, job.created_by) as conn:
        if not _hold(conn, job):
            return
        if retry:
            pause = RETRY_AFTER_SECONDS[min(job.attempts, len(RETRY_AFTER_SECONDS)) - 1]
            conn.execute(text(
                """UPDATE app.jobs
                      SET status = 'queued', run_after = now() + make_interval(secs => :pause),
                          claim_token = NULL, locked_until = NULL, error = :error
                    WHERE id = :id"""), {"id": job.id, "pause": pause, "error": message})
            return
        conn.execute(text(
            """UPDATE app.jobs SET status = 'failed', finished_at = now(), locked_until = NULL, error = :error
                WHERE id = :id"""), {"id": job.id, "error": message})
        if handler is not None and handler.on_fail is not None:
            try:
                with conn.begin_nested():   # a broken on_fail must not keep the job running
                    handler.on_fail(conn, job, message)
            except Exception:
                log.exception("job %s (%s): on_fail raised", job.id, job.kind)


def run_one(handlers: Mapping[str, Handler] | None = None, lease_seconds: int | None = None) -> bool:
    """Claim and run one job. False when nothing was ready."""
    handlers = HANDLERS if handlers is None else handlers
    lease = lease_seconds if lease_seconds is not None else get_settings().worker_lease_seconds
    job = claim(sorted(handlers), lease)
    if job is None:
        return False
    run_job(job, handlers)
    return True


# --- the process --------------------------------------------------------------------
def run_forever(stop: threading.Event, handlers: Mapping[str, Handler] | None = None,
                poll_seconds: float | None = None) -> None:
    """Run jobs until `stop` is set; a job that has started is finished first."""
    poll = poll_seconds if poll_seconds is not None else get_settings().worker_poll_seconds
    while not stop.is_set():
        try:
            busy = run_one(handlers)
        except Exception:   # database restarting, network: wait and look again
            log.exception("worker loop error")
            busy = False
        if not busy:
            stop.wait(poll)


def load_handlers() -> None:
    """Import the modules that register handlers (they import this module, so not at the top)."""
    from . import roll_match  # noqa: F401  roll_import (10.2)


def main(argv: list[str] | None = None) -> int:
    load_handlers()
    parser = argparse.ArgumentParser(description="JANSETU background worker")
    parser.add_argument("--once", action="store_true", help="run the jobs that are ready now, then stop")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.once:
        count = 0
        while run_one():
            count += 1
        log.info("ran %d job(s)", count)
        return 0

    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    log.info("worker started; kinds: %s", ", ".join(sorted(HANDLERS)) or "none yet")
    run_forever(stop)
    log.info("worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
