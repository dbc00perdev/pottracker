"""decouple probe_pot from probe identity (floating probe)

Revision ID: 0007_probe_pot_decouple
Revises: 0006_tool_mfr_edp
Create Date: 2026-07-13

The probe on the Viper LG-1000AP does NOT return to a fixed home pot: T50 (the
probe, Decision-4) floats between pots under the ATC's random-return strategy
(pot 4 held T30 on 2026-07-08 and T50 on 2026-07-13 — confirmed at the panel by
dbc00per's brother). So the original `ck_machine_probe_pair_consistent`
constraint — `(probe_pot IS NULL) = (probe_t_number IS NULL)`, which assumed the
probe HAS a fixed pot — is the wrong invariant for this machine.

The probe's IDENTITY is fixed (T50 / H50); only its LOCATION floats. R12
write/assignment safety keys on `probe_t_number` / `probe_h_register` (see
`assignments.py`, `offset_write.py`) and is pot-independent, so `probe_pot` can
be NULL without weakening any safety gate. The pot map instead tags the probe
pot DYNAMICALLY (whichever pot currently holds T50 — see `occupancy.py`).

This migration swaps the paired constraint:
  * DROP `ck_machine_probe_pair_consistent`  (probe_pot ⟺ probe_t_number)
  * ADD  `ck_machine_probe_identity_pair`    (probe_t_number ⟺ probe_h_register)

The new invariant enforces that the probe's T-lock and H-lock travel together
(a half-configured probe would make R12 asymmetric), while leaving `probe_pot`
independent and optional.

Downgrade restores the old pairing; it round-trips cleanly on an empty schema.
(If a row with probe_t_number set but probe_pot NULL exists, the old constraint
cannot be re-added — that is the expected consequence of downgrading past the
floating-probe model, not a migration bug.)
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_probe_pot_decouple"
down_revision: str | Sequence[str] | None = "0006_tool_mfr_edp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_machine_probe_pair_consistent", "machine", schema="shared", type_="check"
    )
    op.create_check_constraint(
        "ck_machine_probe_identity_pair",
        "machine",
        "(probe_t_number IS NULL) = (probe_h_register IS NULL)",
        schema="shared",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_machine_probe_identity_pair", "machine", schema="shared", type_="check"
    )
    op.create_check_constraint(
        "ck_machine_probe_pair_consistent",
        "machine",
        "(probe_pot IS NULL) = (probe_t_number IS NULL)",
        schema="shared",
    )
