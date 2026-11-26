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


def next_update(now=None):
    """When the next closing prices should arrive, in words: "about 5:45pm today", "about 5:45pm tomorrow"
    or "about 5:45pm on Monday". The next weekday's close; a public holiday can make it a day later."""
    now = now or singapore_now()
    day = now.date()
    if day.weekday() >= 5 or now.time() >= READY_AT:
        day += timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
    when = "today" if day == now.date() else "tomorrow" if day == now.date() + timedelta(days=1) else f"on {day:%A}"
    return f"about 5:45pm {when}"


def prices_version(conn):
    """A short label that changes whenever ANY closing price is saved or corrected, like
    "2026-11-12/6043/91234.5600": the newest date, how many prices there are, and their total. (The date
    alone isn't enough: one stock can already have today's close while the others catch up, and Yahoo
    sometimes corrects a past close.) Pages compare it with what they showed."""
    row = conn.execute("SELECT MAX(price_date) AS d, COUNT(*) AS n, COALESCE(SUM(close), 0) AS t FROM prices").fetchone()
    return f"{row['d']}/{row['n']}/{row['t']:.4f}" if row["d"] else ""


def seconds_to_next_close(conn, now=None):
    """How long open pages should wait before asking for new prices again (static/js/live.js). New closes come
    once a trading day, so asking every couple of minutes all day was wasted work (audit 4, from "make sure your
    app isn't polling"). 0 while a close is due but not saved yet (then pages keep checking every 2 minutes);
    otherwise the time until about 5:45pm on the next weekday."""
    now = now or singapore_now()
    latest = _benchmark_latest(conn)
    if latest is None or latest < last_trading_day(now).isoformat():
        return 0
    day = now.date()
    if day.weekday() >= 5 or now.time() >= READY_AT:
        day += timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
    target = datetime.combine(day, READY_AT, tzinfo=now.tzinfo)
    return max(0, int((target - now).total_seconds()))


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
        conn.execute("INSERT INTO jobs (name) VALUES ('prices') ON CONFLICT DO NOTHING")
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
    holds (real or practice) plus the STI ETF, plus the companies named in the last week's headlines (so
    Market today can show how they moved). Only Yahoo Finance is called. True if nothing failed."""
    import market
    from instruments import seed_instruments
    seed_instruments(conn)
    import news
    # Companies in the last week's headlines too, so Market today can show how they moved.
    # And every watched stock (s14), so the watchlist shows the latest close too, and every stock tried in the
    # "what if" calculator (s12), so its answer runs up to the latest close.
    tickers = sorted(set(db.get_traded_tickers(conn)) | {market.BENCHMARK} | set(news.recent_tickers(conn))
                     | set(db.watched_tickers(conn)) | set(db.history_tickers(conn)))
    actions = market.update_actions(conn, tickers)          # splits first: prices are un-adjusted with them
    prices = market.update_prices(conn, tickers)
    results = actions + prices + market.update_dividends(conn, tickers)
    # Announced ex-dates (s04) only for stocks someone holds: that's who the calendar is for. A failed check
    # isn't counted as a failed update (the forecast just keeps estimating that stock's dates).
    market.update_announced(conn, sorted(set(db.get_traded_tickers(conn))))
    for r in prices:                         # to the server log (Render's Logs tab), for a person to check
        for day, old, new in r.held_back or []:
            print(f"SGXray prices: held back {r.ticker} {day}: saved {old:g}, Yahoo now says {new:g}",
                  file=sys.stderr, flush=True)
    import plans
    plans.catch_up_all(conn)                 # monthly plans: record any month whose buy day now has a close
    return not any(r.error for r in results)


NEWS_EVERY = timedelta(hours=3)


def news_once(conn, now=None, update=None):
    """Fetches headlines if the last try was 3 hours ago or more. Returns "not due", "updated" or "failed"."""
    import news
    now = now or singapore_now()
    conn.execute(JOB_SQL)
    with conn:
        conn.execute("INSERT INTO jobs (name) VALUES ('news') ON CONFLICT DO NOTHING")
    job = conn.execute("SELECT last_try FROM jobs WHERE name = 'news'").fetchone()
    if job["last_try"] and datetime.fromisoformat(job["last_try"]) > now - NEWS_EVERY:
        return "not due"
    stamp = now.isoformat(timespec="seconds")
    with conn:                                      # mark the try first, so two processes don't both fetch
        conn.execute("UPDATE jobs SET last_try = ? WHERE name = 'news'", (stamp,))
    try:
        ok = (update or news.update)(conn)
    except Exception:
        ok = False
    if ok:
        with conn:
            conn.execute("UPDATE jobs SET last_ok = ? WHERE name = 'news'", (stamp,))
    return "updated" if ok else "failed"


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
                if news_once(conn) == "failed":
                    print(f"[news] {singapore_now():%d %b %H:%M} SGT: no feed answered", flush=True)
                conn.close()
            except Exception as e:     # a locked or missing database: try again next time
                print(f"[prices] check skipped: {type(e).__name__}", flush=True)
            time.sleep(CHECK_EVERY)
    threading.Thread(target=loop, name="sgxray-prices", daemon=True).start()
