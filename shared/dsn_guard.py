"""DSN preflight guard — refuse accidental connections to production.

Single source of truth for every entry point that builds a DB engine
(migrations, API app, seed/admin scripts, persist soak). It prints the target
before acting and refuses any non-dev target unless the operator explicitly
sets ``LANCE_ALLOW_PROD=1``.

**Dev fingerprint = local host AND port 5433** (the docker-compose.dev.yml
mapping). Production is never on localhost:5433, so the host/port pair is a
robust discriminator — more reliable than the database name, which is
``pottracker`` in the dev container and could well be reused in prod.

Escape hatches:
  ``LANCE_ALLOW_PROD=1``        allow a non-dev target (loud warning printed).
  ``LANCE_DSN_GUARD_DISABLE=1`` skip the guard entirely — for unit tests that
                                fabricate URLs and never actually connect.

The guard also no-ops for empty and non-PostgreSQL URLs (sqlite, etc.), which
only ever appear in tests, never against a real server.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

_LOCAL_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})
_DEV_PORT: int = 5433


class ProdConnectionRefused(RuntimeError):
    """Raised when a non-dev DSN is used without ``LANCE_ALLOW_PROD=1``."""


def _is_dev(host: str | None, port: int | None) -> bool:
    return host in _LOCAL_HOSTS and port == _DEV_PORT


def assert_target_allowed(url: str, *, action: str) -> None:
    """Print the DSN target, allow dev, refuse prod unless ``LANCE_ALLOW_PROD=1``.

    Raises ``ProdConnectionRefused`` for a non-dev target without the override.
    No-ops for non-network URLs (empty/sqlite) and when
    ``LANCE_DSN_GUARD_DISABLE=1`` is set — both are test conveniences that never
    reach a real server.
    """
    if os.environ.get("LANCE_DSN_GUARD_DISABLE") == "1":
        return
    if not url:
        return
    try:
        parsed = make_url(url)
    except ArgumentError:
        return
    backend = parsed.get_backend_name()
    if backend and not backend.startswith("postgresql"):
        return  # sqlite / other non-network test URLs

    host = parsed.host
    port = parsed.port
    target = f"{host or '?'}:{port or '?'}/{parsed.database or '?'}"
    print(f"[dsn-guard] {action}: about to hit {target}", file=sys.stderr)

    if _is_dev(host, port):
        return

    if os.environ.get("LANCE_ALLOW_PROD") == "1":
        print(
            f"[dsn-guard] WARNING: LANCE_ALLOW_PROD=1 — proceeding against "
            f"NON-DEV target {target} for {action!r}. This is not the dev DB.",
            file=sys.stderr,
        )
        return

    raise ProdConnectionRefused(
        f"Refusing {action}: target {target} is not the dev database "
        f"(expected a local host on port {_DEV_PORT}). If you truly intend to "
        f"run against this target, set LANCE_ALLOW_PROD=1 explicitly. Production "
        f"migrations require an explicit, backed-up, confirmed cutover — see "
        f"tasks/spec-install-safeguards.md and docs/07-risks.md R1."
    )


__all__ = ["ProdConnectionRefused", "assert_target_allowed"]
