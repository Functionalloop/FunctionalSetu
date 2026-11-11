"""The workspace's settings as clients see them (GET /me and GET /sync/pull send the same thing)."""

from __future__ import annotations

from sqlalchemy import Connection, text

from .schemas import CANDIDATE_FIELDS, WorkspaceSettings


def load_workspace_settings(conn: Connection) -> WorkspaceSettings | None:
    """Settings of the request's workspace (RLS). Candidate fields are blanked while
    code_of_conduct_mode is on. None if the workspace has no settings row yet."""
    row = conn.execute(text("SELECT * FROM app.tenant_settings")).mappings().first()
    if row is None:
        return None
    data = {k: row[k] for k in WorkspaceSettings.model_fields}
    if data["code_of_conduct_mode"]:
        data.update(dict.fromkeys(CANDIDATE_FIELDS))
    return WorkspaceSettings(**data)
