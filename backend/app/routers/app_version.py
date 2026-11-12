"""GET /app/version (6.3): the newest APK on our server, for the app's update check.

Public: the app asks before login (and with an expired token), so no auth and no
workspace. Releases are global rows in app.app_releases, written only by
scripts/publish_apk.py as the owner (the API role may read them, not write).

- latest_*: the release with the highest version_code.
- min_version_code: the highest version_code published with is_required; 1 when none is
  (nothing forced). An app below it must update before anything else.
- apk_url: absolute, built from the address the phone used (the domain through Caddy,
  or the laptop's address in the fallback); Caddy serves the file under /download/.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import text

from ..db import transaction
from ..errors import ApiError
from ..schemas_field import AppVersion

router = APIRouter(tags=["more"])

_SQL = text("""
    SELECT r.version_code, r.version_name, r.apk_path, r.apk_sha256, r.size_bytes, r.notes_mr, r.notes_en,
           coalesce((SELECT max(version_code) FROM app.app_releases WHERE is_required), 1) AS min_version_code
    FROM app.app_releases r
    ORDER BY r.version_code DESC
    LIMIT 1
""")


@router.get("/app/version", response_model=AppVersion,
            summary="Latest and minimum app version and the APK link. Public (the app checks it before login). "
                    "404 not_found while no APK has been published.")
def app_version(request: Request) -> AppVersion:
    with transaction() as conn:
        row = conn.execute(_SQL).mappings().first()
    if row is None:
        raise ApiError(404, "not_found", "No app version has been published yet.")
    base = str(request.base_url).rstrip("/")
    return AppVersion(
        latest_version_code=row["version_code"],
        latest_version_name=row["version_name"],
        min_version_code=row["min_version_code"],
        apk_url=base + "/" + row["apk_path"].lstrip("/"),
        apk_sha256=row["apk_sha256"].strip(),
        size_bytes=row["size_bytes"],
        notes_mr=row["notes_mr"],
        notes_en=row["notes_en"],
    )
