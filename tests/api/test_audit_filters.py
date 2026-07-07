"""Cover audit query filter branches + the tool 'assigned' filter branch."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.api.conftest import auth

pytestmark = pytest.mark.integration


def test_audit_filters(client, seed_users, viper, tool_type_id):
    # create a tool (audit: tool_create) and a machine update (audit: machine_update)
    client.post("/api/tooling/tools", headers=auth(seed_users["setter"]),
                json={"short_id": "AF-1", "tool_type_id": tool_type_id, "diameter_mm": "6.0"})
    client.patch(f"/api/tooling/machines/{viper['id']}",
                 json={"poll_interval_seconds": 45}, headers=auth(seed_users["admin"]))
    h = auth(seed_users["admin"])
    # filter by entity_type
    tools_only = client.get("/api/tooling/audit?entity_type=tool", headers=h).json()["items"]
    assert tools_only and all(r["entity_type"] == "tool" for r in tools_only)
    # filter by machine_id
    by_machine = client.get(f"/api/tooling/audit?machine_id={viper['id']}",
                            headers=h).json()["items"]
    assert all(r["machine_id"] == str(viper["id"]) for r in by_machine)
    # filter by user_id (admin scoping to a specific user)
    setter_id = seed_users["setter"]["id"]
    by_user = client.get(f"/api/tooling/audit?user_id={setter_id}", headers=h).json()["items"]
    assert all(r["user_id"] == str(setter_id) for r in by_user)
    # time window (params= so httpx encodes the '+' in the tz offset)
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    page = client.get("/api/tooling/audit", params={"since": future}, headers=h).json()
    assert page["items"] == [] and page["total"] == 0


def test_tool_assigned_filter(client, seed_users, viper, tool_type_id):
    unassigned = client.post("/api/tooling/tools", headers=auth(seed_users["setter"]),
                             json={"short_id": "UN-1", "tool_type_id": tool_type_id,
                                   "diameter_mm": "6.0"}).json()["id"]
    assigned_tool = client.post("/api/tooling/tools", headers=auth(seed_users["setter"]),
                                json={"short_id": "AS-1", "tool_type_id": tool_type_id,
                                      "diameter_mm": "6.0"}).json()["id"]
    client.post("/api/tooling/assignments", headers=auth(seed_users["setter"]),
                json={"tool_id": assigned_tool, "machine_id": str(viper["id"]),
                      "t_number": 22, "h_register": 122})
    h = auth(seed_users["viewer"])
    only_assigned = client.get("/api/tooling/tools?assigned=true", headers=h).json()
    ids = {t["id"] for t in only_assigned["items"]}
    assert assigned_tool in ids and unassigned not in ids
    only_unassigned = client.get("/api/tooling/tools?assigned=false", headers=h).json()
    ids2 = {t["id"] for t in only_unassigned["items"]}
    assert unassigned in ids2 and assigned_tool not in ids2
    by_machine = client.get(f"/api/tooling/tools?assigned_machine_id={viper['id']}",
                            headers=h).json()
    assert {t["id"] for t in by_machine["items"]} == {assigned_tool}
