"""Files (9.4): POST /files (admin, images up to 5 MB), GET /files/{id} (all roles).
Generic rules: test_endpoint_rules.py."""

from __future__ import annotations

import hashlib

import pytest

from conftest import bearer, login, phone
from endpoints import PNG_1PX

API = "/api/v1"
JPEG_HEAD = b"\xff\xd8\xff\xe0" + b"\x00" * 100


def code(resp) -> str:
    return resp.json()["error"]["code"]


@pytest.fixture
def ws(make_workspace):
    return make_workspace()


@pytest.fixture
def admin(client, ws):
    return bearer(login(client, ws, "admin1").json())


def upload(client, headers, data: bytes, kind="candidate_photo", name="photo.png", mime="image/png"):
    return client.post(f"{API}/files", headers=headers, data={"kind": kind}, files={"file": (name, data, mime)})


def test_upload_and_download(client, ws, admin, set_device_status):
    r = upload(client, admin, PNG_1PX, name="../../etc/candidate.png")
    assert r.status_code == 201, r.text
    f = r.json()
    assert (f["kind"], f["mime_type"], f["size_bytes"], f["original_name"]) == (
        "candidate_photo", "image/png", len(PNG_1PX), "candidate.png")
    assert f["sha256"] == hashlib.sha256(PNG_1PX).hexdigest()

    t = login(client, ws, "survey1", device=phone("files-phone")).json()
    set_device_status(t["device"]["id"], "approved")
    got = client.get(f"{API}/files/{f['id']}", headers=bearer(t))
    assert got.status_code == 200 and got.content == PNG_1PX
    assert got.headers["content-type"] == "image/png"

    jpg = upload(client, admin, JPEG_HEAD, kind="symbol", name="s.jpg", mime="application/octet-stream")
    assert jpg.status_code == 201 and jpg.json()["mime_type"] == "image/jpeg"  # told by the bytes, not the name


def test_only_small_png_or_jpeg_images(client, admin):
    r = upload(client, admin, b"%PDF-1.4 not an image", name="x.png")
    assert r.status_code == 422 and code(r) == "unsupported_file"
    r = upload(client, admin, PNG_1PX + b"\0" * (5 * 1024 * 1024))
    assert r.status_code == 422 and code(r) == "file_too_large"
    r = upload(client, admin, PNG_1PX, kind="roll_import")
    assert r.status_code == 422


def test_another_workspaces_file_is_404(client, make_workspace, admin):
    other = make_workspace("other")
    fid = upload(client, bearer(login(client, other, "admin1").json()), PNG_1PX).json()["id"]
    assert client.get(f"{API}/files/{fid}", headers=admin).status_code == 404
