"""FOCAS write-path safety gate (CLAUDE.md HARD GATE) — PR-1 + PR-2.

Pure guards that decide whether an offset write may proceed. NO write is
performed here and `cnc_wrtofs` is NOT bound anywhere yet — this module only
says *permitted / refused* and why. The real write surface is mock-only (PR-3)
until the binding lands behind this gate (PR-4). See `tasks/spec-phase5-write-path.md`.

A write is permitted only when ALL hold (checked fail-closed, worst-first):

  1. Target is NOT the reserved probe register (R12).
  2. Mode lockout — the machine is NOT running and is in a manual/idle mode, so
     no program is (or can be) executing (R6). Verified from the live status.
  3. The ask — an explicit write approval was affirmatively granted (never a
     default/auto-yes).
  4. The entry — the gated `WRITE_APPROVAL_PASSWORD` is supplied and verifies.

Neither wall (ask/entry) alone suffices; both are required, every write.

NOTE (domain validation pending): the exact set of "safe editing" modes below is
a conservative fail-closed default. It MUST be confirmed with the operator /
on-site FOCAS expert against the real control before the first LIVE write
(spec D5 / PR-4) — tune `_WRITE_SAFE_MODES` there, not by guessing.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from apps.tooling.api.config import Settings
from shared.focas.models import MachineMode, MachineStatus

# Manual / idle modes where an offset edit is safe WHEN the machine is not
# running. Anything else (MEM/AUTO program-execution modes, UNKNOWN, or a
# running machine) is refused — fail closed.
_WRITE_SAFE_MODES = frozenset(
    {
        MachineMode.MDI,
        MachineMode.EDIT,
        MachineMode.HND,
        MachineMode.JOG,
        MachineMode.REF,
    }
)

# Refusal reasons — stable strings so the API/UI and tests can assert on them.
REASON_PROBE = "target is the reserved probe register (R12)"
REASON_RUNNING = "machine is running — writes are locked out (R6)"
REASON_MODE = "control mode is not a safe editing mode — writes are locked out (R6)"
REASON_NO_ASK = "write approval was not explicitly granted (the ask)"
REASON_BAD_PASSWORD = "write-approval password missing or incorrect (the entry)"


@dataclass(frozen=True)
class WriteAuthorization:
    """Result of the gate. `permitted` is True only when every wall passed;
    otherwise `reason` names the first failing wall (stable string above)."""

    permitted: bool
    reason: str = ""


def mode_lockout_ok(status: MachineStatus) -> tuple[bool, str]:
    """True when the machine is safe to write to: not running AND in a manual/idle
    mode. Fail-closed — UNKNOWN or any auto-execution mode returns False."""
    if status.running:
        return False, REASON_RUNNING
    if status.mode not in _WRITE_SAFE_MODES:
        return False, REASON_MODE
    return True, ""


def verify_write_approval(password_attempt: str, settings: Settings) -> bool:
    """Constant-time check of the entry wall. Fail-closed: if no gate password is
    configured (`WRITE_APPROVAL_PASSWORD` unset), NO password can verify — the
    write path is disabled rather than open."""
    configured = settings.write_approval_password
    if not configured:
        return False
    return secrets.compare_digest(password_attempt, configured)


def authorize_write(
    *,
    status: MachineStatus,
    is_probe_target: bool,
    approved: bool,
    password_attempt: str,
    settings: Settings,
) -> WriteAuthorization:
    """Compose the full gate. Returns permitted only when the target is not the
    probe, mode-lockout passes, the ask was granted, AND the entry verifies.
    Checked fail-closed and worst-first so the returned `reason` is the most
    fundamental block."""
    if is_probe_target:
        return WriteAuthorization(False, REASON_PROBE)

    mode_ok, mode_reason = mode_lockout_ok(status)
    if not mode_ok:
        return WriteAuthorization(False, mode_reason)

    if not approved:
        return WriteAuthorization(False, REASON_NO_ASK)

    if not verify_write_approval(password_attempt, settings):
        return WriteAuthorization(False, REASON_BAD_PASSWORD)

    return WriteAuthorization(True, "")
