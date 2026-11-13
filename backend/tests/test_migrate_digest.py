"""migrate.py: a migration's digest does not depend on line endings (Windows vs Linux checkout)."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("migrate_script", ROOT / "scripts" / "migrate.py")
migrate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migrate)


def test_crlf_and_lf_give_the_same_digest(tmp_path):
    lf = tmp_path / "lf.sql"
    crlf = tmp_path / "crlf.sql"
    lf.write_bytes(b"CREATE TABLE t (id int);\nSELECT 1;\n")
    crlf.write_bytes(b"CREATE TABLE t (id int);\r\nSELECT 1;\r\n")
    assert migrate.file_digest(lf) == migrate.file_digest(crlf)


def test_lf_digest_is_the_plain_sha256(tmp_path):
    """Digests recorded before the change (plain SHA-256 of LF files) stay valid."""
    f = tmp_path / "a.sql"
    f.write_bytes(b"SELECT 1;\n")
    assert migrate.file_digest(f) == hashlib.sha256(b"SELECT 1;\n").hexdigest()


def test_applied_migrations_match_the_git_copies():
    """Every migration file hashes the same as its committed (LF) copy."""
    for path in sorted((ROOT / "db" / "migrations").glob("*.sql")):
        lf_bytes = path.read_bytes().replace(b"\r\n", b"\n")
        assert migrate.file_digest(path) == hashlib.sha256(lf_bytes).hexdigest()
