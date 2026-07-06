"""Exercise the REAL db.py wiring (not the test-override) so production
dependency plumbing is covered: engine build, search_path listener, the
get_session unit-of-work, reset_engine."""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.integration

_RAW = os.environ.get("DATABASE_URL", "")


@pytest.fixture(autouse=True)
def _skip_without_db():
    if not _RAW:
        pytest.skip("DATABASE_URL not set")


def test_get_session_yields_and_commits():
    from apps.tooling.api import db

    db.reset_engine()
    gen = db.get_session()
    session = next(gen)
    try:
        # search_path listener applied → unqualified 'machine' resolves to shared.
        val = session.execute(sa.text("SELECT 1")).scalar_one()
        assert val == 1
        assert session.execute(sa.text("SHOW search_path")).scalar_one().replace(" ", "") \
            .startswith("tooling,shared")
    finally:
        # drive the generator to completion (commit + close)
        for _ in gen:
            pass
    db.reset_engine()


def test_get_session_rolls_back_on_error():
    from apps.tooling.api import db

    db.reset_engine()
    gen = db.get_session()
    session = next(gen)
    session.execute(sa.text("SELECT 1"))
    with pytest.raises(RuntimeError):
        gen.throw(RuntimeError("boom"))
    db.reset_engine()
