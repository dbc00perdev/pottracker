"""Offset-hover data source: latest offset_change audit row per register/bank
(spec-offset-export follow-on feature 2)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from shared.db import audit_log
from tests.api.conftest import auth

pytestmark = pytest.mark.integration

_T = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)


def _audit(db_session, machine_id, entity_id, at, before, after):
    db_session.execute(sa.insert(audit_log).values(
        occurred_at=at, machine_id=machine_id, event_type="offset_change",
        entity_type="offset", entity_id=entity_id,
        before_value=before, after_value=after, success=True,
    ))


def test_latest_change_per_register(client, db_session, seed_users, viper, no_tsc_machine):
    mid = viper["id"]
    # Two changes on 21/h_geom — only the newest may surface; the newest is
    # the presetter write of the live 07-08 experiment (3.4744 -> 0 -> 5.6883).
    _audit(db_session, mid, "21/h_geom", _T - timedelta(hours=2),
           {"value_mm": "3.4744"}, {"value_mm": "0.0000", "source": "manual_edit"})
    _audit(db_session, mid, "21/h_geom", _T,
           {"value_mm": "0.0000"}, {"value_mm": "5.6883", "source": "presetter_verified"})
    # First observation (baseline capture): before NULL, no source.
    _audit(db_session, mid, "50/d_geom", _T, None, {"value_mm": "0.2360"})
    # Different machine's audit row must not leak in (FK needs a real row).
    _audit(db_session, no_tsc_machine["id"], "21/h_geom", _T,
           {"value_mm": "9.9999"}, {"value_mm": "1.1111"})
    db_session.commit()

    resp = client.get(f"/api/tooling/machines/{mid}/offset-changes",
                      headers=auth(seed_users["viewer"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 2
    h21 = next(c for c in body if c["register_number"] == 21)
    assert h21["register_type"] == "h_geom"
    assert h21["old_value"] == "0.0000" and h21["new_value"] == "5.6883"
    assert h21["source"] == "presetter_verified"
    d50 = next(c for c in body if c["register_number"] == 50)
    assert d50["old_value"] is None and d50["new_value"] == "0.2360"
    assert d50["source"] is None


def test_requires_auth_and_404(client, seed_users, viper):
    assert client.get(f"/api/tooling/machines/{viper['id']}/offset-changes").status_code == 401
    resp = client.get(f"/api/tooling/machines/{uuid.uuid4()}/offset-changes",
                      headers=auth(seed_users["viewer"]))
    assert resp.status_code == 404
