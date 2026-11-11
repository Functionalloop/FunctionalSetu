"""One error shape for every failure: {"error": {"code": "...", "message": "..."}}."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("jansetu")


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] | None = None  # field errors, only on 422 validation_error
    current: dict[str, Any] | None = Field(None, description=(
        "Only on 409 version_conflict: the server's copy of the record (null if it does not exist yet)."))


class ErrorResponse(BaseModel):
    error: ErrorBody


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict[str, str] | None = None,
                 extra: dict[str, Any] | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.headers = status, code, message, headers
        self.extra = extra  # extra keys inside "error", e.g. {"current": {...}} on a 409


def _body(code: str, message: str, details: list[dict[str, Any]] | None = None,
          extra: dict[str, Any] | None = None) -> dict:
    err: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        err["details"] = details
    err.update(extra or {})
    return {"error": err}


# Status codes Starlette raises itself (unknown route, wrong method, ...)
_HTTP_CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
               405: "method_not_allowed", 409: "conflict", 422: "validation_error"}

# Documented on every route so generated clients know the error type.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse, "description": desc}
    for code, desc in ((400, "Bad request"), (401, "Not logged in or token expired"),
                       (403, "Not allowed"), (404, "Not found"), (409, "Version conflict"),
                       (422, "Invalid input"))
}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message, extra=exc.extra), status_code=exc.status,
                            headers=exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "error")
        return JSONResponse(_body(code, str(exc.detail)), status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
                   for e in exc.errors()]
        first = details[0] if details else None
        msg = f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}" if first else "Invalid input"
        return JSONResponse(_body("validation_error", msg, details), status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", exc_info=exc)
        return JSONResponse(_body("internal_error", "Something went wrong on the server."), status_code=500)
