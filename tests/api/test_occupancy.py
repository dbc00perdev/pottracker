"""Occupancy model (#3): pure classifier + the enriched query end-to-end."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa

from apps.tooling.api.services.occupancy import PotState, classify_pot, occupancy
from apps.tooling.api.tables import assignment as asg
from apps.tooling.api.tables import tool, tool_type
from shared.db import audit_log, focas_offset_register, focas_pot

_T = datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)


# --- pure classifier (no DB) -------------------------------------------------


class TestClassifyPot:
    def test_probe_pot_wins(self):
        occ = classify_pot(24, 90, probe_pot=24, h_register=5, offset_mm=Decimal("3"), presetter_verified=True)
        assert occ.state is PotState.PROBE
        assert occ.verified is False

    def test_no_identity_is_empty(self):
        occ = classify_pot(2, None, None, None, None, False)
        assert occ.state is PotState.EMPTY

    def test_identity_no_assignment_ordinal_is_empty(self):
        # Pot reads its own ordinal, no assignment -> reinit/empty sentinel.
        occ = classify_pot(4, 4, None, None, None, False)
        assert occ.state is PotState.EMPTY

    def test_identity_no_assignment_nonordinal_is_unverified(self):
        occ = classify_pot(3, 33, None, None, None, False)
        assert occ.state is PotState.UNVERIFIED
        assert occ.t_number == 33

    def test_assignment_zero_offset_is_empty(self):
        occ = classify_pot(1, 5, None, h_register=5, offset_mm=Decimal("0.0000"), presetter_verified=False)
        assert occ.state is PotState.EMPTY
        assert occ.assigned_h_register == 5

    def test_assignment_missing_offset_is_empty(self):
        occ = classify_pot(1, 5, None, h_register=5, offset_mm=None, presetter_verified=False)
        assert occ.state is PotState.EMPTY

    def test_assignment_nonzero_offset_is_loaded(self):
        occ = classify_pot(1, 5, None, h_register=5, offset_mm=Decimal("3.4744"), presetter_verified=False)
        assert occ.state is PotState.LOADED
        assert occ.offset_mm == Decimal("3.4744")
        assert occ.verified is False

    def test_loaded_carries_presetter_verified(self):
        occ = classify_pot(1, 5, None, h_register=5, offset_mm=Decimal("5.6883"), presetter_verified=True)
        assert occ.state is PotState.LOADED
        assert occ.verified is True


# --- enriched query (integration) --------------------------------------------


def _seed_tool(session, *, short_id: str) -> uuid.UUID:
    tt_id = uuid.uuid4()
    session.execute(sa.insert(tool_type).values(
        id=tt_id, code=f"tt_{short_id}", display_name="T", has_corner_radius=False,
        has_thread_pitch=False, has_taper_angle=False, is_drilling=False,
    ))
    t_id = uuid.uuid4()
    session.execute(sa.insert(tool).values(
        id=t_id, short_id=short_id, tool_type_id=tt_id, diameter_mm=Decimal("6.0"),
        requires_tsc=False, requires_climb=False, is_consumable_class=False,
        regrind_count=0, created_at=_T, updated_at=_T,
    ))
    return t_id


@pytest.mark.integration
def test_occupancy_query_all_states(db_session, viper):
    mid = viper["id"]
    # pots: 1 loaded (assigned+offset), 2 empty (assigned+zero offset),
    #       3 unverified (identity, no assignment), 4 empty-sentinel (ordinal),
    #       24 probe.
    for pot_number, t_number in [(1, 5), (2, 90), (3, 33), (4, 4), (24, 50)]:
        db_session.execute(sa.insert(focas_pot).values(
            machine_id=mid, pot_number=pot_number, t_number=t_number,
            last_polled_at=_T, last_changed_at=_T,
        ))
    # assignments: T5->H5, T90->H90 (T33, T4 intentionally unassigned)
    for t_number, h_register in [(5, 5), (90, 90)]:
        db_session.execute(sa.insert(asg).values(
            tool_id=_seed_tool(db_session, short_id=f"S{t_number}"), machine_id=mid,
            t_number=t_number, h_register=h_register, pending_review=False, assigned_at=_T,
        ))
    # offsets: H5 = 3.4744 (loaded), H90 = 0 (decommissioned -> empty)
    for reg, val in [(5, "3.4744"), (90, "0.0000")]:
        db_session.execute(sa.insert(focas_offset_register).values(
            machine_id=mid, register_number=reg, register_type="h_geom",
            value_mm=Decimal(val), last_polled_at=_T, last_changed_at=_T,
        ))
    # H5's latest offset change was presetter-attributed -> verified
    db_session.execute(sa.insert(audit_log).values(
        machine_id=mid, event_type="offset_change", entity_type="offset",
        entity_id="5/h_geom", after_value={"value_mm": "3.4744", "source": "presetter_verified"},
        success=True, occurred_at=_T,
    ))
    db_session.commit()

    rows = {r["pot_number"]: r for r in occupancy(db_session, mid)}
    assert rows[1]["state"] == "loaded"
    assert rows[1]["verified"] is True
    assert rows[1]["assigned_h_register"] == 5
    assert rows[1]["offset_mm"] == Decimal("3.4744")
    assert rows[2]["state"] == "empty"  # assigned but offset zeroed
    assert rows[3]["state"] == "unverified"  # identity, no assignment
    assert rows[4]["state"] == "empty"  # ordinal sentinel
    assert rows[24]["state"] == "probe"


@pytest.mark.integration
def test_occupancy_404_unknown_machine(db_session):
    from apps.tooling.api.errors import NotFound

    with pytest.raises(NotFound):
        occupancy(db_session, uuid.uuid4())
