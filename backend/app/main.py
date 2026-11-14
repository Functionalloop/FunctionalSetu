"""FastAPI app. Run (from backend/):  uvicorn app.main:app --reload"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from . import __version__, errors
from .config import get_settings
from .routers import (admin_logs, app_version, auth, birthdays, constituencies, data_quality, devices, families,
                      field, files, geo,
                      health, masters, me, misc, new_voters, part_notes, reports, roll_edits, rolls, settings, slips,
                      sync, turnout, users, visits, voters)
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
| 403 | `forbidden_role` | role too low (also: an admin changing an admin or super admin) |
| 403 | `own_account` | users: your own role, switch-off or password reset (use change-password) |
| 403 | `feature_off` | mobile number sheets: switched off in the workspace's settings (`feature_mobile_import`) |
| 404 | `not_found`, `no_device` | also returned for records outside your workspace or area |
| 422 | `validation_error` (with `details`), `weak_password` | |
| 409 | `version_conflict` (with `current` = the server copy) | stale `version` |
| 409 | `id_in_use` | a phone-made id is already used by a record you cannot see; make a new id |
| 409 | `username_taken`, `mobile_taken` | users: another user already has this user ID / mobile |
| 409 | `user_limit` | users: the workspace has its limit of active users (200) |
| 409 | `code_taken`, `constituency_limit` | constituencies: code used / limit of 5 active reached; colour tags: code used |
| 409 | `name_taken` | lists: another entry has this Marathi name |
| 409 | `import_in_progress` | roll import: this constituency has an import not yet applied or discarded |
| 409 | `import_closed`, `review_not_finished` | roll import: not in review (resolve, apply) or already applied (discard) / rows still wait for review (`error.pending`) |
| 409 | `voter_taken` | roll import: another row already has this voter (`error.row_no`) |
| 409 | `epic_in_use`, `serial_in_use` | roll apply: another voter has the EPIC / keeps the part and serial of these rows (`error.row_nos`); one-voter add, correct, restore: a live voter has them (`error.voter_id`) |
| 409 | `row_resolved` | mobile number sheet: the row is already matched or skipped |
| 422 | `file_too_large`, `unsupported_file` | files: over 5 MB / not a PNG or JPEG; roll import and mobile sheets: over 20 MB / not CSV or .xlsx |
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
    app.include_router(families.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    app.include_router(visits.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    app.include_router(new_voters.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    app.include_router(slips.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    app.include_router(birthdays.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    app.include_router(sync.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    app.include_router(app_version.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    app.include_router(misc.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    app.include_router(part_notes.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    app.include_router(turnout.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    app.include_router(users.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    app.include_router(constituencies.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    app.include_router(settings.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    app.include_router(masters.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    app.include_router(files.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    app.include_router(admin_logs.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    # partly built (Step 10): each route not built yet carries responses=NOT_BUILT itself
    app.include_router(rolls.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    app.include_router(roll_edits.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    app.include_router(data_quality.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    # partly built (Step 11: reports built, exports not yet): exports carry responses=NOT_BUILT themselves
    app.include_router(reports.router, prefix=API_PREFIX, responses=errors.ERROR_RESPONSES)
    # contract only until built (4.10): they answer 501 not_implemented
    for planned in (field,):
        app.include_router(planned.router, prefix=API_PREFIX, responses={**errors.ERROR_RESPONSES, **NOT_BUILT})
    return app


app = create_app()
