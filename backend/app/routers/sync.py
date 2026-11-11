"""GET /sync/pull (POST /sync/push comes in step 4.8). How sync works: context/sync.md."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ..deps import CurrentUser, Db, get_active_principal, get_ready_principal
from ..schemas import SyncPage
from ..scope import load_scope
from ..sync_pull import WATERMARK_PATTERN, pull_page

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
