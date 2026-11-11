"""Opaque list cursors: the sort key of the last row, as URL-safe base64 JSON.

    encode_cursor([part_no, booth_no, serial_no, str(id)])  ->  "WzEsIDEsIDcsICIuLi4iXQ"
    decode_cursor(cursor, 4)                                ->  [1, 1, 7, "..."]  or 400 invalid_cursor
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from .errors import ApiError


def encode_cursor(key: list[Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(key).encode()).decode().rstrip("=")


def invalid_cursor() -> ApiError:
    return ApiError(400, "invalid_cursor", "This cursor is not valid; start again without it.")


def decode_cursor(cursor: str, length: int) -> list[Any]:
    try:
        key = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except (ValueError, TypeError, binascii.Error):
        raise invalid_cursor() from None
    if not isinstance(key, list) or len(key) != length:
        raise invalid_cursor()
    return key
