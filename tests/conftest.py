"""Shared test setup. pytest runs this file before the tests."""

import os
import sys
from pathlib import Path

import pytest

# Let tests import the app's modules (db, importer, ...) from src/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import db  # noqa: E402
from instruments import seed_instruments  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _postgres_test_schemas():
    """With SGXRAY_TEST_PG set (a PostgreSQL URL), every test's database is its own schema there instead of a
    SQLite file (db.get_connection). They are all dropped before and after the run, so each run starts clean.
    Run:  SGXRAY_TEST_PG=postgresql://sgxray:localtest@127.0.0.1:54329/sgxray python -m pytest"""
    url = os.environ.get("SGXRAY_TEST_PG")

    def drop_all():
        import psycopg
        with psycopg.connect(url, autocommit=True) as pg:
            for (name,) in pg.execute("SELECT nspname FROM pg_namespace WHERE nspname LIKE 't!_%' ESCAPE '!'").fetchall():
                pg.execute(f'DROP SCHEMA "{name}" CASCADE')
    if url:
        drop_all()
    yield
    if url:
        drop_all()


@pytest.fixture
def conn(tmp_path):
    """A fresh, empty database for each test, in a temporary folder. The real one is never touched."""
    connection = db.get_connection(tmp_path / "test.db")
    db.init_db(connection)
    seed_instruments(connection)
    yield connection
    connection.close()


@pytest.fixture
def user_id(conn):
    return db.create_user(conn, "test@example.com", "!test")
