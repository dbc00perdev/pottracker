"""Fixtures for API tests.

Integration tests hit the live dev Postgres (DATABASE_URL, migrated to head).
Isolation: each test runs inside an outer transaction on a single connection
that is rolled back at teardown — nothing persists. The app's `get_session`
dependency is overridden to yield sessions bound to that same connection
(`join_transaction_mode="create_savepoint"`), so the app's per-request commits
become savepoint releases the outer rollback still undoes.

All API integration tests are marked `integration` and skip without DATABASE_URL.
"""

from __future__ import annotations

import os
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from apps.tooling.api.config import Settings, get_settings
from apps.tooling.api.db import get_session
from apps.tooling.api.main import create_app
from apps.tooling.api.security import create_access_token, hash_password
from shared.db import machine as machine_t
from shared.db import user as user_t

_RAW_URL = os.environ.get("DATABASE_URL", "")
_URL = _RAW_URL.replace("postgresql://", "postgresql+psycopg://", 1) if _RAW_URL else ""

pytestmark = pytest.mark.integration

_TEST_SETTINGS = Settings(
    database_url=_URL,
    jwt_secret="test-secret-not-for-prod",
    jwt_access_ttl=900,
    jwt_refresh_ttl=86400,
    log_level="INFO",
)


@pytest.fixture(scope="session")
def engine() -> sa.Engine:
    if not _URL:
        pytest.skip("DATABASE_URL not set — API integration tests skipped")
    eng = sa.create_engine(_URL, future=True)

    @sa.event.listens_for(eng, "connect")
    def _sp(dbapi_conn, _rec):
        with dbapi_conn.cursor() as cur:
            cur.execute("SET search_path TO tooling, shared")

    return eng


@pytest.fixture
def conn(engine: sa.Engine):
    connection = engine.connect()
    txn = connection.begin()
    try:
        yield connection
    finally:
        txn.rollback()
        connection.close()


@pytest.fixture
def db_session(conn) -> Session:
    """Direct session for seeding — shares the test transaction."""
    maker = sessionmaker(bind=conn, join_transaction_mode="create_savepoint",
                         expire_on_commit=False, future=True)
    s = maker()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client(conn):
    from fastapi.testclient import TestClient

    maker = sessionmaker(bind=conn, join_transaction_mode="create_savepoint",
                         expire_on_commit=False, future=True)

    def _override_session():
        s = maker()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    app = create_app()
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_settings] = lambda: _TEST_SETTINGS
    with TestClient(app) as c:
        yield c


# --- seeding helpers ---------------------------------------------------------

@pytest.fixture
def seed_users(db_session: Session) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for role in ("viewer", "operator", "setter", "admin"):
        uid = uuid.uuid4()
        db_session.execute(sa.insert(user_t).values(
            id=uid, username=f"{role}_u", display_name=role.title(),
            role=role, password_hash=hash_password("pw-" + role),
        ))
        out[role] = {"id": uid, "username": f"{role}_u", "password": "pw-" + role, "role": role}
    db_session.commit()  # release savepoint; visible to app request-sessions on the same conn
    return out


@pytest.fixture
def viper(db_session: Session) -> dict:
    """Viper LG-1000AP with the probe locked at T50/H50 (Decision-4)."""
    mid = uuid.uuid4()
    db_session.execute(sa.insert(machine_t).values(
        id=mid, name="Viper LG-1000AP", control_model="FANUC 0i-MF",
        ip_address="10.1.10.58", focas_port=8193, pot_count=24,
        probe_pot=None, probe_t_number=50, probe_h_register=50,
        offset_register_count=400, atc_strategy="random_access",
        has_tsc=True, has_toolsetter=True, poll_interval_seconds=60, enabled=True,
    ))
    db_session.commit()
    return {"id": mid, "name": "Viper LG-1000AP"}


@pytest.fixture
def no_tsc_machine(db_session: Session) -> dict:
    mid = uuid.uuid4()
    db_session.execute(sa.insert(machine_t).values(
        id=mid, name="AG100", control_model="FANUC 30i-B",
        ip_address="10.1.10.59", focas_port=8193, pot_count=24,
        offset_register_count=400, atc_strategy="random_access",
        has_tsc=False, has_toolsetter=True, poll_interval_seconds=60, enabled=True,
    ))
    db_session.commit()
    return {"id": mid, "name": "AG100"}


def token_for(user: dict) -> str:
    return create_access_token(
        _TEST_SETTINGS, user_id=str(user["id"]), username=user["username"], role=user["role"])


def auth(user: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(user)}"}


@pytest.fixture
def tool_type_id(client, seed_users) -> str:
    resp = client.post("/api/tooling/tool-types",
                       json={"code": "em_square", "display_name": "Square Endmill"},
                       headers=auth(seed_users["admin"]))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]
