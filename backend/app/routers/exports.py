"""Exports (plan 11.2): POST /exports, GET /exports/{id}, GET /exports/{id}/download. Supervisor and above.

POST checks the request (app/export_jobs.py `parse`: 422 / 404) and answers 202 at once; the worker writes
the file. An export is seen by the user who asked for it, by an admin of that user's constituency and
by a super admin (as mobile number sheets): anyone else gets 404. `status` is `running` while its job
runs. Download: only when done (else 409 export_not_ready); the file is sent as an attachment.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Response, status
from sqlalchemy import Connection, text

from ..deps import Db, Principal
from ..errors import ApiError
from ..export_jobs import KIND, PDF_MIME, XLSX_MIME, parse
from ..schemas import Role
from ..schemas_roll import Export, ExportIn
from ..scope import UserScope
from ..stubs import Supervisor
from ..worker import enqueue
from .files import stored_path

router = APIRouter(tags=["reports"])

_SELECT = """
    SELECT e.id, e.kind, e.format, e.status::text AS status, e.row_count, e.page_count, e.error, e.created_at,
           e.finished_at, f.storage_path, f.mime_type, f.original_name,
           (SELECT j.status::text FROM app.jobs j WHERE j.ref_id = e.id AND j.kind = :kind
             ORDER BY j.created_at DESC LIMIT 1) AS job_status
      FROM app.exports e
      JOIN app.users u ON u.tenant_id = e.tenant_id AND u.id = e.created_by
      LEFT JOIN app.files f ON f.tenant_id = e.tenant_id AND f.id = e.file_id"""


def _find(conn: Connection, user: Principal, export_id: uuid.UUID) -> Any:
    """The export, if the caller may see it: own, an admin's team (own constituency), or a super admin."""
    row = conn.execute(text(f"""{_SELECT}
         WHERE e.id = :id AND (e.created_by = :me OR :is_super OR (:is_admin AND u.local_body_id = :lb))"""),
                       {"id": export_id, "me": user.user_id, "kind": KIND, "is_super": user.role == Role.super_admin,
                        "is_admin": user.role == Role.admin, "lb": user.local_body_id}).mappings().first()
    if row is None:
        raise ApiError(404, "not_found", "Export not found.")
    return row


def _to_export(r: Any) -> Export:
    st = "running" if r["status"] == "queued" and r["job_status"] == "running" else r["status"]
    return Export(**{k: r[k] for k in ("id", "kind", "format", "row_count", "page_count", "error", "created_at",
                                       "finished_at")}, status=st)


@router.post("/exports", response_model=Export, status_code=status.HTTP_202_ACCEPTED,
             summary="Start a PDF or Excel export of a list (filters and columns) or a report; poll it. Supervisor.")
def start_export(body: ExportIn, conn: Db, user: Supervisor, scope: UserScope) -> Export:
    spec = parse(conn, scope, body)
    kept = spec.stored()
    eid = conn.execute(text("""
        INSERT INTO app.exports (tenant_id, kind, format, language, filter, columns, options, created_by)
        VALUES (app.current_tenant_id(), :kind, :format, CAST(:lang AS app.lang), CAST(:filter AS jsonb),
                CAST(:columns AS text[]), CAST(:options AS jsonb), :by)
        RETURNING id"""), {"kind": spec.kind.value, "format": spec.format.value, "lang": spec.language,
                           "filter": json.dumps(kept["filter"]), "columns": kept["columns"],
                           "options": json.dumps(kept["options"]), "by": user.user_id}).scalar_one()
    enqueue(conn, KIND, eid)
    return _to_export(_find(conn, user, eid))


@router.get("/exports/{export_id}", response_model=Export, summary="An export's status. Supervisor.")
def get_export(export_id: uuid.UUID, conn: Db, user: Supervisor) -> Export:
    return _to_export(_find(conn, user, export_id))


@router.get("/exports/{export_id}/download", response_class=Response,
            responses={200: {"content": {PDF_MIME: {}, XLSX_MIME: {}}, "description": "The finished file"}},
            summary="Download a finished export (409 export_not_ready before). Supervisor.")
def download_export(export_id: uuid.UUID, conn: Db, user: Supervisor) -> Response:
    r = _find(conn, user, export_id)
    if r["status"] != "done" or r["storage_path"] is None:
        raise ApiError(409, "export_not_ready", "The file is not ready." if r["status"] != "failed"
                       else "This export failed; start a new one.")
    try:
        data = stored_path(r["storage_path"]).read_bytes()
    except FileNotFoundError:
        raise ApiError(404, "not_found", "The file is no longer on the server; start a new export.") from None
    name = r["original_name"] or f"export.{r['format']}"
    return Response(content=data, media_type=r["mime_type"],
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "private, no-store",
                             "X-Content-Type-Options": "nosniff"})
