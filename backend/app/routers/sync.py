"""GET /sync/pull and POST /sync/push. How sync works: context/sync.md."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from ..deps import CurrentUser, Db, ReadyUser, get_active_principal, get_ready_principal
from ..schemas import PushRequest, PushResponse, SyncPage
from ..schemas_field import Conflict, ConflictPage, ConflictResolution, ConflictStatus
from ..stubs import NOT_BUILT, Cursor, Limit, Surveyor, not_built
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
    return pull_page(conn, load_scope(conn, ready), since, cursor, limit)


@router.post("/push", response_model=PushResponse,
             summary="Apply a batch of outbox items; one result per item (applied, conflict, rejected). "
                     "All roles, from an approved phone; each item's own role rules apply.")
def push(body: PushRequest, conn: Db, user: ReadyUser, scope: UserScope) -> PushResponse:
    return PushResponse(results=apply_push(conn, user, scope, body.items))


@router.get("/conflicts", response_model=ConflictPage, responses=NOT_BUILT,
            summary="Conflicts to review. A surveyor sees their own; supervisor and above all in their area. "
                    "Survey roles. (Plan 7.10; who resolves is the gap-table proposal.)")
def list_conflicts(conn: Db, user: Surveyor, status: ConflictStatus = ConflictStatus.open,
                   entity_id: uuid.UUID | None = None, limit: Limit = 50, cursor: Cursor = None) -> ConflictPage:
    not_built("7.10")


@router.post("/conflicts/{conflict_id}/resolve", response_model=Conflict, responses=NOT_BUILT,
             summary="Keep the phone's value (written with a new version) or the server's. Survey roles, "
                     "same rule as the list.")
def resolve_conflict(conflict_id: uuid.UUID, body: ConflictResolution, conn: Db, user: Surveyor) -> Conflict:
    not_built("7.10")
