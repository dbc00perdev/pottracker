"""Auth endpoint + role-gating integration tests."""

from __future__ import annotations

import pytest

from tests.api.conftest import auth

pytestmark = pytest.mark.integration


def test_login_success(client, seed_users):
    u = seed_users["setter"]
    r = client.post("/api/tooling/auth/login",
                    json={"username": u["username"], "password": u["password"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "bearer"


def test_login_wrong_password(client, seed_users):
    r = client.post("/api/tooling/auth/login",
                    json={"username": "setter_u", "password": "nope"})
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")


def test_login_unknown_user(client, seed_users):
    r = client.post("/api/tooling/auth/login",
                    json={"username": "ghost", "password": "x"})
    assert r.status_code == 401


def test_me(client, seed_users):
    r = client.get("/api/tooling/auth/me", headers=auth(seed_users["admin"]))
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


def test_me_requires_token(client, seed_users):
    r = client.get("/api/tooling/auth/me")
    assert r.status_code == 401


def test_refresh_flow(client, seed_users):
    u = seed_users["operator"]
    login = client.post("/api/tooling/auth/login",
                        json={"username": u["username"], "password": u["password"]}).json()
    r = client.post("/api/tooling/auth/refresh",
                    json={"refresh_token": login["refresh_token"]})
    assert r.status_code == 200
    assert r.json()["access_token"]


def test_refresh_rejects_access_token(client, seed_users):
    u = seed_users["operator"]
    login = client.post("/api/tooling/auth/login",
                        json={"username": u["username"], "password": u["password"]}).json()
    r = client.post("/api/tooling/auth/refresh",
                    json={"refresh_token": login["access_token"]})
    assert r.status_code == 401


def test_role_gate_forbids_low_role(client, seed_users, tool_type_id):
    # viewer cannot create a tool (needs setter+)
    r = client.post("/api/tooling/tools", headers=auth(seed_users["viewer"]),
                    json={"short_id": "X-1", "tool_type_id": tool_type_id, "diameter_mm": "6.0"})
    assert r.status_code == 403
