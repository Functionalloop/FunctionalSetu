"""GET /geo/tree: the area tree (constituency > ward > booth > section) for the user's scope."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import text

from ..deps import Db, ReadyUser
from ..schemas import GeoNode, GeoTree
from ..scope import UserScope

router = APIRouter(prefix="/geo", tags=["geo"])


@router.get("/tree", response_model=GeoTree, summary="Area tree for the user's area. All roles.")
def get_geo_tree(conn: Db, user: ReadyUser, scope: UserScope) -> GeoTree:
    cond, params = scope.filter("g.path")
    rows = conn.execute(text(f"""
        SELECT g.id, g.parent_id, g.level, g.code, g.number, g.name_mr, g.name_en,
               g.address_mr, g.address_en, g.ac_no, g.path::text AS path
          FROM app.geo_units g
         WHERE g.is_active AND {cond}
         ORDER BY nlevel(g.path), g.sort_order, g.number NULLS LAST, g.code, g.name_mr
    """), params).mappings().all()

    # Parents come before children (ordered by depth). A node is a root only if it is one of
    # the scope's top areas; any other node whose parent is missing (inactive) is dropped.
    roots_paths = set(scope.paths)
    nodes: dict[uuid.UUID, GeoNode] = {}
    roots: list[GeoNode] = []
    for r in rows:
        node = GeoNode(**{k: v for k, v in r.items() if k != "path"})
        is_root = r["path"] in roots_paths if not scope.whole_workspace else r["parent_id"] is None
        if is_root:
            roots.append(node)
        elif r["parent_id"] in nodes:
            nodes[r["parent_id"]].children.append(node)
        else:
            continue
        nodes[r["id"]] = node
    return GeoTree(roots=roots)
