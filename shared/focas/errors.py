"""FOCAS error code -> exception hierarchy.

FOCAS functions return `short` error codes. 0 is success; nonzero is an error
whose meaning is defined in the FOCAS2 developer manual and (for some codes)
`Fwlib64.h` `#define EW_*` constants.

This module defines an exception hierarchy and a `raise_for_code(code, context)`
helper that the client uses to convert raw return codes into typed exceptions.

Specific code-to-exception mappings live in `_KNOWN_CODES` below. The set is
intentionally minimal at first — codes are added as we encounter them in
integration testing or extract them verbatim from `Fwlib64.h`. Any unmapped
nonzero code raises a generic `FocasError` carrying the code, so we never
swallow an error silently.

`Fwlib64.h` is the source of truth for the integer constants. A future
extractor pass should pull every `#define EW_*` line into a constants table;
until then, this module deliberately avoids guessing values.
"""

from __future__ import annotations


class FocasError(Exception):
    """Base for all FOCAS errors raised by `shared.focas.client`.

    Attributes:
        code: the raw `short` returned by the FOCAS function.
        context: human-readable label for the call site, e.g. "cnc_rdtofs".
    """

    code: int
    context: str | None

    def __init__(self, code: int, context: str | None = None, message: str = ""):
        self.code = code
        self.context = context
        suffix = f" ({context})" if context else ""
        body = f": {message}" if message else ""
        super().__init__(f"FOCAS error {code}{suffix}{body}")


# Connection / transport ------------------------------------------------------


class FocasConnectError(FocasError):
    """Failed to allocate or use the library handle (network, DLL, version)."""


class FocasHandleError(FocasError):
    """Invalid handle. Reconnect required."""


class FocasSocketError(FocasError):
    """TCP / Ethernet transport error."""


class FocasNoDllError(FocasError):
    """`Fwlib64.dll` (or its TCP / processing siblings) failed to load."""


class FocasVersionError(FocasError):
    """Library or processing-DLL version mismatch with the connected control."""


# Per-call data errors --------------------------------------------------------


class FocasFunctionError(FocasError):
    """Function not available on this control / option not licensed."""


class FocasLengthError(FocasError):
    """Caller supplied a buffer length that doesn't match the expected struct."""


class FocasNumberError(FocasError):
    """Data number out of range (e.g. offset register beyond use_no)."""


class FocasAttributeError(FocasError):
    """Data attribute / type code invalid for this call."""


class FocasDataError(FocasError):
    """Returned data was malformed or out of expected range."""


class FocasNoOptionError(FocasError):
    """The requested function requires a control option not present."""


class FocasWriteProtectedError(FocasError):
    """Target register is write-protected (e.g. parameter mode lockout)."""


class FocasParameterError(FocasError):
    """A passed-in value was rejected as out of bounds by the control."""


# Control state errors --------------------------------------------------------


class FocasModeError(FocasError):
    """Operation refused because the control is in an incompatible mode.

    Mode lockout (R6) lives here: writes refused while in AUTO running.
    """


class FocasAlarmError(FocasError):
    """Operation refused because an alarm is active on the control."""


class FocasRejectedError(FocasError):
    """The control returned a generic reject — see message for detail."""


class FocasBusyError(FocasError):
    """The control is busy and the call should be retried after backoff."""


class FocasResetError(FocasError):
    """The control raised a reset during the call; state is indeterminate."""


# Mapping ---------------------------------------------------------------------

# Populated as codes are confirmed against `Fwlib64.h` / FOCAS2 manual.
# Keep this dict tight — guessing here means client code makes wrong recovery
# decisions. Empty mapping = every nonzero code raises generic `FocasError`,
# which is the right safe default until codes are extracted.
_KNOWN_CODES: dict[int, type[FocasError]] = {
    # 0 is success and is handled before lookup.
    # TODO: populate from Fwlib64.h #define EW_* lines via a future extractor pass.
    # Candidate mappings to confirm against header before adding:
    #   1  -> FocasFunctionError      (EW_FUNC?)
    #   2  -> FocasLengthError        (EW_LENGTH?)
    #   3  -> FocasNumberError        (EW_NUMBER?)
    #   4  -> FocasAttributeError     (EW_ATTRIB?)
    #   5  -> FocasDataError          (EW_DATA?)
    #   6  -> FocasNoOptionError      (EW_NOOPT?)
    #   7  -> FocasWriteProtectedError(EW_PROT?)
    #   13 -> FocasRejectedError      (EW_REJECT?)
    #   15 -> FocasAlarmError         (EW_ALARM?)
    #   16 -> FocasBusyError          (EW_BUSY?)
    #   -8 -> FocasHandleError        (EW_HANDLE?)
}


def raise_for_code(code: int, context: str | None = None, message: str = "") -> None:
    """Raise the appropriate `FocasError` subclass for a nonzero FOCAS return.

    No-op when `code == 0` (success). Unmapped nonzero codes raise generic
    `FocasError`. Caller passes a `context` string identifying the call site
    so error messages name the failing FOCAS function.
    """
    if code == 0:
        return
    cls = _KNOWN_CODES.get(code, FocasError)
    raise cls(code=code, context=context, message=message)
