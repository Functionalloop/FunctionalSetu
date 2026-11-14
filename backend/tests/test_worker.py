"""Background worker (plan 10.1): app.jobs, app.claim_job, app/worker.py.

Every test uses its own job kind, so jobs other tests leave queued are never taken here
(the worker claims only the kinds it has handlers for).
"""

from __future__ import annotations

import threading
import time
import uuid

import pytest
from conftest import _connect
from sqlalchemy import text

from app import db as app_db
from app import worker
from app.worker import Handler, JobFailed


@pytest.fixture
def kind() -> str:
    return f"t_{uuid.uuid4().hex[:12]}"


def add_job(owner_conn, ws, kind: str, user: str = "boss", **cols) -> uuid.UUID:
    """A queued job written by the owner (what enqueue does in a request)."""
    job_id = uuid.uuid4()
    names = ["id", "tenant_id", "kind", "created_by", *cols]
    values = [job_id, ws.tenant, kind, ws.users[user], *cols.values()]
    owner_conn.execute(f"INSERT INTO app.jobs ({', '.join(names)}) VALUES ({', '.join(['%s'] * len(names))})",
                       values)
    return job_id


def job_row(owner_conn, job_id: uuid.UUID) -> dict:
    cur = owner_conn.execute(
        """SELECT status::text, attempts, error, claim_token, run_after > now() AS waiting,
                  finished_at IS NOT NULL AS finished
             FROM app.jobs WHERE id = %s""", (job_id,))
    names = [c.name for c in cur.description]
    return dict(zip(names, cur.fetchone()))


def make_due(owner_conn, job_id: uuid.UUID) -> None:
    owner_conn.execute("UPDATE app.jobs SET run_after = now() WHERE id = %s", (job_id,))


def booth_name(owner_conn, booth: uuid.UUID) -> str:
    return owner_conn.execute("SELECT name_en FROM app.geo_units WHERE id = %s", (booth,)).fetchone()[0]


# --- claiming -------------------------------------------------------------------------
def test_two_workers_never_take_the_same_job(owner_conn, make_workspace, kind):
    a, b = make_workspace("wa"), make_workspace("wb")
    jobs = {add_job(owner_conn, ws, kind): ws.tenant for ws in (a, b) for _ in range(15)}
    seen: list[uuid.UUID] = []
    lock = threading.Lock()

    def record(conn, job):
        tenant = conn.execute(text("SELECT app.current_tenant_id()")).scalar_one()
        assert tenant == job.tenant_id
        time.sleep(0.01)   # hold the job a moment so the workers overlap
        with lock:
            seen.append(job.id)

    handlers = {kind: Handler(record)}

    def work():
        while worker.run_one(handlers):
            pass

    threads = [threading.Thread(target=work) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert sorted(seen) == sorted(jobs)   # every job once, none twice
    rows = owner_conn.execute("SELECT status::text, attempts FROM app.jobs WHERE kind = %s", (kind,)).fetchall()
    assert rows and all(r == ("done", 1) for r in rows)


def test_a_job_another_transaction_holds_is_skipped(owner_conn, make_workspace, kind):
    ws = make_workspace("skip")
    first, second = add_job(owner_conn, ws, kind), add_job(owner_conn, ws, kind)
    claim = "SELECT id FROM app.claim_job(%s, 300)"
    with _connect("jansetu_app", "JANSETU_APP_PASSWORD") as c1, \
            _connect("jansetu_app", "JANSETU_APP_PASSWORD") as c2, \
            _connect("jansetu_app", "JANSETU_APP_PASSWORD") as c3:
        assert c1.execute(claim, ([kind],)).fetchone()[0] == first    # not committed yet: row locked
        assert c2.execute(claim, ([kind],)).fetchone()[0] == second   # skips the locked row
        assert c3.execute(claim, ([kind],)).fetchone() is None
        c1.commit()
        c2.commit()
        c3.rollback()
        # both running with a live lease: nothing to take
        assert c3.execute(claim, ([kind],)).fetchone() is None
    assert job_row(owner_conn, first)["status"] == "running"


def test_only_the_named_kinds_are_taken(owner_conn, make_workspace, kind):
    ws = make_workspace("kinds")
    other = add_job(owner_conn, ws, kind + "_x")
    assert worker.claim([kind], 300) is None
    assert job_row(owner_conn, other)["status"] == "queued"


def test_a_running_job_with_a_live_lease_is_left_alone(owner_conn, make_workspace, kind):
    ws = make_workspace("live")
    job = add_job(owner_conn, ws, kind, status="running", attempts=1, claim_token=uuid.uuid4())
    owner_conn.execute("UPDATE app.jobs SET locked_until = now() + interval '5 min' WHERE id = %s", (job,))
    assert worker.run_one({kind: Handler(lambda conn, j: None)}) is False


def test_a_job_whose_worker_died_is_taken_again(owner_conn, make_workspace, kind):
    ws = make_workspace("dead")
    job = add_job(owner_conn, ws, kind, status="running", attempts=1, claim_token=uuid.uuid4())
    owner_conn.execute("UPDATE app.jobs SET locked_until = now() - interval '1 s' WHERE id = %s", (job,))
    ran = []
    assert worker.run_one({kind: Handler(lambda conn, j: ran.append(j.attempts))}) is True
    assert ran == [2]
    assert job_row(owner_conn, job)["status"] == "done"


def test_a_job_that_killed_its_worker_every_time_is_failed_without_running(owner_conn, make_workspace, kind):
    ws = make_workspace("crash")
    job = add_job(owner_conn, ws, kind, status="running", attempts=worker.MAX_ATTEMPTS, claim_token=uuid.uuid4())
    owner_conn.execute("UPDATE app.jobs SET locked_until = now() - interval '1 s' WHERE id = %s", (job,))
    ran, failed = [], []
    handlers = {kind: Handler(lambda conn, j: ran.append(j), lambda conn, j, msg: failed.append(msg))}
    assert worker.run_one(handlers) is True
    assert ran == []
    row = job_row(owner_conn, job)
    assert row["status"] == "failed" and "stopped after" in row["error"]
    assert failed == [row["error"]]


# --- running ----------------------------------------------------------------------------
def test_the_handler_runs_in_the_jobs_workspace_as_its_user(owner_conn, make_workspace, kind):
    a, b = make_workspace("ctx-a"), make_workspace("ctx-b")
    job = add_job(owner_conn, a, kind, user="admin1")
    seen = {}

    def look(conn, j):
        seen["tenant"], seen["user"] = conn.execute(
            text("SELECT app.current_tenant_id(), app.current_user_id()")).one()
        seen["areas"] = set(conn.execute(text("SELECT id FROM app.geo_units")).scalars())

    assert worker.run_one({kind: Handler(look)})
    assert seen["tenant"] == a.tenant and seen["user"] == a.users["admin1"]
    assert seen["areas"] == {a.local_body, a.ward, *a.booths}   # RLS: nothing of workspace b
    assert job_row(owner_conn, job) | {"claim_token": None} == {
        "status": "done", "attempts": 1, "error": None, "claim_token": None, "waiting": False, "finished": True}


def test_an_error_is_tried_again_after_a_pause_then_fails(owner_conn, make_workspace, kind):
    ws = make_workspace("retry")
    job = add_job(owner_conn, ws, kind)
    failed = []

    def boom(conn, j):
        conn.execute(text("UPDATE app.geo_units SET name_en = 'half done' WHERE id = :b"), {"b": ws.booths[0]})
        raise RuntimeError("disk full")

    handlers = {kind: Handler(boom, lambda conn, j, msg: failed.append(msg))}
    for attempt in range(1, worker.MAX_ATTEMPTS):
        assert worker.run_one(handlers)
        row = job_row(owner_conn, job)
        assert (row["status"], row["attempts"], row["waiting"]) == ("queued", attempt, True)
        assert row["error"] == "RuntimeError: disk full" and row["claim_token"] is None
        assert worker.run_one(handlers) is False   # waits for its pause
        make_due(owner_conn, job)
    assert worker.run_one(handlers)
    row = job_row(owner_conn, job)
    assert (row["status"], row["attempts"], row["finished"]) == ("failed", worker.MAX_ATTEMPTS, True)
    assert failed == ["RuntimeError: disk full"]
    assert booth_name(owner_conn, ws.booths[0]) == "Booth 1"   # every try rolled back


def test_job_failed_fails_at_once_and_keeps_only_what_on_fail_wrote(owner_conn, make_workspace, kind):
    ws = make_workspace("bad")
    job = add_job(owner_conn, ws, kind)

    def bad_file(conn, j):
        conn.execute(text("UPDATE app.geo_units SET name_en = 'half done' WHERE id = :b"), {"b": ws.booths[0]})
        raise JobFailed("The file has no EPIC column.")

    def mark(conn, j, msg):
        conn.execute(text("UPDATE app.geo_units SET name_en = :m WHERE id = :b"), {"m": msg, "b": ws.booths[1]})

    assert worker.run_one({kind: Handler(bad_file, mark)})
    row = job_row(owner_conn, job)
    assert (row["status"], row["attempts"], row["error"]) == ("failed", 1, "The file has no EPIC column.")
    assert booth_name(owner_conn, ws.booths[0]) == "Booth 1"
    assert booth_name(owner_conn, ws.booths[1]) == "The file has no EPIC column."


def test_a_broken_on_fail_still_fails_the_job(owner_conn, make_workspace, kind):
    ws = make_workspace("onfail")
    job = add_job(owner_conn, ws, kind)

    def broken(conn, j, msg):
        conn.execute(text("SELECT 1 / 0"))

    assert worker.run_one({kind: Handler(lambda conn, j: (_ for _ in ()).throw(JobFailed("no")), broken)})
    assert job_row(owner_conn, job)["status"] == "failed"


def test_a_lost_claim_runs_nothing(owner_conn, make_workspace, kind):
    """The lease ran out before the run began and another worker took the job."""
    ws = make_workspace("lost")
    job_id = add_job(owner_conn, ws, kind)
    job = worker.claim([kind], 300)
    assert job is not None and job.id == job_id
    other = uuid.uuid4()
    owner_conn.execute("UPDATE app.jobs SET claim_token = %s WHERE id = %s", (other, job_id))
    ran = []
    worker.run_job(job, {kind: Handler(lambda conn, j: ran.append(j))})
    assert ran == []
    row = job_row(owner_conn, job_id)
    assert (row["status"], row["claim_token"]) == ("running", other)


def test_run_forever_takes_new_jobs_until_stopped(owner_conn, make_workspace, kind):
    ws = make_workspace("loop")
    done = threading.Event()
    stop = threading.Event()
    t = threading.Thread(target=worker.run_forever,
                         args=(stop, {kind: Handler(lambda conn, j: done.set())}, 0.05))
    t.start()
    try:
        job = add_job(owner_conn, ws, kind)   # queued while the worker waits
        assert done.wait(10)
    finally:
        stop.set()
        t.join(timeout=10)
    assert not t.is_alive()
    for _ in range(50):   # the handler ran; the commit follows right after
        if job_row(owner_conn, job)["status"] == "done":
            break
        time.sleep(0.05)
    assert job_row(owner_conn, job)["status"] == "done"


# --- queueing ---------------------------------------------------------------------------
def test_enqueue_stores_the_requests_workspace_and_user(owner_conn, make_workspace, kind):
    a, b = make_workspace("enq-a"), make_workspace("enq-b")
    ref = uuid.uuid4()
    with app_db.transaction(a.tenant, a.users["admin1"]) as conn:
        job_id = worker.enqueue(conn, kind, ref, {"sheet": 1})
    row = owner_conn.execute("SELECT tenant_id, created_by, ref_id, payload, status::text FROM app.jobs WHERE id = %s",
                             (job_id,)).fetchone()
    assert row == (a.tenant, a.users["admin1"], ref, {"sheet": 1}, "queued")
    with app_db.transaction(b.tenant) as conn:   # RLS: another workspace does not see it
        assert conn.execute(text("SELECT count(*) FROM app.jobs WHERE id = :id"), {"id": job_id}).scalar_one() == 0
    with app_db.transaction() as conn:            # no workspace: nothing
        assert conn.execute(text("SELECT count(*) FROM app.jobs")).scalar_one() == 0


def test_the_api_role_cannot_queue_a_job_for_another_workspace(make_workspace, kind):
    a, b = make_workspace("rls-a"), make_workspace("rls-b")
    with pytest.raises(Exception, match="row-level security"):
        with app_db.transaction(a.tenant) as conn:
            conn.execute(text("INSERT INTO app.jobs (tenant_id, kind) VALUES (:t, :k)"), {"t": b.tenant, "k": kind})


def test_python_dash_m_app_worker_has_every_handler():
    """The worker is started as `python -m app.worker` (Docker); its handlers must be the registered ones
    (14 Nov: run as __main__ it had none and would never take a job)."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    out = subprocess.run([sys.executable, "-m", "app.worker", "--kinds"], cwd=Path(__file__).parents[1],
                         env=os.environ.copy(), capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["export", "mobile_import", "roll_import"]
