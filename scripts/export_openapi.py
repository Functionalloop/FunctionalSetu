"""Write the API contract to docs/openapi.json (the portal generates its client from it).

    python scripts/export_openapi.py           write the file
    python scripts/export_openapi.py --check   exit 1 if the file is out of date

Run after any endpoint change, commit the file and tell the portal developer.
backend/tests/test_openapi.py fails while the file is stale. No database needed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "openapi.json"


def render() -> str:
    # Building the schema needs no secrets; placeholders keep Settings() happy without a .env.
    os.environ.setdefault("JWT_SECRET", "x" * 32)
    os.environ.setdefault("JANSETU_APP_PASSWORD", "unused")
    sys.path.insert(0, str(ROOT / "backend"))
    from app.main import create_app

    return json.dumps(create_app().openapi(), indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    spec = render()
    if args.check:
        # Compare as JSON, not text: git may turn LF into CRLF on Windows checkouts.
        current = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else None
        if current != json.loads(spec):
            sys.exit("docs/openapi.json is out of date: run python scripts/export_openapi.py")
        print("docs/openapi.json is up to date")
        return
    OUT.write_text(spec, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
