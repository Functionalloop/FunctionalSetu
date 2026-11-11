"""Area scope: which part of the workspace a user may see and edit.

    super_admin  the whole workspace
    admin        their own constituency (users.local_body_id)
    others       their assigned wards and booths (user_area_assignments)

Each area in the scope covers everything below it (a ward covers its booths and
sections). RLS already limits every query to the workspace; the scope narrows it
to the user's area. A record outside the scope is answered with 404, exactly like
a record in another workspace, so a user cannot tell the two apart.

Use in a route:

    def list_things(conn: Db, user: ReadyUser, scope: UserScope):
        cond, params = scope.filter("v.geo_path")
        conn.execute(text(f"SELECT ... FROM app.voters v WHERE {cond}"), params)
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Connection, text

from .deps import Db, Principal, ReadyUser
from .errors import ApiError
from .schemas import Role

_COLUMN_RE = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)?$")

# Area g and every area above it are active. Switching off a ward hides its booths too.
_ALL_ACTIVE = """NOT EXISTS (SELECT 1 FROM app.geo_units x
                             WHERE x.tenant_id = g.tenant_id AND x.path @> g.path AND NOT x.is_active)"""


@dataclass(frozen=True)
class Scope:
    whole_workspace: bool
    area_ids: frozenset[uuid.UUID]  # the areas the scope was built from (assigned or own constituency)
    paths: tuple[str, ...]          # their ltree paths, with paths inside another one removed
    excluded: tuple[str, ...] = ()  # paths of switched-off areas: they and everything below are left out

    @property
    def is_empty(self) -> bool:
        return not self.whole_workspace and not self.paths

    def filter(self, column: str, param: str = "scope_paths") -> tuple[str, dict]:
        """SQL condition that keeps rows whose ltree `column` lies in the scope.

        `column` is an ltree column such as geo_units.path or voters.geo_path. It is
        put into the SQL as written, so pass only names from code, never user input.
        """
        if not _COLUMN_RE.match(column) or not re.match(r"^[a-z_][a-z0-9_]*$", param):
            raise ValueError(f"bad column or parameter name: {column!r}, {param!r}")
        if self.is_empty:
            return "FALSE", {}
        conds, params = [], {}
        if not self.whole_workspace:
            conds.append(f"{column} <@ CAST(:{param} AS ltree[])")
            params[param] = list(self.paths)
        if self.excluded:
            conds.append(f"NOT ({column} <@ CAST(:{param}_off AS ltree[]))")
            params[f"{param}_off"] = list(self.excluded)
        return (" AND ".join(conds) or "TRUE"), params

    def contains_path(self, path: str) -> bool:
        """Is this ltree path (as text) in the scope?"""
        def under(p: str) -> bool:
            return path == p or path.startswith(p + ".")
        if any(under(p) for p in self.excluded):
            return False
        return self.whole_workspace or any(under(p) for p in self.paths)


def _outermost(paths: list[str]) -> tuple[str, ...]:
    """Drop paths that sit inside another path in the list (a booth under an assigned ward)."""
    keep = []
    for p in sorted(set(paths), key=lambda s: (s.count("."), s)):
        if not any(p == k or p.startswith(k + ".") for k in keep):
            keep.append(p)
    return tuple(keep)


def load_scope(conn: Connection, user: Principal) -> Scope:
    """Build the scope for a user. `conn` must have the user's RLS context set."""
    # Switched-off areas of this workspace (RLS): hidden with everything below them, for every role.
    excluded = _outermost(list(conn.execute(text(
        "SELECT path::text FROM app.geo_units WHERE NOT is_active")).scalars()))
    if user.role == Role.super_admin:
        return Scope(True, frozenset(), (), excluded)

    if user.role == Role.admin:
        rows = conn.execute(text("""
            SELECT id, path::text AS path FROM app.geo_units
             WHERE id = :lb AND level = 'local_body' AND is_active
        """), {"lb": user.local_body_id}).all()
    else:
        # Assigned areas inside the user's own constituency, with no inactive area at or above them.
        rows = conn.execute(text(f"""
            SELECT g.id, g.path::text AS path
              FROM app.user_area_assignments a
              JOIN app.geo_units g  ON g.tenant_id = a.tenant_id AND g.id = a.geo_unit_id
              JOIN app.geo_units lb ON lb.tenant_id = a.tenant_id AND lb.id = :lb
             WHERE a.user_id = :u AND g.path <@ lb.path AND {_ALL_ACTIVE}
        """), {"u": user.user_id, "lb": user.local_body_id}).all()

    return Scope(False, frozenset(r.id for r in rows), _outermost([r.path for r in rows]), excluded)


def get_scope(conn: Db, user: ReadyUser) -> Scope:
    return load_scope(conn, user)


UserScope = Annotated[Scope, Depends(get_scope)]


def require_area(conn: Connection, scope: Scope, geo_unit_id: uuid.UUID) -> str:
    """404 unless the area exists, it and the areas above it are active, and it lies in the scope.
    Returns its ltree path."""
    path = conn.execute(text(f"SELECT g.path::text FROM app.geo_units g WHERE g.id = :id AND {_ALL_ACTIVE}"),
                        {"id": geo_unit_id}).scalar()
    if path is None or not scope.contains_path(path):
        raise ApiError(404, "not_found", "Area not found.")
    return path
