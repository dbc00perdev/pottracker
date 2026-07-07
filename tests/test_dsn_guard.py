"""Unit tests for the DSN preflight guard (shared/dsn_guard.py, safeguard #2).

Pure-function tests — no DB connection. Covers: dev acceptance across host
forms and driver prefixes, prod refusal, the LANCE_ALLOW_PROD override, the
LANCE_DSN_GUARD_DISABLE test escape, and the non-network URL no-ops.
"""

from __future__ import annotations

import pytest

from shared.dsn_guard import ProdConnectionRefused, assert_target_allowed

# IPv6 must be bracketed in a DSN; SQLAlchemy strips the brackets so the
# guard sees host "::1".
_DEV_HOSTS = ["localhost", "127.0.0.1", "[::1]"]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure neither escape-hatch env var leaks in from the ambient shell."""
    monkeypatch.delenv("LANCE_ALLOW_PROD", raising=False)
    monkeypatch.delenv("LANCE_DSN_GUARD_DISABLE", raising=False)


@pytest.mark.parametrize("host", _DEV_HOSTS)
@pytest.mark.parametrize("prefix", ["postgresql", "postgresql+psycopg"])
def test_dev_target_accepted(host: str, prefix: str) -> None:
    url = f"{prefix}://pottracker_dev:pw@{host}:5433/pottracker"
    # Must not raise.
    assert_target_allowed(url, action="test")


def test_remote_host_refused() -> None:
    url = "postgresql://u:pw@db.prod.internal:5432/lance"
    with pytest.raises(ProdConnectionRefused):
        assert_target_allowed(url, action="test")


def test_local_but_wrong_port_refused() -> None:
    # localhost on the default 5432 is NOT the dev fingerprint (dev is 5433).
    url = "postgresql://u:pw@localhost:5432/pottracker"
    with pytest.raises(ProdConnectionRefused):
        assert_target_allowed(url, action="test")


def test_remote_host_on_5433_still_refused() -> None:
    # Port alone is insufficient — host must also be local.
    url = "postgresql://u:pw@10.0.0.9:5433/pottracker"
    with pytest.raises(ProdConnectionRefused):
        assert_target_allowed(url, action="test")


def test_prod_allowed_with_explicit_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANCE_ALLOW_PROD", "1")
    url = "postgresql://u:pw@db.prod.internal:5432/lance"
    assert_target_allowed(url, action="test")  # must not raise


def test_guard_disabled_skips_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANCE_DSN_GUARD_DISABLE", "1")
    url = "postgresql://u:pw@db.prod.internal:5432/lance"
    assert_target_allowed(url, action="test")  # must not raise


def test_empty_url_noop() -> None:
    assert_target_allowed("", action="test")  # must not raise


def test_non_postgres_url_noop() -> None:
    # sqlite/test URLs never reach a real server; guard ignores them.
    assert_target_allowed("sqlite:///:memory:", action="test")


def test_unparseable_url_noop() -> None:
    assert_target_allowed("not a url", action="test")
