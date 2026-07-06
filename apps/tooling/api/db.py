"""Database engine + per-request session dependency.

Sync SQLAlchemy (psycopg3). The engine sets `search_path` to `tooling, shared`
on every pooled connection so unqualified identifiers resolve safely and the
app never touches `public` or `tracker` by accident (mirrors the migration
connection's lockdown).

`get_session` yields a Session inside a transaction and commits on clean exit,
rolls back on exception — the standard FastAPI unit-of-work. Routers do NOT
commit; they let the dependency own the boundary (audit rows + domain writes
land atomically).
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from apps.tooling.api.config import Settings, get_settings

_engine: Engine | None = None
_Session: sessionmaker[Session] | None = None


def _build_engine(settings: Settings) -> Engine:
    engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)

    @event.listens_for(engine, "connect")
    def _set_search_path(dbapi_conn, _record):
        with dbapi_conn.cursor() as cur:
            cur.execute("SET search_path TO tooling, shared")

    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _build_engine(get_settings())
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    global _Session
    if _Session is None:
        _Session = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _Session


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one transactional session per request."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Test hook: drop cached engine/sessionmaker so a new DATABASE_URL/Settings
    takes effect."""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Session = None
