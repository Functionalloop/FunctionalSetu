"""GET /sync/pull (POST /sync/push comes in step 4.8). How sync works: context/sync.md."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ..deps import Db, ReadyUser
from ..schemas import SyncPage
from ..scope import UserScope
from ..sync_pull import first_download_page

router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/pull", response_model=SyncPage,
            summary="First download of the user's area, in pages (see SyncPage). All roles, from the app.")
def pull(
    conn: Db, user: ReadyUser, scope: UserScope,
    cursor: Annotated[str | None, Query(description="next_cursor from the previous page; none = start")] = None,
    limit: Annotated[int, Query(ge=1, le=2000, description="Voters or surveys per page")] = 1000,
) -> SyncPage:
    return first_download_page(conn, scope, cursor, limit)
