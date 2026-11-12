"""Publish a release APK: record it in app.app_releases so GET /api/v1/app/version offers it.

1. Build the signed release APK (android/: gradlew assembleRelease).
2. Put it in deploy/apk/ under a name with its version, e.g. jansetu-0.2.0.apk
   (server: scp it to /srv/jansetu/deploy/apk/). Caddy serves that folder at /download/.
3. Run (server: through the ops container, which has the folder mounted read-only):
     docker compose -f deploy/docker-compose.yml run --rm ops \\
       python scripts/publish_apk.py deploy/apk/jansetu-0.2.0.apk [--required] [--notes-en "..."] [--notes-mr "..."]
   Laptop against the dev database: python scripts/publish_apk.py deploy/apk/jansetu-0.2.0.apk

versionCode and versionName come from output-metadata.json next to the APK (written by the
Android build) or from --version-code / --version-name. The script refuses: a file outside
deploy/apk/, a file that is not a signed APK, a debug build, and a versionCode that is not higher
than every published one. Never replace a published file: phones check its SHA-256.

--required: every app below this version must update before anything else (min_version_code).

Runs as jansetu_owner (the API role cannot write releases).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent))
from create_super_admin import connect_owner  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
APK_DIR = ROOT / "deploy" / "apk"
URL_PREFIX = "/download/"          # deploy/Caddyfile serves APK_DIR here
NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.apk$")
SIG_BLOCK_MAGIC = b"APK Sig Block 42"  # APK signature scheme v2/v3


class PublishError(Exception):
    pass


@dataclass
class Release:
    version_code: int
    version_name: str
    apk_path: str
    apk_sha256: str
    size_bytes: int


def read_metadata(apk: Path) -> dict:
    """versionCode / versionName / applicationId from the Android build's output-metadata.json, if any."""
    meta = apk.parent / "output-metadata.json"
    if not meta.is_file():
        return {}
    data = json.loads(meta.read_text(encoding="utf-8"))
    out = {"application_id": data.get("applicationId"), "variant": data.get("variantName")}
    for el in data.get("elements", []):
        if el.get("outputFile") == apk.name:
            out.update(version_code=el.get("versionCode"), version_name=el.get("versionName"))
    return out


def check_apk(apk: Path, apk_dir: Path) -> tuple[str, int]:
    """The file must be a signed APK inside apk_dir with a plain name. Returns (sha256, size)."""
    apk = apk.resolve()
    if apk.parent != apk_dir.resolve():
        raise PublishError(f"{apk} is not in {apk_dir}: copy the APK there first (Caddy serves only that folder).")
    if not NAME_RE.match(apk.name):
        raise PublishError(f"File name {apk.name!r}: use letters, digits, '.', '_' or '-' and end in .apk.")
    data = apk.read_bytes()
    if not data.startswith(b"PK\x03\x04"):
        raise PublishError(f"{apk.name} is not an APK (not a zip file).")
    if SIG_BLOCK_MAGIC not in data:
        raise PublishError(f"{apk.name} is not signed: phones will not install it. Build it with the release keystore.")
    return hashlib.sha256(data).hexdigest(), len(data)


def publish(conn: psycopg.Connection, apk: Path, version_code: int, version_name: str, *, required: bool = False,
            notes_en: str | None = None, notes_mr: str | None = None, apk_dir: Path = APK_DIR) -> Release:
    """Check the APK and insert its app_releases row (in the caller's transaction)."""
    if version_code < 1:
        raise PublishError("versionCode must be 1 or more.")
    if not version_name.strip():
        raise PublishError("versionName is empty.")
    sha, size = check_apk(apk, apk_dir)
    apk_path = URL_PREFIX + apk.name
    newest = conn.execute("SELECT max(version_code) FROM app.app_releases").fetchone()[0]
    if newest is not None and version_code <= newest:
        raise PublishError(f"versionCode {version_code} is not higher than the published {newest}. "
                           "Raise versionCode in android/app/build.gradle.kts and build again.")
    if conn.execute("SELECT 1 FROM app.app_releases WHERE apk_path = %s", (apk_path,)).fetchone():
        raise PublishError(f"{apk_path} is already published. Use a new file name for a new version.")
    conn.execute(
        """INSERT INTO app.app_releases (version_code, version_name, apk_path, apk_sha256, size_bytes,
                                         is_required, notes_mr, notes_en)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (version_code, version_name.strip(), apk_path, sha, size, required, notes_mr, notes_en))
    return Release(version_code, version_name.strip(), apk_path, sha, size)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("apk", type=Path, help="the APK, already in deploy/apk/")
    parser.add_argument("--version-code", type=int, help="default: from output-metadata.json")
    parser.add_argument("--version-name", help="default: from output-metadata.json")
    parser.add_argument("--required", action="store_true", help="apps below this version must update")
    parser.add_argument("--notes-en", help="what is new, English")
    parser.add_argument("--notes-mr", help="what is new, Marathi")
    args = parser.parse_args()

    meta = read_metadata(args.apk)
    if (meta.get("application_id") or "").endswith(".debug") or meta.get("variant") == "debug":
        sys.exit("This is a debug build. Publish only the release APK.")
    code = args.version_code or meta.get("version_code")
    name = args.version_name or meta.get("version_name")
    if not code or not name:
        sys.exit("versionCode / versionName unknown: pass --version-code and --version-name "
                 "(no output-metadata.json next to the APK).")
    try:
        with connect_owner() as conn:
            rel = publish(conn, args.apk, int(code), str(name), required=args.required,
                          notes_en=args.notes_en, notes_mr=args.notes_mr)
    except PublishError as e:
        sys.exit(str(e))
    print(f"Published {rel.version_name} (versionCode {rel.version_code}{', required' if args.required else ''})")
    print(f"  file   {rel.apk_path}  {rel.size_bytes:,} bytes")
    print(f"  sha256 {rel.apk_sha256}")
    print("Check: GET /api/v1/app/version, and download the file from a phone.")


if __name__ == "__main__":
    main()
