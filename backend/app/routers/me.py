"""GET /me and GET /devices/me."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from ..deps import CurrentUser, Db, ReadyUser
from ..errors import ApiError
from ..scope import load_scope
from ..workspace_settings import load_workspace_settings
from ..schemas import Area, DeviceDetail, Me, MeUser, Role, WorkspaceSummary

router = APIRouter(tags=["me"])

_AREA_COLS = "g.id, g.parent_id, g.level, g.code, g.number, g.name_mr, g.name_en"


@router.get("/me", response_model=Me, summary="Logged-in user, workspace, assigned areas and settings")
def get_me(conn: Db, user: ReadyUser) -> Me:
    u = conn.execute(text("""
        SELECT id, username, full_name_en, full_name_mr, role, mobile, local_body_id,
               preferred_language, terms_version
          FROM app.users WHERE id = :u
    """), {"u": user.user_id}).mappings().one()
    ws = conn.execute(text("SELECT id, code, name_en, name_mr FROM app.tenants")).mappings().one()

    if user.role == Role.super_admin:
        areas_sql = f"""SELECT {_AREA_COLS} FROM app.geo_units g
                         WHERE g.level = 'local_body' AND g.is_active ORDER BY g.sort_order, g.name_mr"""
    elif user.role == Role.admin:
        areas_sql = f"SELECT {_AREA_COLS} FROM app.geo_units g WHERE g.id = :lb AND g.is_active"
    else:  # the same areas the scope uses (active, inside the user's constituency)
        areas_sql = f"""SELECT {_AREA_COLS} FROM app.geo_units g WHERE g.id = ANY(:ids)
                         ORDER BY app.geo_level_rank(g.level), g.sort_order, g.name_mr"""
    ids = list(load_scope(conn, user).area_ids) if user.role not in (Role.super_admin, Role.admin) else []
    areas = conn.execute(text(areas_sql), {"u": user.user_id, "lb": user.local_body_id, "ids": ids}
                         ).mappings().all()

    settings = load_workspace_settings(conn)

    return Me(user=MeUser(**u), workspace=WorkspaceSummary(**ws),
              areas=[Area(**a) for a in areas], settings=settings)


@router.get("/devices/me", response_model=DeviceDetail, tags=["devices"],
            summary="This phone's status: pending, approved, blocked or wiped")
def get_my_device(conn: Db, user: CurrentUser) -> DeviceDetail:
    if user.device_id is None:
        raise ApiError(404, "no_device", "This login is not from a phone.")
    d = conn.execute(text("""
        SELECT id, status, model, os_version, app_version_code, requested_at, decided_at,
               (status IN ('blocked', 'wiped') AND wipe_requested_at IS NOT NULL) AS wipe_required
          FROM app.devices WHERE id = :d
    """), {"d": user.device_id}).mappings().one()
    return DeviceDetail(**d)
