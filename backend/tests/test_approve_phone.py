"""scripts/approve_phone.py: the first admin phone, which no approved admin can approve yet. Fake data only."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import bearer, login, phone

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from approve_phone import ApproveError, approve_phone  # noqa: E402

API = "/api/v1"


def status(owner_conn, device_id) -> str:
    return owner_conn.execute("SELECT status FROM app.devices WHERE id = %s", (device_id,)).fetchone()[0]


@pytest.mark.parametrize("who", ["admin1", "boss"])
def test_first_admin_phone_then_admin_approves_a_surveyor_in_the_app(client, make_workspace, owner_conn, who):
    ws = make_workspace("ap")
    admin = login(client, ws, who, device=phone(f"{who}-phone-1")).json()
    assert client.get(f"{API}/devices", headers=bearer(admin)).status_code == 403  # own phone still waiting

    assert approve_phone(owner_conn, ws.code, who) == ["Test Phone, Android 14"]
    assert status(owner_conn, admin["device"]["id"]) == "approved"

    # now the admin approves a surveyor's phone from the app, as in the demo
    surveyor = login(client, ws, "survey1", device=phone("surveyor-phone")).json()
    waiting = client.get(f"{API}/devices", params={"status": "pending"}, headers=bearer(admin)).json()["items"]
    assert [d["id"] for d in waiting] == [surveyor["device"]["id"]]
    r = client.post(f"{API}/devices/{surveyor['device']['id']}/approve", headers=bearer(admin))
    assert r.status_code == 200 and r.json()["status"] == "approved"


def test_field_workers_and_blocked_phones_are_refused(client, make_workspace, owner_conn, set_device_status):
    ws = make_workspace("ap")
    s = login(client, ws, "survey1", device=phone("surveyor-phone-1")).json()
    with pytest.raises(ApproveError, match="in the app"):
        approve_phone(owner_conn, ws.code, "survey1")
    assert status(owner_conn, s["device"]["id"]) == "pending"

    a = login(client, ws, "admin1", device=phone("admin-phone-1")).json()
    set_device_status(a["device"]["id"], "blocked")
    with pytest.raises(ApproveError, match="no phone waiting"):
        approve_phone(owner_conn, ws.code, "admin1")
    assert status(owner_conn, a["device"]["id"]) == "blocked"


def test_unknown_user_or_workspace(make_workspace, owner_conn):
    ws = make_workspace("ap")
    with pytest.raises(ApproveError, match="not found"):
        approve_phone(owner_conn, ws.code, "nobody")
    with pytest.raises(ApproveError, match="Workspace"):
        approve_phone(owner_conn, "no-such-workspace", "admin1")
