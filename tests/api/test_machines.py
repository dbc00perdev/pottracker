"""Machine endpoints + FOCAS mirror reads + health integration tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from shared.db import focas_machine_status as f_status
from shared.db import focas_offset_register as f_off
from shared.db import focas_pot as f_pot
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


def test_spindle_empty_when_no_status_row(client, seed_users, viper):
    r = client.get(f"/api/tooling/machines/{viper['id']}/spindle",
                   headers=auth(seed_users["viewer"]))
    assert r.status_code == 200
    body = r.json()
    assert body["head_t_number"] is None and body["next_t_number"] is None
    assert body["last_polled_at"] is None


def test_spindle_reads_status_mirror(client, seed_users, viper, db_session):
    now = datetime.now(UTC)
    db_session.execute(sa.insert(f_status).values(
        machine_id=viper["id"], head_t_number=85, next_t_number=31, mode="auto",
        running=True, emergency_stop=False, last_polled_at=now, last_changed_at=now))
    db_session.commit()
    r = client.get(f"/api/tooling/machines/{viper['id']}/spindle",
                   headers=auth(seed_users["viewer"]))
    assert r.status_code == 200
    body = r.json()
    assert body["head_t_number"] == 85
    assert body["next_t_number"] == 31
    assert body["mode"] == "auto" and body["running"] is True
    # No last-tool memory persisted -> both fields present and null (VT_23 L2).
    assert body["last_tool_t_word"] is None and body["last_tool_at"] is None


def test_spindle_exposes_last_tool_memory(client, seed_users, viper, db_session):
    """VT_23 L2: the last-real-offset memory rides the spindle payload — live
    word is a T1200 cancel, memory still says T1224 was last active."""
    now = datetime.now(UTC)
    earlier = now - timedelta(minutes=5)
    db_session.execute(sa.insert(f_status).values(
        machine_id=viper["id"], head_t_number=1200, next_t_number=None, mode="mdi",
        running=False, emergency_stop=False, last_tool_t_word=1224,
        last_tool_at=earlier, last_polled_at=now, last_changed_at=now))
    db_session.commit()
    r = client.get(f"/api/tooling/machines/{viper['id']}/spindle",
                   headers=auth(seed_users["viewer"]))
    assert r.status_code == 200
    body = r.json()
    assert body["head_t_number"] == 1200
    assert body["last_tool_t_word"] == 1224
    assert body["last_tool_at"] is not None


def test_spindle_404_unknown_machine(client, seed_users):
    import uuid
    r = client.get(f"/api/tooling/machines/{uuid.uuid4()}/spindle",
                   headers=auth(seed_users["viewer"]))
    assert r.status_code == 404


def test_pots_include_location(client, seed_users, viper, db_session):
    now = datetime.now(UTC)
    db_session.execute(sa.insert(f_pot).values(
        machine_id=viper["id"], pot_number=2, t_number=50,
        last_polled_at=now, last_changed_at=now))
    db_session.execute(sa.insert(f_status).values(
        machine_id=viper["id"], head_t_number=50, next_t_number=None, mode="auto",
        running=True, emergency_stop=False, last_polled_at=now, last_changed_at=now))
    db_session.commit()
    r = client.get(f"/api/tooling/machines/{viper['id']}/pots",
                   headers=auth(seed_users["viewer"]))
    assert r.status_code == 200
    pot2 = next(p for p in r.json() if p["pot_number"] == 2)
    assert pot2["location"] == "spindle"  # T50 is in the spindle


def test_health(client, seed_users, viper):
    r = client.get("/api/tooling/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert any(m["name"] == "Viper LG-1000AP" for m in body["machines"])
