"""Tool-type + audit-scoping integration tests."""

from __future__ import annotations

import pytest

from tests.api.conftest import auth

pytestmark = pytest.mark.integration


def test_tool_type_create_admin_only(client, seed_users):
    r = client.post("/api/tooling/tool-types",
                    json={"code": "drill", "display_name": "Drill", "is_drilling": True},
                    headers=auth(seed_users["setter"]))
    assert r.status_code == 403
    r2 = client.post("/api/tooling/tool-types",
                     json={"code": "drill", "display_name": "Drill", "is_drilling": True},
                     headers=auth(seed_users["admin"]))
    assert r2.status_code == 201
    assert r2.json()["is_drilling"] is True


def test_tool_type_list(client, seed_users, tool_type_id):
    r = client.get("/api/tooling/tool-types", headers=auth(seed_users["viewer"]))
    assert r.status_code == 200
    assert any(t["code"] == "em_square" for t in r.json())


def test_tool_type_duplicate_code_conflict(client, seed_users):
    b = {"code": "reamer", "display_name": "Reamer"}
    assert client.post("/api/tooling/tool-types", json=b,
                       headers=auth(seed_users["admin"])).status_code == 201
    r = client.post("/api/tooling/tool-types", json=b, headers=auth(seed_users["admin"]))
    assert r.status_code == 409


def test_audit_admin_sees_all_others_scoped(client, seed_users, tool_type_id):
    # setter creates a tool → audit row with setter's user_id
    client.post("/api/tooling/tools", headers=auth(seed_users["setter"]),
                json={"short_id": "AUD-1", "tool_type_id": tool_type_id, "diameter_mm": "6.0"})
    # admin sees the event
    admin_rows = client.get("/api/tooling/audit?event_type=tool_create",
                            headers=auth(seed_users["admin"])).json()["items"]
    assert any(r["event_type"] == "tool_create" for r in admin_rows)
    # viewer (different user) sees none of the setter's actions
    viewer_page = client.get("/api/tooling/audit?event_type=tool_create",
                             headers=auth(seed_users["viewer"])).json()
    assert viewer_page["items"] == [] and viewer_page["total"] == 0


def test_validation_error_is_problem_json(client, seed_users, tool_type_id):
    # missing required diameter_mm
    r = client.post("/api/tooling/tools", headers=auth(seed_users["setter"]),
                    json={"short_id": "BAD", "tool_type_id": tool_type_id})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    assert "diameter_mm" in r.json()["detail"]
