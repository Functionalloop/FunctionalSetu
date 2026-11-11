"""4.10: every endpoint in docs/02_tech_stack_and_api.md is in the API (built or as a 501 stub)."""

from __future__ import annotations

import re
from pathlib import Path

from app.main import API_PREFIX, create_app

DOC = Path(__file__).resolve().parents[2] / "docs" / "02_tech_stack_and_api.md"

# In the API document but deliberately not built (docs/plan.md, "not in the SRS"): decided 11 Nov.
NOT_IN_SCOPE = {("GET", "/saved-filters"), ("POST", "/saved-filters"), ("DELETE", "/saved-filters/{}")}
# One document path served as one explicit route per list (each list has its own shape and key).
EXPANDED = {"/masters/{}": ["/masters/castes", "/masters/professions", "/masters/color-tags",
                            "/masters/custom-fields", "/masters/message-templates"],
            "/masters/{}/{}": ["/masters/castes/{}", "/masters/professions/{}", "/masters/color-tags/{}",
                               "/masters/custom-fields/{}", "/masters/message-templates/{}"]}


def norm(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def doc_endpoints() -> set[tuple[str, str]]:
    out = set()
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("| `"):
            cell = line.split("|")[1]
            out |= {(m, norm(p)) for m, p in re.findall(r"`(GET|POST|PUT|PATCH|DELETE) (/[^`]*)`", cell)}
    return out


def api_endpoints() -> set[tuple[str, str]]:
    paths = create_app().openapi()["paths"]
    return {(m.upper(), norm(p.removeprefix(API_PREFIX))) for p, ops in paths.items() for m in ops}


def test_every_documented_endpoint_is_in_the_api():
    served = api_endpoints()
    missing = []
    for method, path in sorted(doc_endpoints() - NOT_IN_SCOPE):
        options = EXPANDED.get(path, [path])
        # PATCH /masters/{list}/{id}: the custom-field and template lists are edited, never added to
        if not any((method, o) in served for o in options):
            missing.append(f"{method} {path}")
    assert missing == [], f"documented but not in the API: {missing}"
    assert len(doc_endpoints()) >= 85  # the document parsed (about 90 endpoints)


def test_api_has_nothing_outside_the_document_except_known_additions():
    documented = doc_endpoints() | {(m, o) for (m, p) in doc_endpoints() for o in EXPANDED.get(p, [])}
    extra = {e for e in api_endpoints() - documented}
    # added on purpose: health check, admin view of phones, plan gap-table proposals (GET /files/{id},
    # mobile row review), masters edited by key
    assert extra == {("GET", "/files/{}"), ("POST", "/mobile-imports/{}/rows/{}/resolve")}, extra
