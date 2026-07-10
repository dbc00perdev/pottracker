"""Gate-blocks matrix for the FOCAS write-path safety gate (PR-1 + PR-2).

Pure (no DB, no FOCAS), so it runs everywhere. The point of this suite is to
PROVE a write is refused unless mode-lockout passes AND the target isn't the
probe AND both walls (ask + entry) are satisfied — teeth before `cnc_wrtofs`
exists. See `tasks/spec-phase5-write-path.md` §6.
"""

from __future__ import annotations

import pytest

from apps.tooling.api.config import Settings
from apps.tooling.api.services.write_safety import (
    REASON_BAD_PASSWORD,
    REASON_MODE,
    REASON_NO_ASK,
    REASON_PROBE,
    REASON_RUNNING,
    authorize_write,
    mode_lockout_ok,
    verify_write_approval,
)
from shared.focas.models import MachineMode, MachineStatus

_PW = "correct-horse-battery-staple"


def _settings(pw: str = _PW) -> Settings:
    return Settings(
        database_url="",
        jwt_secret="x",
        jwt_access_ttl=900,
        jwt_refresh_ttl=86400,
        log_level="INFO",
        write_approval_password=pw,
    )


def _status(mode: MachineMode = MachineMode.MDI, running: bool = False) -> MachineStatus:
    return MachineStatus(mode=mode, running=running)


def _authz(**overrides):
    """authorize_write with all-passing defaults; override one wall per test."""
    kw = dict(
        status=_status(),
        is_probe_target=False,
        approved=True,
        password_attempt=_PW,
        settings=_settings(),
    )
    kw.update(overrides)
    return authorize_write(**kw)  # type: ignore[arg-type]


# --- the happy path ---------------------------------------------------------


def test_permitted_when_every_wall_passes() -> None:
    authz = _authz()
    assert authz.permitted is True
    assert authz.reason == ""


# --- each wall blocks independently -----------------------------------------


def test_probe_target_refused() -> None:
    authz = _authz(is_probe_target=True)
    assert authz.permitted is False
    assert authz.reason == REASON_PROBE


def test_running_machine_refused() -> None:
    authz = _authz(status=_status(mode=MachineMode.MDI, running=True))
    assert authz.permitted is False
    assert authz.reason == REASON_RUNNING


@pytest.mark.parametrize("mode", [MachineMode.MEM, MachineMode.AUTO, MachineMode.UNKNOWN])
def test_auto_or_unknown_mode_refused(mode: MachineMode) -> None:
    authz = _authz(status=_status(mode=mode, running=False))
    assert authz.permitted is False
    assert authz.reason == REASON_MODE


def test_missing_ask_refused() -> None:
    authz = _authz(approved=False)
    assert authz.permitted is False
    assert authz.reason == REASON_NO_ASK


def test_wrong_password_refused() -> None:
    authz = _authz(password_attempt="wrong")
    assert authz.permitted is False
    assert authz.reason == REASON_BAD_PASSWORD


def test_unconfigured_gate_password_fails_closed() -> None:
    # No WRITE_APPROVAL_PASSWORD configured -> nothing can satisfy the entry wall.
    authz = _authz(password_attempt="", settings=_settings(pw=""))
    assert authz.permitted is False
    assert authz.reason == REASON_BAD_PASSWORD


# --- ordering: the most fundamental block wins ------------------------------


def test_probe_beats_every_other_failure() -> None:
    authz = _authz(
        is_probe_target=True,
        status=_status(mode=MachineMode.AUTO, running=True),
        approved=False,
        password_attempt="wrong",
    )
    assert authz.reason == REASON_PROBE


def test_mode_beats_ask_and_entry() -> None:
    authz = _authz(
        status=_status(mode=MachineMode.MDI, running=True),
        approved=False,
        password_attempt="wrong",
    )
    assert authz.reason == REASON_RUNNING


def test_ask_beats_entry() -> None:
    authz = _authz(approved=False, password_attempt="wrong")
    assert authz.reason == REASON_NO_ASK


# --- unit coverage of the two guards ----------------------------------------


@pytest.mark.parametrize(
    "mode", [MachineMode.MDI, MachineMode.EDIT, MachineMode.HND, MachineMode.JOG, MachineMode.REF]
)
def test_mode_lockout_ok_safe_modes(mode: MachineMode) -> None:
    ok, reason = mode_lockout_ok(_status(mode=mode, running=False))
    assert ok is True and reason == ""


@pytest.mark.parametrize("mode", [MachineMode.MEM, MachineMode.AUTO, MachineMode.UNKNOWN])
def test_mode_lockout_blocks_auto_modes(mode: MachineMode) -> None:
    ok, reason = mode_lockout_ok(_status(mode=mode, running=False))
    assert ok is False and reason == REASON_MODE


def test_mode_lockout_blocks_running_even_in_safe_mode() -> None:
    ok, reason = mode_lockout_ok(_status(mode=MachineMode.MDI, running=True))
    assert ok is False and reason == REASON_RUNNING


def test_verify_write_approval() -> None:
    assert verify_write_approval(_PW, _settings()) is True
    assert verify_write_approval("nope", _settings()) is False
    # Fail-closed when unconfigured, even if the attempt is also empty.
    assert verify_write_approval("", _settings(pw="")) is False
