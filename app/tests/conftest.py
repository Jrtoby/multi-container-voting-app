"""Shared fixtures for the Flask test suite.

The suite is deliberately service-free: SQLite replaces PostgreSQL and
fakeredis replaces Redis, so `python -m pytest` passes on a laptop with no
containers running. The real services are exercised by
scripts/e2e-test.ps1 / scripts/e2e-test.sh against Docker Compose.

Two import-time details matter here:
  * app/app.py reads DATABASE_URL / SECRET_KEY when it is first imported, so
    the environment is seeded *before* `import app`.
  * app/ is put on sys.path so both `import app` (the module) and the
    app-internal `from models import ...` resolve the way gunicorn resolves
    them inside the container.
"""
import os
import pathlib
import sys
import tempfile

APP_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

# A throwaway file-backed database: one file per session, tables dropped and
# recreated around every test. File-backed (rather than :memory:) because
# Flask-SQLAlchemy hands out pooled connections and an in-memory DB would
# vanish between them.
_TEST_DB = pathlib.Path(tempfile.mkdtemp(prefix="voting-app-tests-")) / "test.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("REDIS_HOST", "localhost")

import fakeredis
import pytest

import app as app_module
from models import db as models_db


@pytest.fixture()
def app():
    app_module.app.config.update(TESTING=True)
    return app_module.app


@pytest.fixture(autouse=True)
def db(app):
    """Give every test a clean schema on the shared SQLite file.

    Named `db` so tests read exactly like the application code.
    """
    with app.app_context():
        models_db.create_all()
        yield models_db
        models_db.session.remove()
        models_db.drop_all()


@pytest.fixture(autouse=True)
def redis_client(monkeypatch):
    """Swap the app's Redis connection for an in-memory fake.

    autouse so a test can never accidentally reach for a real Redis.
    """
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    monkeypatch.setattr(app_module, "r", fake)
    return fake


@pytest.fixture()
def client(app):
    return app.test_client()
