"""Machine endpoints + FOCAS mirror reads + health integration tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from shared.db import focas_offset_register as f_off
from tests.api.conftest import auth

pytestmark = pytest.mark.integration


def test_create_skip_probe(client, seed_users):
    r = client.post("/api/tooling/machines?skip_probe=true", headers=auth(seed_users["admin"]),
                    json={"name": "TESTM-1", "control_model": "FANUC 0i-MF",
                          "ip_address": "10.0.0.9", "pot_count": 24,
                          "atc_strategy": "random_access"})
    assert r.status_code == 201, r.text
    assert r.json()["focas_state"]["connected"] is False


def test_create_probe_unreachable(client, seed_users, monkeypatch):
    monkeypatch.setattr("apps.tooling.api.services.machines.tcp_probe", lambda *a, **k: False)
    r = client.post("/api/tooling/machines", headers=auth(seed_users["admin"]),
                    json={"name": "TESTM-2", "control_model": "x", "ip_address": "10.0.0.10",
                          "pot_count": 24, "atc_strategy": "random_access"})
    assert r.status_code == 422
    assert "not reachable" in r.json()["detail"]


def test_create_requires_admin(client, seed_users):
    r = client.post("/api/tooling/machines?skip_probe=true", headers=auth(seed_users["setter"]),
                    json={"name": "TESTM-3", "control_model": "x", "ip_address": "10.0.0.11",
                          "pot_count": 24, "atc_strategy": "random_access"})
    assert r.status_code == 403


def test_list_and_get(client, seed_users, viper):
    lst = client.get("/api/tooling/machines", headers=auth(seed_users["viewer"])).json()
    assert any(m["name"] == "Viper LG-1000AP" for m in lst)
    g = client.get(f"/api/tooling/machines/{viper['id']}", headers=auth(seed_users["viewer"]))
    assert g.status_code == 200
    assert g.json()["probe_t_number"] == 50
    assert g.json()["probe_h_register"] == 50


def test_update(client, seed_users, viper):
    r = client.patch(f"/api/tooling/machines/{viper['id']}", json={"poll_interval_seconds": 30},
                     headers=auth(seed_users["admin"]))
    assert r.status_code == 200
    assert r.json()["poll_interval_seconds"] == 30


def test_focas_state_fresh_mirror(client, seed_users, viper, db_session):
    now = datetime.now(UTC)
    db_session.execute(sa.insert(f_off).values(
        machine_id=viper["id"], register_number=100, register_type="h_geom",
        value_mm="7.4050", last_polled_at=now, last_changed_at=now))
    db_session.commit()
    g = client.get(f"/api/tooling/machines/{viper['id']}", headers=auth(seed_users["viewer"]))
    assert g.json()["focas_state"]["connected"] is True
    assert g.json()["focas_state"]["lag_seconds"] is not None


def test_offsets_read(client, seed_users, viper, db_session):
    now = datetime.now(UTC)
    db_session.execute(sa.insert(f_off).values(
        machine_id=viper["id"], register_number=125, register_type="h_geom",
        value_mm="63.5042", last_polled_at=now, last_changed_at=now))
    db_session.commit()
    r = client.get(f"/api/tooling/machines/{viper['id']}/offsets",
                   headers=auth(seed_users["viewer"]))
    assert r.status_code == 200
    assert any(o["register_number"] == 125 and o["value_mm"] == "63.5042" for o in r.json())


def test_health(client, seed_users, viper):
    r = client.get("/api/tooling/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert any(m["name"] == "Viper LG-1000AP" for m in body["machines"])
