"""Routes whose contract is final but whose code is not built yet (plan 4.10).

A stub checks login and role like the real endpoint, then answers 501 not_implemented with the
plan task that builds it. Building a task = replace `not_built(...)` with the code, remove the
route's `stub` flag in tests/endpoints.py, and add its own tests.
"""

from __future__ import annotations

from typing import Annotated, Any, NoReturn

from fastapi import Depends, Query

from .deps import POLLING_ROLES, SURVEY_ROLES, Principal, require_role, require_roles
from .errors import ApiError, ErrorResponse
from .schemas import Role

NOT_BUILT: dict[int | str, dict[str, Any]] = {
    501: {"model": ErrorResponse, "description": "Not built yet (code not_implemented); the shapes are final"}}

Supervisor = Annotated[Principal, Depends(require_role(Role.supervisor))]
Admin = Annotated[Principal, Depends(require_role(Role.admin))]
SuperAdmin = Annotated[Principal, Depends(require_role(Role.super_admin))]
Surveyor = Annotated[Principal, Depends(require_roles(SURVEY_ROLES))]
BoothAgent = Annotated[Principal, Depends(require_roles(POLLING_ROLES))]

Limit = Annotated[int, Query(ge=1, le=200)]
Cursor = Annotated[str | None, Query(description="next_cursor from the previous page")]


def not_built(task: str) -> NoReturn:
    raise ApiError(501, "not_implemented", f"Not built yet: plan task {task}. The request and response shapes are final.")
