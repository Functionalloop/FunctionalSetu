"""Database access: one engine (role jansetu_app), one transaction per request.

Every transaction that touches tenant data starts with
    SELECT app.set_context(:tenant, :user, :device)
The values are transaction-local, so they vanish at COMMIT / ROLLBACK and a
pooled connection never carries one request's workspace into the next.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Connection, Engine, create_engine, text

from .config import get_settings

SET_CONTEXT = text("SELECT app.set_context(:tenant, :user, :device)")


@lru_cache
def get_engine() -> Engine:
    s = get_settings()
    return create_engine(
        s.database_url,
        pool_size=s.db_pool_size,
        max_overflow=s.db_pool_size,
        pool_pre_ping=True,
    )


def set_context(conn: Connection, tenant: uuid.UUID | None,
                user: uuid.UUID | None = None, device: uuid.UUID | None = None) -> None:
    conn.execute(SET_CONTEXT, {"tenant": tenant, "user": user, "device": device})


@contextmanager
def transaction(tenant: uuid.UUID | None = None, user: uuid.UUID | None = None,
                device: uuid.UUID | None = None) -> Iterator[Connection]:
    """BEGIN, set the RLS context (if a tenant is given), yield, COMMIT or ROLLBACK.

    With no tenant every tenant table reads as empty (RLS fails closed). Only
    login / refresh / health run like that, and login uses the SECURITY DEFINER
    function app.login_lookup to find the user.
    """
    with get_engine().begin() as conn:
        if tenant is not None:
            set_context(conn, tenant, user, device)
        yield conn
