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

-- Splits, bonus issues and consolidations. factor = shares you hold after for each share before:
-- 1-for-10 bonus = 1.1, 2-for-1 split = 2.0, 10-to-1 consolidation = 0.1. Shared by all users.
CREATE TABLE IF NOT EXISTS corporate_actions (
    ticker   TEXT NOT NULL REFERENCES instruments(ticker),
    ex_date  TEXT NOT NULL,               -- 'YYYY-MM-DD'
    factor   REAL NOT NULL CHECK (factor > 0 AND factor <> 1),
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


def add_trades(conn, user_id, trades):
    """Saves many trades in one transaction: either all of them are saved or none are.

    Each trade is a dict with ticker, trade_date, side, quantity, price and fees.
    Returns how many were saved.
    """
    with conn:
        conn.executemany(
            """
            INSERT INTO trades (user_id, ticker, trade_date, side, quantity, price, fees)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (user_id, t["ticker"], t["trade_date"], t["side"], t["quantity"], t["price"], t["fees"])
                for t in trades
            ],
        )
    return len(trades)


def get_holdings(conn, user_id):
    """Buys minus sells per ticker, in plain SQL. It doesn't include splits or bonus issues:
    for real holdings use portfolio.positions()."""
    return conn.execute(
        """
        SELECT ticker,
               SUM(CASE WHEN side = 'BUY' THEN quantity ELSE -quantity END) AS shares
        FROM trades
        WHERE user_id = ?
        GROUP BY ticker
        HAVING SUM(CASE WHEN side = 'BUY' THEN quantity ELSE -quantity END) > 0
        ORDER BY ticker
        """,
        (user_id,),
    ).fetchall()


def get_traded_tickers(conn):
    """Every ticker anyone has traded. These are the ones that need prices."""
    rows = conn.execute("SELECT DISTINCT ticker FROM trades ORDER BY ticker").fetchall()
    return [r["ticker"] for r in rows]


def get_first_trade_date(conn, ticker=None):
    """The earliest trade date for one ticker, or for all tickers if none is given. None if no trades."""
    row = conn.execute(
        "SELECT MIN(trade_date) AS first FROM trades WHERE ? IS NULL OR ticker = ?",
        (ticker, ticker),
    ).fetchone()
    return row["first"]


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


def get_trading_days(conn):
    """Every day SGX traded, as far as our saved prices know: any day with a price for any ticker."""
    rows = conn.execute("SELECT DISTINCT price_date FROM prices ORDER BY price_date").fetchall()
    return [r["price_date"] for r in rows]


def get_close(conn, ticker, day):
    """The closing price of one ticker on one day, or None if we don't have it."""
    row = conn.execute(
        "SELECT close FROM prices WHERE ticker = ? AND price_date = ?", (ticker, day)
    ).fetchone()
    return row["close"] if row else None


def get_latest_close(conn, ticker, as_of=None):
    """The newest saved close on or before as_of ('YYYY-MM-DD'; default: newest of all).

    Returns (price_date, close), or None if we have no price yet.
    """
    row = conn.execute(
        """
        SELECT price_date, close
        FROM prices
        WHERE ticker = ? AND price_date <= COALESCE(?, '9999-12-31')
        ORDER BY price_date DESC
        LIMIT 1
        """,
        (ticker, as_of),
    ).fetchone()
    return (row["price_date"], row["close"]) if row else None


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
            WHERE dividends.source <> 'manual'           -- hand-entered amounts always win
              AND dividends.amount <> excluded.amount    -- only count real changes
            """,
            [(ticker, ex_date, amount, source) for ex_date, amount in rows],
        )
    return conn.total_changes - before


def set_manual_dividend(conn, ticker, ex_date, amount):
    """Saves a dividend typed in by hand. Unlike save_dividends, it always wins: it replaces
    whatever was there (from yfinance or an earlier manual entry) and marks it 'manual'."""
    with conn:
        conn.execute(
            """
            INSERT INTO dividends (ticker, ex_date, amount, source)
            VALUES (?, ?, ?, 'manual')
            ON CONFLICT (ticker, ex_date) DO UPDATE SET
                amount = excluded.amount,
                source = 'manual'
            """,
            (ticker, ex_date, amount),
        )


def get_manual_dividends(conn):
    """Every dividend typed in by hand, for any ticker."""
    return conn.execute(
        "SELECT ticker, ex_date, amount FROM dividends WHERE source = 'manual' ORDER BY ticker, ex_date"
    ).fetchall()


def get_dividends(conn, ticker):
    return conn.execute(
        "SELECT ex_date, amount, source FROM dividends WHERE ticker = ? ORDER BY ex_date",
        (ticker,),
    ).fetchall()


# ---------- Corporate actions ----------

def save_actions(conn, ticker, rows):
    """Saves (ex_date, factor) pairs from yfinance. Returns how many were added or changed.

    A manual entry on the same date is left alone.
    """
    before = conn.total_changes
    with conn:
        conn.executemany(
            """
            INSERT INTO corporate_actions (ticker, ex_date, factor, source)
            VALUES (?, ?, ?, 'yfinance')
            ON CONFLICT (ticker, ex_date) DO UPDATE SET factor = excluded.factor
            WHERE corporate_actions.source <> 'manual'
              AND corporate_actions.factor <> excluded.factor
            """,
            [(ticker, ex_date, factor) for ex_date, factor in rows],
        )
    return conn.total_changes - before


def add_manual_action(conn, ticker, ex_date, factor):
    """Saves a split or bonus issue that Yahoo doesn't know about."""
    with conn:
        conn.execute(
            "INSERT INTO corporate_actions (ticker, ex_date, factor, source) VALUES (?, ?, ?, 'manual')",
            (ticker, ex_date, factor),
        )


def get_actions(conn, ticker, source=None):
    """One ticker's corporate actions, oldest first, optionally only from one source."""
    return conn.execute(
        """
        SELECT ex_date, factor, source
        FROM corporate_actions
        WHERE ticker = ? AND (? IS NULL OR source = ?)
        ORDER BY ex_date
        """,
        (ticker, source, source),
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
