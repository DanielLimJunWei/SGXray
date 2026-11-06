"""Database layer for SGXray: the tables, the connection, and the basic reads and writes.

All SQL in the app lives in this file, so the rest of the code never builds SQL strings itself.

Run this file directly to create the database and print its tables:
    python src/db.py
"""

import os
import sqlite3
from pathlib import Path

# Where the database file lives. Set SGXRAY_DB to use another file (the tests do this).
# *.db is in .gitignore, so this file never goes to GitHub.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "sgxray.db"


# ---------- Tables ----------

SCHEMA = """
-- People who use the app. Each person sees only their own trades.
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,          -- never the password itself
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Every stock, REIT or ETF the app knows about. Shared by all users.
CREATE TABLE IF NOT EXISTS instruments (
    ticker  TEXT PRIMARY KEY,             -- e.g. 'D05.SI'
    name    TEXT NOT NULL,                -- e.g. 'DBS Group Holdings'
    type    TEXT NOT NULL CHECK (type IN ('stock', 'reit', 'etf')),
    sector  TEXT
);

-- Each buy or sell a user makes.
CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticker      TEXT    NOT NULL REFERENCES instruments(ticker),
    trade_date  TEXT    NOT NULL,         -- 'YYYY-MM-DD'
    side        TEXT    NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity    INTEGER NOT NULL CHECK (quantity > 0),
    price       REAL    NOT NULL CHECK (price > 0),
    fees        REAL    NOT NULL DEFAULT 0 CHECK (fees >= 0),
    created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Most queries ask for one user's trades in date order, so index exactly that.
CREATE INDEX IF NOT EXISTS idx_trades_user_date ON trades (user_id, trade_date);

-- Daily closing prices, saved so we don't download the same day twice. Shared by all users.
CREATE TABLE IF NOT EXISTS prices (
    ticker      TEXT NOT NULL REFERENCES instruments(ticker),
    price_date  TEXT NOT NULL,            -- 'YYYY-MM-DD'
    close       REAL NOT NULL CHECK (close > 0),
    PRIMARY KEY (ticker, price_date)      -- one price per ticker per day
);

-- Dividends per share, by ex-dividend date. Shared by all users.
CREATE TABLE IF NOT EXISTS dividends (
    ticker   TEXT NOT NULL REFERENCES instruments(ticker),
    ex_date  TEXT NOT NULL,               -- 'YYYY-MM-DD'
    amount   REAL NOT NULL CHECK (amount > 0),
    source   TEXT NOT NULL DEFAULT 'yfinance' CHECK (source IN ('yfinance', 'manual')),
    PRIMARY KEY (ticker, ex_date)
);
"""


# ---------- Connection ----------

def get_connection(db_path=None):
    """Opens the database, creating the file if needed, and returns the connection."""
    path = Path(db_path or os.environ.get("SGXRAY_DB", DEFAULT_DB_PATH))
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row             # rows behave like dicts: row["ticker"]
    conn.execute("PRAGMA foreign_keys = ON")   # SQLite ignores REFERENCES unless this is on
    return conn


def init_db(conn):
    """Creates any missing tables. Safe to run every time the app starts."""
    conn.executescript(SCHEMA)
    conn.commit()


# ---------- Users ----------

def create_user(conn, email, password_hash):
    """Adds a user and returns their id. Emails are stored in lower case so 'A@x.com' and 'a@x.com' match."""
    with conn:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash) VALUES (?, ?)",
            (email.strip().lower(), password_hash),
        )
    return cur.lastrowid


def get_user_by_email(conn, email):
    """Returns the user's row, or None if there's no such user."""
    return conn.execute(
        "SELECT id, email, password_hash, created_at FROM users WHERE email = ?",
        (email.strip().lower(),),
    ).fetchone()


# ---------- Instruments ----------

def save_instrument(conn, ticker, name, type_, sector=None):
    """Adds an instrument, or updates its details if the ticker already exists."""
    with conn:
        conn.execute(
            """
            INSERT INTO instruments (ticker, name, type, sector)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (ticker) DO UPDATE SET
                name = excluded.name,
                type = excluded.type,
                sector = excluded.sector
            """,
            (ticker, name, type_, sector),
        )


def get_instruments(conn):
    return conn.execute("SELECT ticker, name, type, sector FROM instruments ORDER BY ticker").fetchall()


# ---------- Trades ----------

def add_trade(conn, user_id, ticker, trade_date, side, quantity, price, fees=0.0):
    """Saves one trade and returns its id. The table's CHECK rules reject impossible values."""
    with conn:
        cur = conn.execute(
            """
            INSERT INTO trades (user_id, ticker, trade_date, side, quantity, price, fees)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, ticker, trade_date, side, quantity, price, fees),
        )
    return cur.lastrowid


def get_trades(conn, user_id):
    """All of one user's trades, oldest first."""
    return conn.execute(
        """
        SELECT id, ticker, trade_date, side, quantity, price, fees
        FROM trades
        WHERE user_id = ?
        ORDER BY trade_date, id
        """,
        (user_id,),
    ).fetchall()


# ---------- Prices ----------

def save_prices(conn, ticker, rows):
    """Saves (price_date, close) pairs for one ticker. Days already saved are skipped.

    Returns how many new days were added.
    """
    before = conn.total_changes
    with conn:
        conn.executemany(
            """
            INSERT INTO prices (ticker, price_date, close)
            VALUES (?, ?, ?)
            ON CONFLICT (ticker, price_date) DO NOTHING
            """,
            [(ticker, price_date, close) for price_date, close in rows],
        )
    return conn.total_changes - before


def get_latest_price_date(conn, ticker):
    """The newest day we have a price for, or None. Used to fetch only newer days."""
    row = conn.execute(
        "SELECT MAX(price_date) AS latest FROM prices WHERE ticker = ?", (ticker,)
    ).fetchone()
    return row["latest"]


def get_prices(conn, ticker, start=None):
    """Saved closing prices for one ticker, oldest first, optionally from a start date."""
    return conn.execute(
        """
        SELECT price_date, close
        FROM prices
        WHERE ticker = ? AND price_date >= COALESCE(?, '0000-00-00')
        ORDER BY price_date
        """,
        (ticker, start),
    ).fetchall()


# ---------- Dividends ----------

def save_dividends(conn, ticker, rows, source="yfinance"):
    """Saves (ex_date, amount) pairs. A manually entered dividend is never overwritten by
    yfinance data, because Yahoo's dividend data has gaps and mistakes.

    Returns how many rows were added or changed.
    """
    before = conn.total_changes
    with conn:
        conn.executemany(
            """
            INSERT INTO dividends (ticker, ex_date, amount, source)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (ticker, ex_date) DO UPDATE SET
                amount = excluded.amount,
                source = excluded.source
            WHERE dividends.source <> 'manual'
            """,
            [(ticker, ex_date, amount, source) for ex_date, amount in rows],
        )
    return conn.total_changes - before


def get_dividends(conn, ticker):
    return conn.execute(
        "SELECT ex_date, amount, source FROM dividends WHERE ticker = ? ORDER BY ex_date",
        (ticker,),
    ).fetchall()


# ---------- Run directly ----------

if __name__ == "__main__":
    conn = get_connection()
    init_db(conn)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ).fetchall()
    print("Database ready:", Path(conn.execute("PRAGMA database_list").fetchone()["file"]).name)
    print("Tables:", ", ".join(t["name"] for t in tables))
    conn.close()
