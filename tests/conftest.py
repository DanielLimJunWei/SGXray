"""Shared test setup. pytest runs this file before the tests."""

import sys
from pathlib import Path

import pytest

# Let tests import the app's modules (db, importer, ...) from src/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import db  # noqa: E402
from instruments import seed_instruments  # noqa: E402


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
