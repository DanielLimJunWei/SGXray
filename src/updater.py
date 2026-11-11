"""Automatic daily price updates (w410): new SGX closing prices arrive by themselves.

Inside the app, a background thread checks every 15 minutes. On a trading day after about 5:45pm Singapore
time (SGX closes at 5pm and the close is final shortly after), or whenever the saved prices are behind,
it downloads the latest closes, splits and dividends for every stock anyone holds, plus the STI ETF:
the same steps as `python src/market.py`. If Yahoo doesn't have the new close yet it tries again 15 minutes
later, and gives up on that day after 12 tries (a public holiday has no close).

Only one copy ever runs at a time, even with several server processes: a row in the `jobs` table works as
a lock, so a second process that finds it taken just waits for the next check.

Open pages notice the new prices by themselves (static/js/live.js asks `/prices/latest`) and roll their
numbers to the new close, so nobody has to refresh.
"""

import os
import sys
import threading
import time
from datetime import datetime, time as clock_time, timedelta

import db

CHECK_EVERY = 15 * 60          # seconds between checks
FIRST_CHECK = 20               # seconds after the app starts: catches up on missed days soon after start-up
READY_AT = clock_time(17, 45)  # Singapore time: the close is usually on Yahoo by now
MAX_TRIES = 12                 # per trading day: 3 hours of tries, then wait for the next day
LOCK_MINUTES = 20              # a crashed run can't hold the lock longer than this

JOB_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    name          TEXT PRIMARY KEY,
    target        TEXT,          -- the trading day it's trying to get the close for
    tries         INTEGER NOT NULL DEFAULT 0,
    last_try      TEXT,
    last_ok       TEXT,
    running_until TEXT           -- the lock: set while a run is going
)
"""


def singapore_now():
    from market import SGT
    return datetime.now(SGT)


def last_trading_day(now=None):
    """The newest weekday whose close should exist by now: today after 5:45pm, else the day before,
    skipping weekends. (Public holidays aren't known: on those, the retries simply find nothing.)"""
    now = now or singapore_now()
    day = now.date() if now.time() >= READY_AT else now.date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def newest_saved(conn):
    """The newest closing price saved for any stock, as 'YYYY-MM-DD', or None."""
    row = conn.execute("SELECT MAX(price_date) AS d FROM prices").fetchone()
    return row["d"]


def prices_version(conn):
    """A short label that changes whenever ANY closing price is saved or corrected, like
    "2026-11-12/6043/91234.5600": the newest date, how many prices there are, and their total. (The date
    alone isn't enough: one stock can already have today's close while the others catch up, and Yahoo
    sometimes corrects a past close.) Pages compare it with what they showed."""
    row = conn.execute("SELECT MAX(price_date) AS d, COUNT(*) AS n, TOTAL(close) AS t FROM prices").fetchone()
    return f"{row['d']}/{row['n']}/{row['t']:.4f}" if row["d"] else ""


def _benchmark_latest(conn):
    from market import BENCHMARK
    return db.get_latest_price_date(conn, BENCHMARK)


def due(conn, now=None):
    """Should a run happen now? Yes when the STI ETF's newest close is older than the last trading day,
    and today's tries for that day aren't used up."""
    now = now or singapore_now()
    target = last_trading_day(now).isoformat()
    latest = _benchmark_latest(conn)
    if latest is not None and latest >= target:
        return False
    conn.execute(JOB_SQL)
    job = conn.execute("SELECT target, tries FROM jobs WHERE name = 'prices'").fetchone()
    return not (job and job["target"] == target and job["tries"] >= MAX_TRIES)


def _take_lock(conn, now):
    """True if this process got the lock. Atomic: two processes can't both succeed."""
    conn.execute(JOB_SQL)
    stamp, until = now.isoformat(timespec="seconds"), (now + timedelta(minutes=LOCK_MINUTES)).isoformat(timespec="seconds")
    with conn:
        conn.execute("INSERT OR IGNORE INTO jobs (name) VALUES ('prices')")
        cur = conn.execute("UPDATE jobs SET running_until = ? WHERE name = 'prices' "
                           "AND (running_until IS NULL OR running_until < ?)", (until, stamp))
    return cur.rowcount == 1


def run_once(conn, now=None, update=None):
    """One check: if due and the lock is free, download the new closes. Returns what happened, one of
    "not due", "busy", "updated", "no new close" or "failed" (for tests and the log)."""
    now = now or singapore_now()
    if not due(conn, now):
        return "not due"
    if not _take_lock(conn, now):
        return "busy"
    target = last_trading_day(now).isoformat()
    before = _benchmark_latest(conn)
    try:
        ok = (update or download_all)(conn)
        after = _benchmark_latest(conn)
        result = "updated" if after and after != before else ("no new close" if ok else "failed")
    except Exception:                      # never let one bad download stop future checks
        result = "failed"
    stamp = now.isoformat(timespec="seconds")
    with conn:
        job = conn.execute("SELECT target, tries FROM jobs WHERE name = 'prices'").fetchone()
        tries = (job["tries"] + 1) if job and job["target"] == target else 1
        conn.execute("UPDATE jobs SET target = ?, tries = ?, last_try = ?, running_until = NULL"
                     + (", last_ok = ?" if result == "updated" else "") + " WHERE name = 'prices'",
                     (target, tries, stamp, stamp) if result == "updated" else (target, tries, stamp))
    return result


def download_all(conn):
    """The same steps as `python src/market.py`: splits, then prices, then dividends, for every stock anyone
    holds (real or practice) plus the STI ETF. Only Yahoo Finance is called. True if nothing failed."""
    import market
    from instruments import seed_instruments
    seed_instruments(conn)
    tickers = sorted(set(db.get_traded_tickers(conn)) | {market.BENCHMARK})
    results = (market.update_actions(conn, tickers) + market.update_prices(conn, tickers)
               + market.update_dividends(conn, tickers))
    return not any(r.error for r in results)


def enabled():
    """On by default when the app runs; off in the tests (they must never reach the internet), or with
    SGXRAY_AUTO_PRICES=0."""
    default = "0" if "pytest" in sys.modules else "1"
    return os.environ.get("SGXRAY_AUTO_PRICES", default) == "1"


def start(db_path):
    """Starts the background checker once per process. Its own database connection: SQLite connections
    can't be shared between threads."""
    def loop():
        time.sleep(FIRST_CHECK)
        while True:
            try:
                conn = db.get_connection(db_path)
                result = run_once(conn)
                if result not in ("not due", "busy"):
                    print(f"[prices] {singapore_now():%d %b %H:%M} SGT: {result}", flush=True)
                conn.close()
            except Exception as e:     # a locked or missing database: try again next time
                print(f"[prices] check skipped: {type(e).__name__}", flush=True)
            time.sleep(CHECK_EVERY)
    threading.Thread(target=loop, name="sgxray-prices", daemon=True).start()
