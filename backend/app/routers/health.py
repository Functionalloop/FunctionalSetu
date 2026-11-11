"""GET /health: is the API up and can it reach PostgreSQL."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .. import __version__
from ..db import get_engine
from ..errors import ErrorResponse
from ..schemas import Health

router = APIRouter(tags=["system"])
log = logging.getLogger("jansetu")


@router.get("/health", response_model=Health, summary="Server check for monitoring",
            responses={503: {"model": ErrorResponse, "description": "Database unreachable"}})
def health():
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        log.exception("health check: database unreachable")
        return JSONResponse({"error": {"code": "database_unavailable", "message": "Database is not reachable."}},
                            status_code=503)
    return Health(status="ok", database="ok", version=__version__)
