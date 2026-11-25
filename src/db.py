"""Database layer for SGXray: the tables, the connection, and the basic reads and writes.

Two databases, one set of SQL (w408):
- SQLite (a file, data/sgxray.db) on your own computer and in the tests;
- PostgreSQL when DATABASE_URL is set (the live site: Render's free disk is wiped on every restart, so a file
  database would lose every account and trade).
The SQL is written to work on both (RETURNING, ON CONFLICT, string_agg, times passed in from Python). The few
differences are handled here: the column types in the schema, `?` placeholders, and how rows are read.

Run this file directly to create the database and print its tables:
    python src/db.py
"""

import hashlib
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fmt

try:                                   # only needed for PostgreSQL
    import psycopg
    from psycopg.types.numeric import FloatLoader
except ImportError:                    # pragma: no cover
    psycopg = None

# A broken rule (a duplicate email, a CHECK) raises one of these, whichever database is in use.
IntegrityError = (sqlite3.IntegrityError,) + ((psycopg.errors.IntegrityError,) if psycopg else ())

# Where the database file lives. Set SGXRAY_DB to use another file (the tests do this).
# *.db is in .gitignore, so this file never goes to GitHub.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "sgxray.db"


# ---------- Tables ----------

SCHEMA = """
-- People who use the app. Each person sees only their own trades.
CREATE TABLE IF NOT EXISTS users (
    id            {ID},
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,          -- never the password itself
    created_at    TEXT NOT NULL DEFAULT {NOW}
);

-- Failed logins, so password guessing can be slowed down. 'key' is 'email:<address>' or 'ip:<address>'.
-- Kept in the database (not in memory) so the limit still works with several server processes.
CREATE TABLE IF NOT EXISTS login_attempts (
    id           {ID},
    key          TEXT NOT NULL,
    attempted_at TEXT NOT NULL DEFAULT {NOW_T}
);
CREATE INDEX IF NOT EXISTS login_attempts_key ON login_attempts (key, attempted_at);

-- Logged-in sessions, kept on the server so logging out really ends a session (a copied cookie stops
-- working). Only a SHA-256 hash of each session id is stored: a leaked database can't be used to log in.
CREATE TABLE IF NOT EXISTS sessions (
    id_hash    TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT {NOW_T},
    last_seen  TEXT NOT NULL DEFAULT {NOW_T}
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions (user_id);

-- "Forgot your password?" links. Only a SHA-256 hash of each link's secret is kept, so a leaked
-- database can't be used to reset anyone's password. A link expires, and works once.
CREATE TABLE IF NOT EXISTS password_resets (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT {NOW_T},
    expires_at TEXT NOT NULL,
    used_at    TEXT
);
CREATE INDEX IF NOT EXISTS password_resets_user ON password_resets (user_id);

-- Security events (sign-ups, logins, failed logins, password changes). NEVER passwords or tokens.
CREATE TABLE IF NOT EXISTS security_log (
    id      {ID},
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    event   TEXT NOT NULL,
    ip      TEXT,
    at      TEXT NOT NULL DEFAULT {NOW_T}
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
    id          {ID},
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticker      TEXT    NOT NULL REFERENCES instruments(ticker),
    trade_date  TEXT    NOT NULL,         -- 'YYYY-MM-DD'
    side        TEXT    NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity    INTEGER NOT NULL CHECK (quantity > 0),
    price       REAL    NOT NULL CHECK (price > 0),
    fees        REAL    NOT NULL DEFAULT 0 CHECK (fees >= 0),
    created_at  TEXT    NOT NULL DEFAULT {NOW}
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

-- Regular savings plans (w314): "I invest $X in this stock every month, on this day". SGXray records each
-- month's purchase itself (src/plans.py). Stopping a plan sets end_month; deleting it deletes its trades.
CREATE TABLE IF NOT EXISTS plans (
    id          {ID},
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticker      TEXT    NOT NULL REFERENCES instruments(ticker),
    amount      REAL    NOT NULL CHECK (amount >= 1 AND amount <= 100000),
    day         INTEGER NOT NULL CHECK (day BETWEEN 1 AND 28),
    start_month TEXT    NOT NULL,        -- 'YYYY-MM'
    end_month   TEXT,                    -- the last month it bought, once stopped; NULL while running
    fee_rate    REAL    NOT NULL DEFAULT 0 CHECK (fee_rate >= 0 AND fee_rate <= 0.05),
    fee_min     REAL    NOT NULL DEFAULT 0 CHECK (fee_min >= 0 AND fee_min <= 100),
    created_at  TEXT    NOT NULL DEFAULT {NOW}
);

-- News headlines (w312) from a few credible publishers' public feeds: only the headline as published, the
-- source, the date and the link to the full article. Shared by everyone; kept 60 days.
CREATE TABLE IF NOT EXISTS news (
    id         {ID},
    url        TEXT NOT NULL UNIQUE,
    title      TEXT NOT NULL,
    summary    TEXT,                     -- the publisher's own one-line standfirst from the feed, if it has one
    source     TEXT NOT NULL,
    published  TEXT NOT NULL,            -- 'YYYY-MM-DDTHH:MM' Singapore time
    fetched_at TEXT NOT NULL DEFAULT {NOW}
);
-- Which stocks each headline mentions.
CREATE TABLE IF NOT EXISTS news_tickers (
    news_id INTEGER NOT NULL REFERENCES news(id) ON DELETE CASCADE,
    ticker  TEXT    NOT NULL,
    PRIMARY KEY (news_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_news_tickers_ticker ON news_tickers (ticker);

-- Which lessons on the Learn page (w313) each person has finished. Only the lesson's short name and
-- when: nothing about how they answered. Deleted with the account.
CREATE TABLE IF NOT EXISTS lesson_reads (
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lesson   TEXT    NOT NULL,           -- the lesson's slug, e.g. 'first-dollar'
    read_at  TEXT    NOT NULL DEFAULT {NOW},
    PRIMARY KEY (user_id, lesson)        -- reading it twice still counts once
);
"""


# ---------- Connection ----------

# The schema's few words that differ: an auto-numbered id, a decimal number, and "now" as text in UTC
# ('2026-11-25T09:30:00' in the security tables, '2026-11-25 09:30:00' elsewhere, as SQLite always wrote them).
DIALECT = {
    "sqlite": {"ID": "INTEGER PRIMARY KEY", "REAL": "REAL",
               "NOW_T": "(strftime('%Y-%m-%dT%H:%M:%S', 'now'))", "NOW": "CURRENT_TIMESTAMP"},
    "postgres": {"ID": "INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY", "REAL": "DOUBLE PRECISION",
                 "NOW_T": """(to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS'))""",
                 "NOW": "(to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))"},
}


def get_connection(db_path=None):
    """Opens the database and returns the connection: PostgreSQL if DATABASE_URL is set, else the SQLite file
    (created if needed). SGXRAY_TEST_PG runs the tests on PostgreSQL: each test's file path gets its own schema."""
    url, test_url = os.environ.get("DATABASE_URL"), os.environ.get("SGXRAY_TEST_PG")
    path = Path(db_path or os.environ.get("SGXRAY_DB", DEFAULT_DB_PATH))
    if url:
        return PgConnection(url)
    if test_url:
        return PgConnection(test_url, schema=test_schema(path))
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row             # rows behave like dicts: row["ticker"]
    conn.execute("PRAGMA foreign_keys = ON")   # SQLite ignores REFERENCES unless this is on
    return conn


def test_schema(path):
    """The PostgreSQL schema standing in for one test's database file."""
    return "t_" + hashlib.sha1(str(Path(path).resolve()).encode()).hexdigest()[:20]


def is_postgres(conn):
    return isinstance(conn, PgConnection)


def schema_sql(dialect):
    """The tables for one database. REAL is swapped too: PostgreSQL's REAL keeps only about 7 digits."""
    words = DIALECT[dialect]
    text = re.sub(r"\bREAL\b", words["REAL"], SCHEMA)
    for key in ("ID", "NOW_T", "NOW"):
        text = text.replace("{" + key + "}", words[key])
    return text


# Any fixed number: the PostgreSQL lock that lets only one server worker set up the tables at a time.
SCHEMA_LOCK = 0x5367587261790001


def init_db(conn):
    """Creates any missing tables and columns. Safe to run every time the app starts."""
    if is_postgres(conn):
        # The live site starts several workers at once, and each runs this. On a brand-new database two of them
        # creating the same table together makes one crash, so they take turns: the lock is held until this
        # transaction ends, and the next worker then finds the tables already there.
        # And when every table and index is already there, the script is skipped: "CREATE INDEX IF NOT EXISTS"
        # still locks its table first, which can deadlock with a worker that's already deleting old rows (prune).
        with conn:
            conn.execute("SELECT pg_advisory_xact_lock(?)", (SCHEMA_LOCK,))
            if not _schema_complete(conn):
                conn.execute_script(schema_sql("postgres"))
            _migrate(conn)
        return
    else:
        conn.executescript(schema_sql("sqlite"))
    _migrate(conn)
    conn.commit()


def _schema_complete(conn):
    """True when every table and index in SCHEMA already exists (PostgreSQL only)."""
    want_tables = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", SCHEMA))
    want_indexes = set(re.findall(r"CREATE (?:UNIQUE )?INDEX IF NOT EXISTS (\w+)", SCHEMA))
    have_indexes = {r[0] for r in conn.execute(
        "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()").fetchall()}
    return want_tables <= set(tables(conn)) and want_indexes <= have_indexes


def columns(conn, table):
    """The names of a table's columns."""
    if is_postgres(conn):
        rows = conn.execute("SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = current_schema() AND table_name = ?", (table,)).fetchall()
        return {r[0] for r in rows}
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}   # table: from the code, never input


def tables(conn):
    """The names of the tables, sorted."""
    if is_postgres(conn):
        sql = ("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() "
               "ORDER BY table_name")
    else:
        sql = "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    return [r[0] for r in conn.execute(sql).fetchall()]


def utc_text(**delta):
    """Now in UTC as the security tables store it ('2026-11-25T09:30:00'), moved by delta (e.g. minutes=-15).
    Passing the time in from Python keeps the SQL the same on both databases."""
    return (datetime.now(timezone.utc) + timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%S")


# ---------- PostgreSQL, made to behave like sqlite3 ----------

class Row:
    """A row you can read by name (row["ticker"]) or position (row[0]), and turn into a dict, like sqlite3.Row."""
    __slots__ = ("_values", "_index")

    def __init__(self, values, index):
        self._values, self._index = values, index

    def __getitem__(self, key):
        return self._values[self._index[key] if isinstance(key, str) else key]

    def keys(self):
        return list(self._index)

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __eq__(self, other):
        return tuple(self) == tuple(other)

    __hash__ = None

    def __repr__(self):
        return f"Row({dict(zip(self._index, self._values))})"


def _row_factory(cursor):
    index = {c.name: i for i, c in enumerate(cursor.description or [])}
    return lambda values: Row(values, index)


def _placeholders(sql):
    """`?` becomes %s and a literal % becomes %%, outside quoted text: psycopg's placeholder style."""
    out, quote = [], None
    for ch in sql:
        if quote:
            out.append("%%" if ch == "%" else ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "?":
            out.append("%s")
        elif ch == "%":
            out.append("%%")
        else:
            out.append(ch)
    return "".join(out)


def _tls(url):
    """Encrypted connections to any database not on this computer, even if the address forgets to ask."""
    info = psycopg.conninfo.conninfo_to_dict(url)
    local = info.get("host", "localhost") in ("localhost", "127.0.0.1", "::1") or str(info.get("host", "")).startswith("/")
    return {} if local or info.get("sslmode") else {"sslmode": "require"}


class PgConnection:
    """A PostgreSQL connection with the parts of sqlite3's API that SGXray uses: execute (with `?`),
    executemany, rows by name, `with conn:` as one transaction, commit and close. A statement on its own is
    saved at once (autocommit); `with conn:` groups statements so they all happen or none do."""

    def __init__(self, url, schema=None):
        if psycopg is None:
            raise RuntimeError("DATABASE_URL is set, but psycopg isn't installed (pip install -r requirements.txt)")
        # Client-side binding: psycopg quotes each value into the SQL itself, so `? IS NULL` works as in SQLite.
        self._pg = psycopg.connect(url, autocommit=True, cursor_factory=psycopg.ClientCursor,
                                   row_factory=_row_factory, connect_timeout=10, **_tls(url))
        self._pg.adapters.register_loader("numeric", FloatLoader)   # SUM() of whole numbers: a float, not Decimal
        self._tx = []
        if schema:                                                   # tests only: a schema per test database
            self._pg.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            self._pg.execute(f'SET search_path TO "{schema}"')

    def execute(self, sql, params=()):
        cur = self._pg.cursor()
        if params:
            cur.execute(_placeholders(sql), tuple(params))
        else:
            cur.execute(sql)
        return cur

    def executemany(self, sql, rows):
        cur = self._pg.cursor()
        rows = [tuple(r) for r in rows]
        if rows:
            cur.executemany(_placeholders(sql), rows)
        return cur

    def execute_script(self, script):
        self._pg.execute(script)

    def __enter__(self):
        tx = self._pg.transaction()
        tx.__enter__()
        self._tx.append(tx)
        return self

    def __exit__(self, *exc):
        return self._tx.pop().__exit__(*exc)

    def commit(self):
        pass                                     # autocommit: each statement outside `with conn:` is already saved

    def rollback(self):
        pass

    def close(self):
        self._pg.close()


# Columns added after a table was first created. CREATE TABLE IF NOT EXISTS skips a table that
# already exists, so it can't add new columns to an existing database: these ALTER TABLEs do.
# Add to the end of this list only; never edit or remove a line once it's been released.
MIGRATIONS = [
    ("dividends", "ignored", "ALTER TABLE dividends ADD COLUMN ignored INTEGER NOT NULL DEFAULT 0"),
    ("users", "session_version", "ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 1"),
    # "Why I bought" (w317): your own reason for a trade, in your words. Optional, so NULL for most trades.
    ("trades", "note", "ALTER TABLE trades ADD COLUMN note TEXT CHECK (note IS NULL OR length(note) <= 280)"),
    # Practice portfolio (w320): each account's hidden "practice twin" points back to its owner, and is
    # deleted with it. The twin also keeps the practice fee settings (NULL = the typical fee).
    ("users", "practice_of", "ALTER TABLE users ADD COLUMN practice_of INTEGER REFERENCES users(id) ON DELETE CASCADE"),
    ("users", "fee_rate", "ALTER TABLE users ADD COLUMN fee_rate REAL CHECK (fee_rate IS NULL OR (fee_rate >= 0 AND fee_rate <= 0.02))"),
    ("users", "fee_min", "ALTER TABLE users ADD COLUMN fee_min REAL CHECK (fee_min IS NULL OR (fee_min >= 0 AND fee_min <= 100))"),
    # Regular savings plans (w314): a trade the plan recorded, and the month it was for (so it's made once).
    ("trades", "plan_id", "ALTER TABLE trades ADD COLUMN plan_id INTEGER REFERENCES plans(id) ON DELETE CASCADE"),
    ("trades", "plan_month", "ALTER TABLE trades ADD COLUMN plan_month TEXT"),
    ("news", "summary", "ALTER TABLE news ADD COLUMN summary TEXT"),
    # "Add a stock I already own": one buy at your average cost on a rough date, until the real trades are in.
    ("trades", "approx", "ALTER TABLE trades ADD COLUMN approx INTEGER NOT NULL DEFAULT 0 CHECK (approx IN (0, 1))"),
]


def _migrate(conn):
    for table, column, sql in MIGRATIONS:
        if column not in columns(conn, table):
            conn.execute(re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql) if is_postgres(conn) else sql)


# ---------- Users ----------

def create_user(conn, email, password_hash):
    """Adds a user and returns their id. Emails are stored in lower case so 'A@x.com' and 'a@x.com' match."""
    with conn:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash) VALUES (?, ?) RETURNING id",
            (email.strip().lower(), password_hash),
        )
        return cur.fetchone()[0]


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
        "SELECT COUNT(*) FROM login_attempts WHERE key = ? AND attempted_at >= ?",
        (key, utc_text(minutes=-int(minutes))),
    ).fetchone()[0]


def login_attempt_times(conn, key, hours=24):
    """The times (UTC datetimes, oldest first) of a key's failed logins in the last `hours` hours."""
    from datetime import datetime
    rows = conn.execute(
        "SELECT attempted_at FROM login_attempts WHERE key = ? AND attempted_at >= ? "
        "ORDER BY attempted_at, id", (key, utc_text(hours=-int(hours)))).fetchall()
    return [datetime.fromisoformat(r[0]) for r in rows]


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
           WHERE s.id_hash = ? AND s.created_at >= ?""",
        (_sid_hash(sid), utc_text(days=-SESSION_DAYS)),
    ).fetchone()
    if row:
        with conn:
            conn.execute("UPDATE sessions SET last_seen = ? WHERE id_hash = ?", (utc_text(), _sid_hash(sid)))
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
                     "VALUES (?, ?, ?)", (_sid_hash(token), user_id, utc_text(minutes=int(minutes))))
    return token


def password_reset_user(conn, token):
    """The user a reset link belongs to, if it's unused and unexpired; else None."""
    return conn.execute(
        """SELECT u.id, u.email, u.password_hash, u.created_at, u.session_version
           FROM password_resets r JOIN users u ON u.id = r.user_id
           WHERE r.token_hash = ? AND r.used_at IS NULL
             AND r.expires_at > ?""",
        (_sid_hash(token or ""), utc_text()),
    ).fetchone()


def use_password_reset(conn, token, user_id, password_hash):
    """Sets the new password, if the link is still good, in one step: the link is marked used in the
    same transaction, so two tabs submitting at once can't both use it. Then every session for that
    user ends (every device is logged out) and every reset link is deleted. True if it worked."""
    with conn:
        used = conn.execute(
            """UPDATE password_resets SET used_at = ?
               WHERE token_hash = ? AND user_id = ? AND used_at IS NULL AND expires_at > ?""",
            (utc_text(), _sid_hash(token or ""), user_id, utc_text()),
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
        conn.execute("DELETE FROM password_resets WHERE expires_at < ?", (utc_text(days=-1),))
        conn.execute("DELETE FROM sessions WHERE created_at < ?", (utc_text(days=-SESSION_DAYS),))
        conn.execute("DELETE FROM login_attempts WHERE attempted_at < ?", (utc_text(days=-ATTEMPT_DAYS),))
        conn.execute("DELETE FROM security_log WHERE at < ?", (utc_text(days=-SECURITY_LOG_DAYS),))


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

def add_trade(conn, user_id, ticker, trade_date, side, quantity, price, fees=0.0, note=None):
    """Saves one trade and returns its id. The table's CHECK rules reject impossible values. Fees are kept in
    whole cents (fmt.cents), as a broker charges them; the price keeps its decimals (SGX prices go to 0.001).
    note is your "why I bought / sold", or None."""
    with conn:
        cur = conn.execute(
            """
            INSERT INTO trades (user_id, ticker, trade_date, side, quantity, price, fees, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id
            """,
            (user_id, ticker, trade_date, side, quantity, price, fmt.cents(fees), note or None),
        )
        return cur.fetchone()[0]


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
                (user_id, t["ticker"], t["trade_date"], t["side"], t["quantity"], t["price"], fmt.cents(t["fees"]))
                for t in trades
            ],
        )
    return len(trades)


def get_trade(conn, user_id, trade_id):
    """One trade, only if it belongs to this user. Someone else's trade id gives None, exactly like
    a trade that doesn't exist, so changing the number in the address shows nothing (no IDOR)."""
    return conn.execute(
        "SELECT id, ticker, trade_date, side, quantity, price, fees, note, plan_id, approx FROM trades WHERE id = ? AND user_id = ?",
        (trade_id, user_id),
    ).fetchone()


def update_trade(conn, user_id, trade_id, t):
    """Changes one of this user's trades. Returns True if a trade was changed.
    user_id is in the WHERE, so the database itself refuses to touch another user's trade."""
    with conn:
        cur = conn.execute(
            """
            UPDATE trades SET ticker = ?, trade_date = ?, side = ?, quantity = ?, price = ?, fees = ?, note = ?
            WHERE id = ? AND user_id = ?
            """,
            (t["ticker"], t["trade_date"], t["side"], t["quantity"], t["price"], fmt.cents(t["fees"]), t.get("note") or None,
             trade_id, user_id),
        )
    return cur.rowcount == 1


def set_note(conn, user_id, trade_id, note):
    """Changes only the "why I bought / sold" note of one of this user's trades (None clears it). Returns True
    if a trade was changed. user_id is in the WHERE, so nobody can edit someone else's note."""
    with conn:
        cur = conn.execute("UPDATE trades SET note = ? WHERE id = ? AND user_id = ?", (note or None, trade_id, user_id))
    return cur.rowcount == 1


def mark_approx(conn, user_id, trade_id):
    """Marks a trade as "a stock I already own": average cost and a rough date, not a real contract note."""
    with conn:
        conn.execute("UPDATE trades SET approx = 1 WHERE id = ? AND user_id = ?", (trade_id, user_id))


def delete_trade(conn, user_id, trade_id):
    """Deletes one of this user's trades. Returns True if one was deleted."""
    with conn:
        cur = conn.execute("DELETE FROM trades WHERE id = ? AND user_id = ?", (trade_id, user_id))
    return cur.rowcount == 1


def count_trades(conn, user_id):
    return conn.execute("SELECT COUNT(*) AS n FROM trades WHERE user_id = ?", (user_id,)).fetchone()["n"]


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
        SELECT id, ticker, trade_date, side, quantity, price, fees, note, approx
        FROM trades
        WHERE user_id = ?
        ORDER BY trade_date, id
        """,
        (user_id,),
    ).fetchall()


# ---------- Practice portfolio (w320) ----------

PRACTICE_HASH = "!practice-no-login"     # starts with "!": auth.check_login and the reset form refuse it


def practice_user(conn, owner_id):
    """The hidden "practice twin" of this account, made the first time it's needed. It can't log in or
    get a reset email (its password is the "!" no-login marker, like the demo), and it's deleted with
    its owner. Every calculation then works on it exactly as on a real portfolio."""
    row = conn.execute("SELECT * FROM users WHERE practice_of = ?", (owner_id,)).fetchone()
    if row is not None:
        return row
    with conn:
        conn.execute("INSERT INTO users (email, password_hash, practice_of) VALUES (?, ?, ?)",
                     (f"practice-{owner_id}@practice.invalid", PRACTICE_HASH, owner_id))
    return conn.execute("SELECT * FROM users WHERE practice_of = ?", (owner_id,)).fetchone()


def set_practice_fees(conn, twin_id, rate, minimum):
    """Your own broker's fee for practice trades, or (None, None) for the typical fee."""
    with conn:
        conn.execute("UPDATE users SET fee_rate = ?, fee_min = ? WHERE id = ? AND practice_of IS NOT NULL",
                     (rate, minimum, twin_id))


def delete_all_trades(conn, user_id):
    """Start over: every trade of this (practice) user. Returns how many were deleted."""
    with conn:
        cur = conn.execute("DELETE FROM trades WHERE user_id = ?", (user_id,))
    return cur.rowcount


def latest_close(conn, ticker):
    """(date, close) of the newest saved price, or None."""
    row = conn.execute("SELECT price_date, close FROM prices WHERE ticker = ? ORDER BY price_date DESC LIMIT 1",
                       (ticker,)).fetchone()
    return (row["price_date"], row["close"]) if row else None


# ---------- Lessons read (w313) ----------

def mark_lesson_read(conn, user_id, lesson):
    """Remembers that this person finished a lesson. Doing it again changes nothing."""
    with conn:
        conn.execute("INSERT INTO lesson_reads (user_id, lesson) VALUES (?, ?) ON CONFLICT DO NOTHING",
                     (user_id, lesson))


def lessons_read(conn, user_id):
    """The slugs of the lessons this person has finished, as a set."""
    rows = conn.execute("SELECT lesson FROM lesson_reads WHERE user_id = ?", (user_id,)).fetchall()
    return {r["lesson"] for r in rows}


# ---------- Your data: download it, or delete the account (audit 4, PDPA) ----------

def export_data(conn, user_id):
    """Everything SGXray keeps about one person, as plain lists and dicts (for "Download my data"). Never a
    password hash, session or reset secret: those are hashes of secrets, useless to the person and risky to hand out."""
    user = conn.execute("SELECT email, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    twin = conn.execute("SELECT id, fee_rate, fee_min FROM users WHERE practice_of = ?", (user_id,)).fetchone()

    def rows(sql, *args):
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    trade_sql = ("SELECT trade_date AS date, ticker, side, quantity, price, fees, note, approx AS approximate "
                 "FROM trades WHERE user_id = ? ORDER BY trade_date, id")
    return {
        "account": {"email": user["email"], "joined_utc": user["created_at"]},
        "trades": rows(trade_sql, user_id),
        "monthly_plans": rows("SELECT ticker, amount, day, start_month, end_month, fee_rate, fee_min FROM plans "
                              "WHERE user_id = ? ORDER BY id", user_id),
        "practice": {"trades": rows(trade_sql, twin["id"]) if twin else [],
                     "own_fee": ({"rate": twin["fee_rate"], "minimum": twin["fee_min"]}
                                 if twin and twin["fee_rate"] is not None else None)},
        "lessons_read": rows("SELECT lesson, read_at AS read_at_utc FROM lesson_reads WHERE user_id = ? ORDER BY read_at",
                             user_id),
        "security_log": rows("SELECT event, ip AS network_address, at AS at_utc FROM security_log WHERE user_id = ? "
                             "ORDER BY at", user_id),
    }


def delete_user(conn, user_id):
    """Deletes an account and everything in it, at once and for good: its trades, notes, monthly plans, practice
    portfolio (the hidden twin and its trades), lessons read, sessions, reset links and security log entries
    (all ON DELETE CASCADE), plus the failed-login counts kept under its email. True if an account was deleted."""
    with conn:
        user = conn.execute("SELECT email FROM users WHERE id = ? AND practice_of IS NULL", (user_id,)).fetchone()
        if user is None:
            return False
        conn.execute("DELETE FROM login_attempts WHERE key = ?", ("email:" + user["email"],))
        conn.execute("DELETE FROM users WHERE practice_of = ?", (user_id,))      # the practice twin, explicitly
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return True


# ---------- Prices ----------

def save_prices(conn, ticker, rows):
    """Saves (price_date, close) pairs for one ticker. Days already saved are skipped.

    Returns how many new days were added.
    """
    with conn:
        cur = conn.executemany(
            """
            INSERT INTO prices (ticker, price_date, close)
            VALUES (?, ?, ?)
            ON CONFLICT (ticker, price_date) DO NOTHING
            """,
            [(ticker, price_date, close) for price_date, close in rows],
        )
    return max(cur.rowcount, 0)


def correct_prices(conn, ticker, rows, max_change):
    """Re-downloaded (price_date, close) pairs for days already saved (w413). A close that differs from the saved
    one is corrected, unless it's more than max_change apart (0.25 = 25%): that's returned instead, for a person to
    check. Days not saved yet are left to save_prices. Returns (corrected, [(day, saved, new), ...])."""
    if not rows:
        return 0, []
    saved = {r["price_date"]: r["close"] for r in conn.execute(
        "SELECT price_date, close FROM prices WHERE ticker = ? AND price_date BETWEEN ? AND ?",
        (ticker, min(d for d, _ in rows), max(d for d, _ in rows))).fetchall()}
    fix, held = [], []
    for day, close in rows:
        old = saved.get(day)
        if old is None or close <= 0 or abs(close - old) < 0.00005:   # not saved, nonsense, or the same
            continue
        (held if abs(close - old) / old > max_change else fix).append((day, old, close))
    if fix:
        with conn:
            conn.executemany("UPDATE prices SET close = ? WHERE ticker = ? AND price_date = ?",
                             [(new, ticker, day) for day, _, new in fix])
    return len(fix), held


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
    with conn:
        cur = conn.executemany(
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
    return max(cur.rowcount, 0)


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
    with conn:
        cur = conn.executemany(
            """
            INSERT INTO corporate_actions (ticker, ex_date, factor, source)
            VALUES (?, ?, ?, 'yfinance')
            ON CONFLICT (ticker, ex_date) DO UPDATE SET factor = excluded.factor
            WHERE corporate_actions.source <> 'manual'
              AND corporate_actions.factor <> excluded.factor
            """,
            [(ticker, ex_date, factor) for ex_date, factor in rows],
        )
    return max(cur.rowcount, 0)


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
    print("Database ready:", "PostgreSQL (DATABASE_URL)" if is_postgres(conn)
          else Path(conn.execute("PRAGMA database_list").fetchone()["file"]).name)
    print("Tables:", ", ".join(tables(conn)))
    conn.close()
