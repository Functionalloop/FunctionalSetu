"""POST /devices/{id}/approve and /devices/{id}/block (admin and super admin).

Scope: RLS keeps every other workspace out (their phones read as 404). Inside the
workspace, a super admin manages every phone; an admin only phones of users in
their own constituency (users.local_body_id). Anything outside scope is 404,
so an admin cannot learn which device ids exist elsewhere.

Blocking does not end sessions here: from the next request the phone gets
403 device_blocked everywhere except /devices/me (which says wipe_required),
and its next /auth/refresh revokes the session.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import Connection, text

from ..deps import Db, Principal, require_role
from ..errors import ApiError
from ..schemas import AdminDevice, BlockDeviceRequest, Role

router = APIRouter(prefix="/devices", tags=["devices"])

AdminUser = Annotated[Principal, Depends(require_role(Role.admin))]

_RETURNING = """RETURNING d.id, d.user_id, d.status, d.model, d.os_version, d.app_version_code, d.requested_at,
                          d.decided_at, d.decided_by, d.blocked_reason,
                          (d.status IN ('blocked', 'wiped') AND d.wipe_requested_at IS NOT NULL) AS wipe_required"""


def _update_in_scope(conn: Connection, admin: Principal, device_id: uuid.UUID, set_sql: str,
                     params: dict) -> AdminDevice:
    row = conn.execute(text(f"""
        UPDATE app.devices d SET {set_sql}, decided_by = :admin, decided_at = now()
          FROM app.users u
         WHERE d.id = :id AND u.tenant_id = d.tenant_id AND u.id = d.user_id
           AND (:is_super OR u.local_body_id = :lb)
        {_RETURNING}
    """), {**params, "id": device_id, "admin": admin.user_id,
           "is_super": admin.role == Role.super_admin, "lb": admin.local_body_id}).mappings().first()
    if row is None:
        raise ApiError(404, "not_found", "Device not found.")
    return AdminDevice(**row)


@router.post("/{device_id}/approve", response_model=AdminDevice,
             summary="Approve a phone (also un-blocks a blocked one). Admin and above.")
def approve_device(device_id: uuid.UUID, conn: Db, admin: AdminUser) -> AdminDevice:
    return _update_in_scope(conn, admin, device_id,
                            "status = 'approved', blocked_reason = NULL, wipe_requested_at = NULL", {})


@router.post("/{device_id}/block", response_model=AdminDevice,
             summary="Block a lost phone and tell it to wipe its data. Admin and above.")
def block_device(device_id: uuid.UUID, conn: Db, admin: AdminUser,
                 body: BlockDeviceRequest | None = None) -> AdminDevice:
    return _update_in_scope(
        conn, admin, device_id,
        "status = 'blocked', blocked_reason = :reason, wipe_requested_at = coalesce(d.wipe_requested_at, now())",
        {"reason": body.reason if body else None})
