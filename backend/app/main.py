"""FastAPI app. Run (from backend/):  uvicorn app.main:app --reload"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from . import __version__, errors
from .config import get_settings
from .routers import admin, auth, devices, field, geo, health, me, misc, reports, rolls, sync, turnout, voters
from .stubs import NOT_BUILT

API_PREFIX = "/api/v1"

DESCRIPTION = """
JANSETU API for the Android app and the web portal.

**Auth.** `POST /auth/login` returns an access token (15 min) and a refresh token.
Send `Authorization: Bearer <access_token>`. On `401 token_expired` call `/auth/refresh`;
each refresh returns a new refresh token and the old one stops working.

**Errors.** Every error is `{"error": {"code": "...", "message": "..."}}`. Codes so far:

| Status | Code | Meaning |
|---|---|---|
| 400 | `wrong_current_password` | change-password: current password wrong |
| 400 | `invalid_cursor` | list cursor is damaged; start again without it |
| 401 | `invalid_credentials` | wrong workspace code, user ID or password |
| 401 | `not_authenticated`, `invalid_token` | no / bad access token |
| 401 | `token_expired` | call `/auth/refresh` |
| 401 | `invalid_refresh_token` | log in again |
| 401 | `session_ended` | logged out or ended by a password change; log in again |
| 403 | `account_locked` | too many wrong passwords; try later |
| 403 | `account_disabled`, `workspace_suspended` | access switched off |
| 403 | `device_required` | surveyors / booth agents must log in from the app; sync push needs a phone login |
| 403 | `device_pending` | phone waits for admin approval; poll `/devices/me` |
| 403 | `device_blocked` | phone blocked: wipe local data |
| 403 | `password_change_required` | call `/auth/change-password` first |
| 403 | `forbidden_role` | role too low |
| 404 | `not_found`, `no_device` | also returned for records outside your workspace or area |
| 422 | `validation_error` (with `details`), `weak_password` | |
| 409 | `version_conflict` (with `current` = the server copy) | stale `version` |
| 501 | `not_implemented` | in the contract, not built yet (the shapes are final) |

IDs are UUIDs; dates are ISO 8601 UTC.
"""


def _operation_id(route: APIRoute) -> str:
    return route.name  # function names: login, refresh, get_me, ... (stable names for generated clients)


def create_app() -> FastAPI:
    app = FastAPI(
        title="JANSETU API",
        version=__version__,
        description=DESCRIPTION,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        generate_unique_id_function=_operation_id,
    )
    errors.install(app)

    origins = get_settings().cors_origin_list
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"],
                           allow_headers=["Authorization", "Content-Type"])

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    app.include_router(me.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    app.include_router(devices.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    app.include_router(geo.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    app.include_router(voters.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    app.include_router(sync.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    # contract only until built (4.10): they answer 501 not_implemented
    for planned in (field, misc, turnout, admin, rolls, reports):
        app.include_router(planned.router, prefix=API_PREFIX, responses={**errors.ERROR_RESPONSES, **NOT_BUILT})
    return app


app = create_app()
