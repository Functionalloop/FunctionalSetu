"""Workspace images (9.4): POST /files (admin) and GET /files/{id} (all roles, for slips).

Only images for now: candidate photo, symbol, slip header, WhatsApp slip; PNG or JPEG (told by their first
bytes, not by the name or the browser's type), up to 5 MB. Roll and mobile sheets come with Steps 10 and 13.
The bytes live on disk under Settings.files_dir/<workspace>/<file id> (Docker: the `files` volume); the
app.files row holds the name, type, size and SHA-256. A file is used by pointing an election setting at it.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, Response, UploadFile, status
from sqlalchemy import text

from ..config import get_settings
from ..deps import Db, ReadyUser
from ..errors import ApiError
from ..schemas_admin import FileKind, StoredFile
from ..stubs import Admin

router = APIRouter(tags=["admin"])

MAX_BYTES = 5 * 1024 * 1024
IMAGE_KINDS = frozenset({FileKind.candidate_photo, FileKind.symbol, FileKind.slip_header, FileKind.whatsapp_slip})
_STORED = "id, kind, original_name, mime_type, size_bytes, sha256, created_at"


def _image_type(head: bytes) -> str | None:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


def _path(tenant: uuid.UUID, file_id: uuid.UUID) -> Path:
    return Path(get_settings().files_dir) / str(tenant) / str(file_id)


@router.post("/files", response_model=StoredFile, status_code=status.HTTP_201_CREATED,
             summary="Upload a candidate photo, symbol or slip header (image, up to 5 MB). Admin.")
def upload_file(conn: Db, user: Admin, file: Annotated[UploadFile, File()],
                kind: Annotated[FileKind, Form()]) -> StoredFile:
    if kind not in IMAGE_KINDS:
        raise ApiError(422, "validation_error", "Only images (candidate_photo, symbol, slip_header, whatsapp_slip) "
                                                "are uploaded here.")
    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ApiError(422, "file_too_large", "The file is larger than 5 MB.")
    mime = _image_type(data[:8])
    if mime is None:
        raise ApiError(422, "unsupported_file", "Only PNG or JPEG images.")

    file_id = uuid.uuid4()
    rel = f"{user.tenant_id}/{file_id}"
    name = os.path.basename(file.filename or "").strip()[:200] or None
    row = conn.execute(text(f"""
        INSERT INTO app.files (id, tenant_id, kind, storage_path, original_name, mime_type, size_bytes, sha256,
                               created_by)
        VALUES (:id, :tenant, CAST(:kind AS app.file_kind), :path, :name, :mime, :size, :sha, :by)
        RETURNING {_STORED}
    """), {"id": file_id, "tenant": user.tenant_id, "kind": kind.value, "path": rel, "name": name, "mime": mime,
           "size": len(data), "sha": hashlib.sha256(data).hexdigest(), "by": user.user_id}).mappings().one()
    # Written after the row and before the commit: if the write fails the row is rolled back; if the commit
    # fails a file without a row is left, which nothing points at.
    target = _path(user.tenant_id, file_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(target)
    return StoredFile(**row)


@router.get("/files/{file_id}", response_class=Response,
            responses={200: {"content": {"image/png": {}, "image/jpeg": {}}, "description": "The file"}},
            summary="Download a workspace image (candidate photo, symbol, slip header) for slips. All roles.")
def download_file(file_id: uuid.UUID, conn: Db, user: ReadyUser) -> Response:
    row = conn.execute(text("""SELECT storage_path, mime_type, sha256 FROM app.files
                                WHERE id = :id AND deleted_at IS NULL AND kind = ANY(CAST(:kinds AS app.file_kind[]))"""),
                       {"id": file_id, "kinds": [k.value for k in IMAGE_KINDS]}).mappings().first()
    if row is None:
        raise ApiError(404, "not_found", "File not found.")
    path = Path(get_settings().files_dir) / row["storage_path"]
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise ApiError(404, "not_found", "File not found.") from None
    return Response(content=data, media_type=row["mime_type"],
                    headers={"Cache-Control": "private, max-age=86400", "ETag": f'"{row["sha256"]}"',
                             "X-Content-Type-Options": "nosniff"})
