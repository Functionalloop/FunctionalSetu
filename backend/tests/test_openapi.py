"""docs/openapi.json (what the portal builds from) must match the running API."""

from __future__ import annotations

import json

from conftest import ROOT

from app.main import create_app


def test_published_openapi_is_current():
    published = json.loads((ROOT / "docs" / "openapi.json").read_text(encoding="utf-8"))
    assert published == create_app().openapi(), \
        "API changed: run python scripts/export_openapi.py and tell the portal developer"


def test_every_route_documents_the_error_shape():
    spec = create_app().openapi()
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if path.endswith("/health"):
                continue
            assert "401" in op["responses"] and "422" in op["responses"], f"{method.upper()} {path}"
            ref = op["responses"]["401"]["content"]["application/json"]["schema"]["$ref"]
            assert ref.endswith("/ErrorResponse")
