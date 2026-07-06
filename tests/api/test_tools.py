"""Tool CRUD + filter integration tests."""

from __future__ import annotations

import pytest

from tests.api.conftest import auth

pytestmark = pytest.mark.integration


def _mk(client, users, ttype, short_id="EM-1", **over):
    body = {"short_id": short_id, "tool_type_id": ttype, "diameter_mm": "6.3500",
            "flute_count": 4, "requires_tsc": False}
    body.update(over)
    return client.post("/api/tooling/tools", json=body, headers=auth(users["setter"]))


def test_create_and_get(client, seed_users, tool_type_id):
    r = _mk(client, seed_users, tool_type_id, short_id="EM-1/4-4F-001")
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert r.json()["tool_type"]["code"] == "em_square"
    g = client.get(f"/api/tooling/tools/{tid}", headers=auth(seed_users["viewer"]))
    assert g.status_code == 200
    assert g.json()["short_id"] == "EM-1/4-4F-001"
    assert g.json()["diameter_mm"] == "6.3500"


def test_duplicate_short_id_conflicts(client, seed_users, tool_type_id):
    assert _mk(client, seed_users, tool_type_id, short_id="DUP").status_code == 201
    r = _mk(client, seed_users, tool_type_id, short_id="DUP")
    assert r.status_code == 409


def test_get_missing_404(client, seed_users):
    import uuid
    r = client.get(f"/api/tooling/tools/{uuid.uuid4()}", headers=auth(seed_users["viewer"]))
    assert r.status_code == 404


def test_patch_updates(client, seed_users, tool_type_id):
    tid = _mk(client, seed_users, tool_type_id, short_id="P-1").json()["id"]
    r = client.patch(f"/api/tooling/tools/{tid}", json={"notes": "updated", "coating": "tialn"},
                     headers=auth(seed_users["setter"]))
    assert r.status_code == 200
    assert r.json()["notes"] == "updated"
    assert r.json()["coating"] == "tialn"


def test_duplicate_endpoint(client, seed_users, tool_type_id):
    tid = _mk(client, seed_users, tool_type_id, short_id="SRC-1", vendor="Helical").json()["id"]
    r = client.post(f"/api/tooling/tools/{tid}/duplicate", json={"short_id": "SRC-2"},
                    headers=auth(seed_users["setter"]))
    assert r.status_code == 201
    assert r.json()["short_id"] == "SRC-2"
    assert r.json()["vendor"] == "Helical"


def test_retire_and_exclusion(client, seed_users, tool_type_id):
    tid = _mk(client, seed_users, tool_type_id, short_id="R-1").json()["id"]
    r = client.post(f"/api/tooling/tools/{tid}/retire", json={"reason": "broken"},
                    headers=auth(seed_users["setter"]))
    assert r.status_code == 200
    assert r.json()["retired_at"] is not None
    # default list excludes retired
    lst = client.get("/api/tooling/tools?q=R-1", headers=auth(seed_users["viewer"])).json()
    assert lst["total"] == 0
    lst2 = client.get("/api/tooling/tools?q=R-1&include_retired=true",
                      headers=auth(seed_users["viewer"])).json()
    assert lst2["total"] == 1


def test_list_filters(client, seed_users, tool_type_id):
    _mk(client, seed_users, tool_type_id, short_id="F-A", diameter_mm="6.0", flute_count=4)
    _mk(client, seed_users, tool_type_id, short_id="F-B", diameter_mm="12.0", flute_count=2)
    h = auth(seed_users["viewer"])
    assert client.get("/api/tooling/tools?diameter_mm_min=10", headers=h).json()["total"] == 1
    assert client.get("/api/tooling/tools?flute_count=4", headers=h).json()["total"] == 1
    assert client.get("/api/tooling/tools?q=F-", headers=h).json()["total"] == 2


def test_create_bad_tool_type_404(client, seed_users):
    import uuid
    r = _mk(client, seed_users, str(uuid.uuid4()), short_id="BT-1")
    assert r.status_code == 404
