"""Offset/program export (spec-offset-export.md): pure G10 build+parse
round-trip, CSV shape, and the endpoints end-to-end against the dev DB."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa

from apps.tooling.api.services.g10 import (
    G10Meta,
    build_g10,
    comment_text,
    format_value,
    parse_g10,
    select_registers,
)
from apps.tooling.api.tables import assignment as asg_t
from apps.tooling.api.tables import tool as tool_t
from apps.tooling.api.tables import tool_type as type_t
from shared.db import focas_offset_register as f_off
from shared.db import machine as machine_t
from tests.api.conftest import auth

_T = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)


def _meta(machine_class: str, *, sparse: bool = True, register_count: int = 99) -> G10Meta:
    return G10Meta(
        machine_name="VIPER VT-23B", machine_class=machine_class, unit="inch",
        register_count=register_count, sparse=sparse,
        generated_at="2026-08-06 1200 UTC", mirror_note="MIRROR POLLED 5 SEC BEFORE EXPORT",
    )


_MILL_ROWS = {
    1: {"h_geom": Decimal("3.4744"), "h_wear": Decimal("0.0000"),
        "d_geom": Decimal("0.0000"), "d_wear": Decimal("-0.0130")},
    2: {"h_geom": Decimal("0.0000"), "h_wear": Decimal("0.0000"),
        "d_geom": Decimal("0.0000"), "d_wear": Decimal("0.0000")},  # empty
    50: {"h_geom": Decimal("5.6883"), "h_wear": Decimal("0.0000"),
         "d_geom": Decimal("0.2360"), "d_wear": Decimal("0.0000")},
}

_LATHE_ROWS = {
    1: {"x_geom": Decimal("0.6600"), "x_wear": Decimal("0.0135"),
        "z_geom": Decimal("-0.0092"), "z_wear": Decimal("0.0000"),
        "r_geom": Decimal("0.0313"), "r_wear": Decimal("0.0000"), "tip": Decimal("3")},
    7: {"x_geom": Decimal("0.0000"), "x_wear": Decimal("0.0000"),
        "z_geom": Decimal("0.0000"), "z_wear": Decimal("0.0000"),
        "r_geom": Decimal("0.0000"), "r_wear": Decimal("0.0000"), "tip": Decimal("0")},  # empty
}


class TestG10Pure:
    def test_mill_sparse_form(self):
        text = build_g10(_MILL_ROWS, _meta("mill", register_count=400))
        assert "G20" in text and "G90" in text
        assert "G10 L10 P1 R3.4744" in text
        assert "G10 L11 P1 R0.0000" in text  # included register writes ALL banks
        assert "G10 L13 P1 R-0.0130" in text
        assert "P2 " not in text  # all-zero register omitted in sparse
        assert "(SPARSE - 2 OF 400 REGS - UNLISTED REGS UNTOUCHED)" in text
        assert "(FORM UNVERIFIED ON THIS MACHINE - DO NOT RUN)" in text
        # no T word anywhere (PS1144-class hazard)
        assert not any(line.startswith("T") for line in text.splitlines())

    def test_lathe_sparse_form(self):
        text = build_g10(_LATHE_ROWS, _meta("lathe"))
        assert "G10 P1 X0.0135 Z0.0000 R0.0000" in text  # wear, no Q
        assert "G10 P10001 X0.6600 Z-0.0092 R0.0313 Q3" in text  # geom carries Q
        assert "G90" not in text  # turning canned cycle in system A — never emit
        assert "P7 " not in text and "P10007" not in text

    def test_full_writes_every_register(self):
        text = build_g10(_MILL_ROWS, _meta("mill", sparse=False, register_count=5))
        for n in range(1, 6):
            assert f"G10 L10 P{n} R" in text
        assert "G10 L10 P4 R0.0000" in text  # absent mirror row exported as zeros
        assert "(FULL TABLE - WRITES ALL 5 REGS INCL ZEROS)" in text

    @pytest.mark.parametrize("machine_class,rows", [("mill", _MILL_ROWS), ("lathe", _LATHE_ROWS)])
    @pytest.mark.parametrize("sparse", [True, False])
    def test_round_trip(self, machine_class, rows, sparse):
        meta = _meta(machine_class, sparse=sparse, register_count=8)
        parsed = parse_g10(build_g10(rows, meta))
        assert parsed.machine_class == machine_class
        selected = select_registers(rows, sparse=sparse, register_count=8)
        assert sorted(parsed.rows) == selected
        for n in selected:
            for bank, value in rows.get(n, {}).items():
                assert parsed.rows[n][bank] == value, (n, bank)
            # full-mode registers absent from the mirror parse back as zeros
            for bank, value in parsed.rows[n].items():
                assert value == rows.get(n, {}).get(bank, Decimal("0"))

    def test_parser_rejects_unknown_block(self):
        with pytest.raises(ValueError, match="unrecognized"):
            parse_g10("%\nG10 L99 P1 R1.0\n%")

    def test_parser_rejects_q_on_wear_line(self):
        with pytest.raises(ValueError, match="must not carry Q"):
            parse_g10("G10 P1 X0.0000 Z0.0000 R0.0000 Q3")

    def test_parser_rejects_bare_count_values(self):
        # A value without a decimal point would be least-increment COUNTS on
        # the control — the parser refuses it the same way the builder can't
        # produce it.
        with pytest.raises(ValueError, match="unrecognized"):
            parse_g10("G10 L10 P1 R34744")

    def test_format_value_requires_known_unit(self):
        with pytest.raises(ValueError, match="unknown offset unit"):
            format_value(Decimal("1"), "furlong")
        assert format_value(None, "inch") == "0.0000"
        assert format_value(Decimal("2"), "mm") == "2.000"

    def test_comment_sanitized_to_punch_charset(self):
        assert comment_text("VIPER AG_1000 (crib)") == "VIPER AG-1000 -CRIB-"


@pytest.mark.integration
class TestExportEndpoints:
    def _seed_offsets(self, db_session, machine_id, rows):
        for n, banks in rows.items():
            for bank, value in banks.items():
                db_session.execute(sa.insert(f_off).values(
                    machine_id=machine_id, register_number=n, register_type=bank,
                    value_mm=value, last_polled_at=_T, last_changed_at=_T,
                ))
        db_session.commit()

    def test_g10_download_mill(self, client, db_session, seed_users, viper):
        self._seed_offsets(db_session, viper["id"], _MILL_ROWS)
        resp = client.get(f"/api/tooling/machines/{viper['id']}/exports/offsets.g10",
                          headers=auth(seed_users["viewer"]))
        assert resp.status_code == 200, resp.text
        assert 'attachment; filename="' in resp.headers["content-disposition"]
        assert "G10 L10 P1 R3.4744" in resp.text
        assert "G10 L10 P2 " not in resp.text  # sparse default
        full = client.get(f"/api/tooling/machines/{viper['id']}/exports/offsets.g10?mode=full",
                          headers=auth(seed_users["viewer"]))
        assert full.text.count("G10 L10 P") == 400

    def test_g10_download_lathe_form(self, client, db_session, seed_users):
        # Unique name: the dev DB permanently carries the real fleet rows.
        mid = uuid.uuid4()
        db_session.execute(sa.insert(machine_t).values(
            id=mid, name=f"TEST LATHE {mid.hex[:8]}", control_model="FANUC 0i-TF",
            ip_address="10.1.10.53", focas_port=8193, pot_count=24,
            offset_register_count=99, atc_strategy="random_access",
            has_tsc=False, has_toolsetter=False, poll_interval_seconds=60,
            enabled=True, machine_class="lathe",
        ))
        db_session.commit()
        self._seed_offsets(db_session, mid, _LATHE_ROWS)
        resp = client.get(f"/api/tooling/machines/{mid}/exports/offsets.g10",
                          headers=auth(seed_users["viewer"]))
        assert resp.status_code == 200, resp.text
        assert "G10 P10001 X0.6600 Z-0.0092 R0.0313 Q3" in resp.text
        assert "G90" not in resp.text

    def test_csv_download_with_identity_join(self, client, db_session, seed_users, viper):
        self._seed_offsets(db_session, viper["id"], _MILL_ROWS)
        # Direct seeds with unique codes/ids: the dev DB permanently carries
        # the real crib (em_square etc. exist), so the POST fixture collides.
        type_id = uuid.uuid4()
        db_session.execute(sa.insert(type_t).values(
            id=type_id, code=f"em_square_{type_id.hex[:8]}", display_name="Square Endmill",
            has_corner_radius=False, has_thread_pitch=False, has_taper_angle=False,
            is_drilling=False,
        ))
        tid = uuid.uuid4()
        db_session.execute(sa.insert(tool_t).values(
            id=tid, short_id=f"T{tid.hex[:8]}", tool_type_id=type_id,
            diameter_mm=Decimal("12.7"), diameter_inch=Decimal("0.5"), flute_count=4,
            requires_tsc=False, requires_climb=False, is_consumable_class=False,
            regrind_count=0, created_at=_T, updated_at=_T,
        ))
        db_session.execute(sa.insert(asg_t).values(
            tool_id=tid, machine_id=viper["id"], t_number=1, h_register=1,
            pending_review=False, assigned_at=_T,
        ))
        db_session.commit()
        resp = client.get(f"/api/tooling/machines/{viper['id']}/exports/offsets.csv",
                          headers=auth(seed_users["viewer"]))
        assert resp.status_code == 200, resp.text
        lines = resp.text.splitlines()
        assert lines[1].startswith("machine,register,h_geom_inch,h_wear_inch,d_geom_inch,d_wear_inch")
        row1 = next(line for line in lines if ",1," in line)
        assert f"T{tid.hex[:8]}" in row1 and "SQUARE ENDMILL" in row1

    def test_requires_auth(self, client, viper):
        resp = client.get(f"/api/tooling/machines/{viper['id']}/exports/offsets.g10")
        assert resp.status_code == 401

    def test_unknown_machine_404(self, client, seed_users):
        resp = client.get(f"/api/tooling/machines/{uuid.uuid4()}/exports/offsets.g10",
                          headers=auth(seed_users["viewer"]))
        assert resp.status_code == 404

    def test_program_endpoint_routes_to_service(self, client, seed_users, viper, monkeypatch):
        # The live FOCAS read is exercised by scripts/probe_upload3.py against
        # real controls; here we prove routing/auth/headers only.
        from apps.tooling.api.routers import exports as exports_router

        def _fake_fetch(session, machine_id, o_number):
            assert str(machine_id) == str(viper["id"])
            assert o_number == 80
            return "VIPER-O0080-x.nc", b"%\nO0080\nM30\n%\n"

        monkeypatch.setattr(exports_router.program_export, "fetch_program", _fake_fetch)
        resp = client.get(
            f"/api/tooling/machines/{viper['id']}/exports/program?o_number=80",
            headers=auth(seed_users["viewer"]))
        assert resp.status_code == 200
        assert resp.content.startswith(b"%")
        assert "O0080" in resp.headers["content-disposition"]
