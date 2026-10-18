"""Test fixtures.

All epidemiological data used in tests are SYNTHETIC. Fictional figures are
used even where text imitates the style of official bulletins; nothing here
describes a real outbreak.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

import pytest

os.environ.setdefault("EW_ENV", "test")
os.environ.setdefault("EW_SECRET_KEY", "test-secret-key-test-secret-key-0123456789")
os.environ.setdefault("EW_PSEUDONYM_SALT", "test-salt-test-salt-test-salt-0123456789")

from ebolawatch.config import reset_settings_cache  # noqa: E402

TODAY = date(2031, 6, 30)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("EW_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    reset_settings_cache()
    from ebolawatch.db.session import configure_engine, create_all, session_scope
    from ebolawatch.pipeline.seed import seed_all

    configure_engine(f"sqlite:///{tmp_path / 'test.db'}")
    create_all()
    with session_scope() as s:
        seed_all(s)
    yield session_scope
    reset_settings_cache()


@pytest.fixture()
def session(db):
    from ebolawatch.db.session import SessionLocal

    s = SessionLocal()
    yield s
    s.rollback()
    s.close()


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient

    from ebolawatch.api.app import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


def dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 12, tzinfo=UTC)
