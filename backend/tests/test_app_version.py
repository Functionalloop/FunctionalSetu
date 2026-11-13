"""GET /app/version (6.3) and scripts/publish_apk.py.

app.app_releases is a global table (no workspace), so every test here starts and ends with it empty.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("publish_apk_script", ROOT / "scripts" / "publish_apk.py")
publish_apk = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = publish_apk  # its dataclass looks the module up there
_spec.loader.exec_module(publish_apk)

URL = "/api/v1/app/version"


def fake_apk(folder: Path, name: str, payload: bytes = b"classes", signed: bool = True) -> Path:
    """Enough of an APK for the script's checks: zip magic, and the v2 signing block magic when signed."""
    path = folder / name
    path.write_bytes(b"PK\x03\x04" + payload + (b"\x00APK Sig Block 42" if signed else b"") + b"PK\x05\x06")
    return path


@pytest.fixture
def releases(owner_conn):
    owner_conn.execute("DELETE FROM app.app_releases")
    yield owner_conn
    owner_conn.execute("DELETE FROM app.app_releases")


def add_release(conn, code: int, *, required: bool = False, name: str | None = None) -> None:
    conn.execute(
        """INSERT INTO app.app_releases (version_code, version_name, apk_path, apk_sha256, size_bytes,
                                         is_required, notes_en, notes_mr)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (code, name or f"0.{code}.0", f"/download/jansetu-{code}.apk", f"{code:064x}", 1000 + code, required,
         f"notes {code}", None))


# --- the endpoint -------------------------------------------------------------------------------
def test_no_release_yet_is_404(client, releases):
    r = client.get(URL)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_newest_release_without_a_token(client, releases):
    add_release(releases, 3)
    add_release(releases, 5, name="0.5.1")
    add_release(releases, 4)
    r = client.get(URL)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "latest_version_code": 5,
        "latest_version_name": "0.5.1",
        "min_version_code": 1,
        "apk_url": "http://testserver/download/jansetu-5.apk",
        "apk_sha256": f"{5:064x}",
        "size_bytes": 1005,
        "notes_mr": None,
        "notes_en": "notes 5",
    }


def test_works_with_a_bad_or_expired_token(client, releases):
    """The phone checks for updates whatever state its login is in."""
    add_release(releases, 2)
    r = client.get(URL, headers={"Authorization": "Bearer not.a.token"})
    assert r.status_code == 200
    assert r.json()["latest_version_code"] == 2


def test_min_version_is_the_newest_required_release(client, releases):
    add_release(releases, 2, required=True)
    add_release(releases, 4, required=True)
    add_release(releases, 6)
    body = client.get(URL).json()
    assert body["latest_version_code"] == 6
    assert body["min_version_code"] == 4


def test_apk_url_follows_the_address_the_phone_used(client, releases):
    """Domain through Caddy, or the laptop's address in the fallback."""
    add_release(releases, 1)
    r = client.get(URL, headers={"Host": "192.168.43.10:8443", "X-Forwarded-Proto": "https"})
    assert r.json()["apk_url"].endswith("://192.168.43.10:8443/download/jansetu-1.apk")


def test_api_role_cannot_write_releases(app_conn):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute("INSERT INTO app.app_releases (version_code, version_name, apk_path, apk_sha256, size_bytes) "
                         "VALUES (99, 'x', '/download/x.apk', %s, 1)", ("0" * 64,))


# --- scripts/publish_apk.py ---------------------------------------------------------------------
def test_publish_records_the_file(client, releases, tmp_path):
    apk = fake_apk(tmp_path, "jansetu-0.2.0.apk")
    rel = publish_apk.publish(releases, apk, 2, "0.2.0", required=True, notes_en="First release", apk_dir=tmp_path)
    assert rel.apk_path == "/download/jansetu-0.2.0.apk"
    assert rel.apk_sha256 == hashlib.sha256(apk.read_bytes()).hexdigest()
    assert rel.size_bytes == apk.stat().st_size
    body = client.get(URL).json()
    assert (body["latest_version_code"], body["min_version_code"]) == (2, 2)
    assert body["apk_sha256"] == rel.apk_sha256 and body["notes_en"] == "First release"


def test_publish_refuses_a_version_that_does_not_go_up(releases, tmp_path):
    publish_apk.publish(releases, fake_apk(tmp_path, "a.apk"), 3, "0.3.0", apk_dir=tmp_path)
    for code in (3, 2):
        with pytest.raises(publish_apk.PublishError, match="not higher"):
            publish_apk.publish(releases, fake_apk(tmp_path, f"b{code}.apk"), code, "x", apk_dir=tmp_path)


def test_publish_refuses_the_same_file_name_twice(releases, tmp_path):
    apk = fake_apk(tmp_path, "jansetu.apk")
    publish_apk.publish(releases, apk, 1, "0.1.0", apk_dir=tmp_path)
    with pytest.raises(publish_apk.PublishError, match="already published"):
        publish_apk.publish(releases, apk, 2, "0.2.0", apk_dir=tmp_path)


@pytest.mark.parametrize("problem, match", [
    ("outside", "is not in"),
    ("unsigned", "not signed"),
    ("not_zip", "not an APK"),
    ("bad_name", "File name"),
])
def test_publish_refuses_bad_files(releases, tmp_path, problem, match):
    served = tmp_path / "apk"
    served.mkdir()
    if problem == "outside":
        apk = fake_apk(tmp_path, "jansetu.apk")
    elif problem == "unsigned":
        apk = fake_apk(served, "jansetu.apk", signed=False)
    elif problem == "not_zip":
        apk = served / "jansetu.apk"
        apk.write_bytes(b"<html>not an apk</html>")
    else:
        apk = fake_apk(served, "jansetu 1.apk")
    with pytest.raises(publish_apk.PublishError, match=match):
        publish_apk.publish(releases, apk, 1, "0.1.0", apk_dir=served)
    assert releases.execute("SELECT count(*) FROM app.app_releases").fetchone()[0] == 0


def test_version_comes_from_the_build_metadata(tmp_path):
    apk = fake_apk(tmp_path, "app-release.apk")
    (tmp_path / "output-metadata.json").write_text(json.dumps({
        "applicationId": "com.jansetu.app", "variantName": "release",
        "elements": [{"outputFile": "app-release.apk", "versionCode": 7, "versionName": "0.7.0"}],
    }), encoding="utf-8")
    meta = publish_apk.read_metadata(apk)
    assert (meta["version_code"], meta["version_name"], meta["variant"]) == (7, "0.7.0", "release")
