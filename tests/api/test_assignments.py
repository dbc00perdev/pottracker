"""Assignment integration tests — probe-lock (Decision-4), uniqueness,
capability, confirm/delete, reuse-after-delete."""

from __future__ import annotations

import pytest

from tests.api.conftest import auth

pytestmark = pytest.mark.integration


@pytest.fixture
def a_tool(client, seed_users, tool_type_id):
    r = client.post("/api/tooling/tools", headers=auth(seed_users["setter"]),
                    json={"short_id": "A-TOOL", "tool_type_id": tool_type_id,
                          "diameter_mm": "6.0", "requires_tsc": False})
    return r.json()["id"]


def _assign(client, users, tool_id, machine_id, **over):
    body = {"tool_id": tool_id, "machine_id": machine_id,
            "t_number": 10, "h_register": 110, "d_register": 210}
    body.update(over)
    return client.post("/api/tooling/assignments", json=body, headers=auth(users["setter"]))


def test_create_pending_review(client, seed_users, viper, a_tool):
    r = _assign(client, seed_users, a_tool, str(viper["id"]))
    assert r.status_code == 201, r.text
    assert r.json()["pending_review"] is True
    assert r.json()["machine_name"] == "Viper LG-1000AP"


def test_probe_t50_rejected(client, seed_users, viper, a_tool):
    r = _assign(client, seed_users, a_tool, str(viper["id"]), t_number=50, h_register=150)
    assert r.status_code == 422
    assert "probe" in r.json()["detail"].lower()
    assert r.json()["field"] == "t_number"


def test_probe_h50_rejected(client, seed_users, viper, a_tool):
    r = _assign(client, seed_users, a_tool, str(viper["id"]), t_number=15, h_register=50)
    assert r.status_code == 422
    assert r.json()["field"] == "h_register"


def test_tnumber_unique_active(client, seed_users, viper, a_tool, tool_type_id):
    assert _assign(client, seed_users, a_tool, str(viper["id"]),
                   t_number=11, h_register=111).status_code == 201
    other = client.post("/api/tooling/tools", headers=auth(seed_users["setter"]),
                        json={"short_id": "A-TOOL2", "tool_type_id": tool_type_id,
                              "diameter_mm": "6.0"}).json()["id"]
    r = _assign(client, seed_users, other, str(viper["id"]), t_number=11, h_register=999)
    assert r.status_code == 409


def test_hregister_unique_active(client, seed_users, viper, a_tool, tool_type_id):
    assert _assign(client, seed_users, a_tool, str(viper["id"]),
                   t_number=12, h_register=112).status_code == 201
    other = client.post("/api/tooling/tools", headers=auth(seed_users["setter"]),
                        json={"short_id": "A-TOOL3", "tool_type_id": tool_type_id,
                              "diameter_mm": "6.0"}).json()["id"]
    r = _assign(client, seed_users, other, str(viper["id"]), t_number=999, h_register=112)
    assert r.status_code == 409


def test_tsc_capability_rejected(client, seed_users, no_tsc_machine, tool_type_id):
    tsc_tool = client.post("/api/tooling/tools", headers=auth(seed_users["setter"]),
                           json={"short_id": "TSC-1", "tool_type_id": tool_type_id,
                                 "diameter_mm": "6.0", "requires_tsc": True}).json()["id"]
    r = _assign(client, seed_users, tsc_tool, str(no_tsc_machine["id"]))
    assert r.status_code == 422
    assert "coolant" in r.json()["detail"].lower()


def test_confirm_clears_pending(client, seed_users, viper, a_tool):
    aid = _assign(client, seed_users, a_tool, str(viper["id"]),
                  t_number=13, h_register=113).json()["id"]
    r = client.post(f"/api/tooling/assignments/{aid}/confirm", json={"reason": "verified"},
                    headers=auth(seed_users["operator"]))
    assert r.status_code == 200
    assert r.json()["pending_review"] is False
    assert r.json()["last_confirmed_at"] is not None


def test_delete_then_reuse_tnumber(client, seed_users, viper, a_tool):
    aid = _assign(client, seed_users, a_tool, str(viper["id"]),
                  t_number=14, h_register=114).json()["id"]
    d = client.request("DELETE", f"/api/tooling/assignments/{aid}",
                       json={"reason": "removed"}, headers=auth(seed_users["setter"]))
    assert d.status_code == 204
    # T14/H114 now free — same registers accept a new assignment
    r = _assign(client, seed_users, a_tool, str(viper["id"]), t_number=14, h_register=114)
    assert r.status_code == 201


def test_patch_reopens_pending(client, seed_users, viper, a_tool):
    aid = _assign(client, seed_users, a_tool, str(viper["id"]),
                  t_number=16, h_register=116).json()["id"]
    client.post(f"/api/tooling/assignments/{aid}/confirm", headers=auth(seed_users["operator"]))
    r = client.patch(f"/api/tooling/assignments/{aid}", json={"h_register": 117},
                     headers=auth(seed_users["setter"]))
    assert r.status_code == 200
    assert r.json()["pending_review"] is True
    assert r.json()["h_register"] == 117


def test_list_filters_by_pending(client, seed_users, viper, a_tool):
    _assign(client, seed_users, a_tool, str(viper["id"]), t_number=18, h_register=118)
    rows = client.get("/api/tooling/assignments?pending_review=true",
                      headers=auth(seed_users["viewer"])).json()
    assert len(rows) >= 1 and all(x["pending_review"] for x in rows)
