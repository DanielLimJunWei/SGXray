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

-- Failed logins, so password guessing can be slowed down. 'key' is 'email:<address>' or 'ip:<address>'.
-- Kept in the database (not in memory) so the limit still works with several server processes.
CREATE TABLE IF NOT EXISTS login_attempts (
    id           INTEGER PRIMARY KEY,
    key          TEXT NOT NULL,
    attempted_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
CREATE INDEX IF NOT EXISTS login_attempts_key ON login_attempts (key, attempted_at);

-- Logged-in sessions, kept on the server so logging out really ends a session (a copied cookie stops
-- working). Only a SHA-256 hash of each session id is stored: a leaked database can't be used to log in.
CREATE TABLE IF NOT EXISTS sessions (
    id_hash    TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    last_seen  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions (user_id);

-- "Forgot your password?" links. Only a SHA-256 hash of each link's secret is kept, so a leaked
-- database can't be used to reset anyone's password. A link expires, and works once.
CREATE TABLE IF NOT EXISTS password_resets (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    expires_at TEXT NOT NULL,
    used_at    TEXT
);
CREATE INDEX IF NOT EXISTS password_resets_user ON password_resets (user_id);

-- Security events (sign-ups, logins, failed logins, password changes). NEVER passwords or tokens.
CREATE TABLE IF NOT EXISTS security_log (
    id      INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    event   TEXT NOT NULL,
    ip      TEXT,
    at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
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
    """Creates any missing tables and columns. Safe to run every time the app starts."""
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()


# Columns added after a table was first created. CREATE TABLE IF NOT EXISTS skips a table that
# already exists, so it can't add new columns to an existing database: these ALTER TABLEs do.
# Add to the end of this list only; never edit or remove a line once it's been released.
MIGRATIONS = [
    ("dividends", "ignored", "ALTER TABLE dividends ADD COLUMN ignored INTEGER NOT NULL DEFAULT 0"),
    ("users", "session_version", "ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 1"),
]


def _migrate(conn):
    for table, column, sql in MIGRATIONS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(sql)


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
        "SELECT id, email, password_hash, created_at, session_version FROM users WHERE email = ?",
        (email.strip().lower(),),
    ).fetchone()


def get_user(conn, user_id):
    """The user's row by id (for the logged-in session), or None."""
    return conn.execute(
        "SELECT id, email, password_hash, created_at, session_version FROM users WHERE id = ?", (user_id,)
    ).fetchone()


def set_password_hash(conn, user_id, password_hash):
    """Saves a new password hash and bumps session_version, which logs out every other session."""
    with conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, session_version = session_version + 1 WHERE id = ?",
            (password_hash, user_id),
        )


def add_login_attempt(conn, key):
    with conn:
        conn.execute("INSERT INTO login_attempts (key) VALUES (?)", (key,))


def count_login_attempts(conn, key, minutes):
    """Failed logins for a key in the last `minutes` minutes."""
    return conn.execute(
        "SELECT COUNT(*) FROM login_attempts WHERE key = ? AND attempted_at >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)",
        (key, f"-{int(minutes)} minutes"),
    ).fetchone()[0]


def clear_login_attempts(conn, key):
    with conn:
        conn.execute("DELETE FROM login_attempts WHERE key = ?", (key,))


SESSION_DAYS = 7               # a session ends 7 days after login, however active it is
SECURITY_LOG_DAYS = 180        # security events are kept for 6 months, then deleted (they hold network addresses)
ATTEMPT_DAYS = 1               # failed-login counts only matter for minutes; keep them a day at most


def _sid_hash(sid):
    import hashlib
    return hashlib.sha256(sid.encode()).hexdigest()


def create_session(conn, user_id):
    """Starts a server-side session and returns its random id (only its hash is stored)."""
    import secrets
    sid = secrets.token_urlsafe(32)
    with conn:
        conn.execute("INSERT INTO sessions (id_hash, user_id) VALUES (?, ?)", (_sid_hash(sid), user_id))
    return sid


def session_user(conn, sid):
    """The user for a session id, or None if it doesn't exist, was ended, or is older than SESSION_DAYS."""
    if not sid:
        return None
    row = conn.execute(
        """SELECT u.id, u.email, u.password_hash, u.created_at, u.session_version
           FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.id_hash = ? AND s.created_at >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)""",
        (_sid_hash(sid), f"-{SESSION_DAYS} days"),
    ).fetchone()
    if row:
        with conn:
            conn.execute("UPDATE sessions SET last_seen = strftime('%Y-%m-%dT%H:%M:%S', 'now') WHERE id_hash = ?",
                         (_sid_hash(sid),))
    return row


def end_session(conn, sid):
    with conn:
        conn.execute("DELETE FROM sessions WHERE id_hash = ?", (_sid_hash(sid or ""),))


def end_other_sessions(conn, user_id, keep_sid):
    """Logs out every other device (used after a password change)."""
    with conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ? AND id_hash != ?", (user_id, _sid_hash(keep_sid or "")))


def create_password_reset(conn, user_id, minutes):
    """A new reset link's secret for this user (only its hash is stored). Any older link for the same
    user stops working, so only the newest email counts."""
    import secrets
    token = secrets.token_urlsafe(32)                    # 256 random bits: can't be guessed
    with conn:
        conn.execute("DELETE FROM password_resets WHERE user_id = ?", (user_id,))
        conn.execute("INSERT INTO password_resets (token_hash, user_id, expires_at) "
                     "VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%S', 'now', ?))",
                     (_sid_hash(token), user_id, f"+{int(minutes)} minutes"))
    return token


def password_reset_user(conn, token):
    """The user a reset link belongs to, if it's unused and unexpired; else None."""
    return conn.execute(
        """SELECT u.id, u.email, u.password_hash, u.created_at, u.session_version
           FROM password_resets r JOIN users u ON u.id = r.user_id
           WHERE r.token_hash = ? AND r.used_at IS NULL
             AND r.expires_at > strftime('%Y-%m-%dT%H:%M:%S', 'now')""",
        (_sid_hash(token or ""),),
    ).fetchone()


def use_password_reset(conn, token, user_id, password_hash):
    """Sets the new password, if the link is still good, in one step: the link is marked used in the
    same transaction, so two tabs submitting at once can't both use it. Then every session for that
    user ends (every device is logged out) and every reset link is deleted. True if it worked."""
    with conn:
        used = conn.execute(
            """UPDATE password_resets SET used_at = strftime('%Y-%m-%dT%H:%M:%S', 'now')
               WHERE token_hash = ? AND user_id = ? AND used_at IS NULL
                 AND expires_at > strftime('%Y-%m-%dT%H:%M:%S', 'now')""",
            (_sid_hash(token or ""), user_id),
        ).rowcount
        if used != 1:
            return False
        conn.execute("UPDATE users SET password_hash = ?, session_version = session_version + 1 WHERE id = ?",
                     (password_hash, user_id))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM password_resets WHERE user_id = ?", (user_id,))
    return True


def prune(conn):
    """Deletes what SGXray no longer needs: expired sessions, old failed-login counts, old security
    events, and reset links a day after they expire."""
    with conn:
        conn.execute("DELETE FROM password_resets WHERE expires_at < strftime('%Y-%m-%dT%H:%M:%S', 'now', '-1 day')")
        conn.execute("DELETE FROM sessions WHERE created_at < strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)",
                     (f"-{SESSION_DAYS} days",))
        conn.execute("DELETE FROM login_attempts WHERE attempted_at < strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)",
                     (f"-{ATTEMPT_DAYS} days",))
        conn.execute("DELETE FROM security_log WHERE at < strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)",
                     (f"-{SECURITY_LOG_DAYS} days",))


def log_security_event(conn, event, user_id=None, ip=None):
    """Records a security event. Callers must never pass passwords, hashes or tokens."""
    with conn:
        conn.execute("INSERT INTO security_log (user_id, event, ip) VALUES (?, ?, ?)", (user_id, event, ip))


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


def get_trade(conn, user_id, trade_id):
    """One trade, only if it belongs to this user. Someone else's trade id gives None, exactly like
    a trade that doesn't exist, so changing the number in the address shows nothing (no IDOR)."""
    return conn.execute(
        "SELECT id, ticker, trade_date, side, quantity, price, fees FROM trades WHERE id = ? AND user_id = ?",
        (trade_id, user_id),
    ).fetchone()


def update_trade(conn, user_id, trade_id, t):
    """Changes one of this user's trades. Returns True if a trade was changed.
    user_id is in the WHERE, so the database itself refuses to touch another user's trade."""
    with conn:
        cur = conn.execute(
            """
            UPDATE trades SET ticker = ?, trade_date = ?, side = ?, quantity = ?, price = ?, fees = ?
            WHERE id = ? AND user_id = ?
            """,
            (t["ticker"], t["trade_date"], t["side"], t["quantity"], t["price"], t["fees"], trade_id, user_id),
        )
    return cur.rowcount == 1


def delete_trade(conn, user_id, trade_id):
    """Deletes one of this user's trades. Returns True if one was deleted."""
    with conn:
        cur = conn.execute("DELETE FROM trades WHERE id = ? AND user_id = ?", (trade_id, user_id))
    return cur.rowcount == 1


def count_trades(conn, user_id):
    return conn.execute("SELECT COUNT(*) AS n FROM trades WHERE user_id = ?", (user_id,)).fetchone()["n"]


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


def get_earliest_price_date(conn, ticker):
    """The oldest day we have a price for, or None. Used to spot a gap when older trades are added."""
    row = conn.execute(
        "SELECT MIN(price_date) AS earliest FROM prices WHERE ticker = ?", (ticker,)
    ).fetchone()
    return row["earliest"]


def get_next_close(conn, ticker, day):
    """(date, close) of the first saved price AFTER day, or None."""
    row = conn.execute(
        "SELECT price_date, close FROM prices WHERE ticker = ? AND price_date > ? ORDER BY price_date LIMIT 1",
        (ticker, day),
    ).fetchone()
    return (row["price_date"], row["close"]) if row else None


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
                source = 'manual',
                ignored = 0                         -- typing it in means it's real
            """,
            (ticker, ex_date, amount),
        )


def set_dividend_ignored(conn, ticker, ex_date, ignored=True):
    """Marks a dividend as wrong (ignored) or brings it back. It stays in the table, so the
    next yfinance download sees it's already there and doesn't add it again.
    Returns False if there's no such dividend."""
    with conn:
        cur = conn.execute(
            "UPDATE dividends SET ignored = ? WHERE ticker = ? AND ex_date = ?",
            (1 if ignored else 0, ticker, ex_date),
        )
    return cur.rowcount == 1


def get_manual_dividends(conn):
    """Every dividend typed in by hand, for any ticker."""
    return conn.execute(
        "SELECT ticker, ex_date, amount FROM dividends WHERE source = 'manual' ORDER BY ticker, ex_date"
    ).fetchall()


def get_dividends(conn, ticker, include_ignored=True):
    """One ticker's dividends, oldest first. Each row has ex_date, amount, source and ignored."""
    return conn.execute(
        """
        SELECT ex_date, amount, source, ignored
        FROM dividends
        WHERE ticker = ? AND (? OR ignored = 0)
        ORDER BY ex_date
        """,
        (ticker, include_ignored),
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
