"""GET /sync/pull and POST /sync/push. How sync works: context/sync.md."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from .. import conflicts

from ..deps import SURVEY_ROLES, CurrentUser, Db, ReadyUser, get_active_principal, get_ready_principal
from ..schemas import PushRequest, PushResponse, SyncPage
from ..schemas_field import Conflict, ConflictPage, ConflictResolution, ConflictStatus
from ..stubs import Cursor, Limit, Surveyor
from ..scope import UserScope, load_scope
from ..sync_pull import WATERMARK_PATTERN, pull_page
from ..sync_push import push as apply_push

router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/pull", response_model=SyncPage,
            summary="First download (no since) or changes since a watermark, in pages. All roles, from the app. "
                    "A blocked phone gets wipe=true.")
def pull(
    conn: Db, user: CurrentUser,
    since: Annotated[str | None, Query(pattern=WATERMARK_PATTERN, description=(
        "watermark from the last complete pull; leave out for a first download"))] = None,
    cursor: Annotated[str | None, Query(description=(
        "next_cursor from the previous page; it carries `since`, so `since` is ignored with a cursor"))] = None,
    limit: Annotated[int, Query(ge=1, le=2000, description="Voters, surveys or ids per page")] = 1000,
) -> SyncPage:
    # Other data endpoints answer a blocked phone with 403; the pull tells it to wipe instead,
    # so a lost phone deletes its copy the next time it is online.
    if user.device_status in ("blocked", "wiped"):
        return SyncPage(watermark="0", next_cursor=None, wipe=True)
    ready = get_ready_principal(get_active_principal(user))  # 403 device_pending / password_change_required
    return pull_page(conn, load_scope(conn, ready), since, cursor, limit, survey_role=ready.role in SURVEY_ROLES)


@router.post("/push", response_model=PushResponse,
             summary="Apply a batch of outbox items; one result per item (applied, conflict, rejected). "
                     "All roles, from an approved phone; each item's own role rules apply.")
def push(body: PushRequest, conn: Db, user: ReadyUser, scope: UserScope) -> PushResponse:
    return PushResponse(results=apply_push(conn, user, scope, body.items))


@router.get("/conflicts", response_model=ConflictPage,
            summary="Conflicts to review, newest first. A surveyor sees the rows of their own pushes; supervisor "
                    "and above all in their area. Survey roles.")
def list_conflicts(conn: Db, user: Surveyor, scope: UserScope, status: ConflictStatus = ConflictStatus.open,
                   entity_id: uuid.UUID | None = None, limit: Limit = 50, cursor: Cursor = None) -> ConflictPage:
    return conflicts.list_conflicts(conn, user, scope, status, entity_id, limit, cursor)


@router.post("/conflicts/{conflict_id}/resolve", response_model=Conflict,
             summary="Keep the phone's value (that field is written on the current record with a new version; "
                     "422 if the record would break a rule) or the server's (nothing written). 409 conflict_resolved "
                     "if already decided. Survey roles, same rule as the list.")
def resolve_conflict(conflict_id: uuid.UUID, body: ConflictResolution, conn: Db, user: Surveyor,
                     scope: UserScope) -> Conflict:
    return conflicts.resolve_conflict(conn, user, scope, conflict_id, body.keep)
