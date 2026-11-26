"""Market data for SGXray: downloads daily closing prices and dividends and saves them in the database.

Data comes from yfinance (unofficial Yahoo Finance data). Every price is saved, so each
day is downloaded only once: later runs fetch just the days after the newest saved one.

Run it directly to update prices and dividends for every ticker anyone has traded, plus the STI ETF:
    python src/market.py
"""

import logging
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, time as clock_time, timedelta, timezone

import yfinance as yf

import db
from adjust import price_factor, yahoo_actions
from instruments import seed_instruments

SGT = timezone(timedelta(hours=8))      # Singapore time. No daylight saving, so a fixed offset is exact.
MARKET_CLOSE = clock_time(17, 30)       # SGX closes at 5pm; the closing price is final shortly after.
BENCHMARK = "ES3.SI"                    # STI ETF, to compare portfolios against the market
DEFAULT_HISTORY_DAYS = 365              # how far back to start when nobody has traded yet
PAUSE_SECONDS = 0.5                     # wait between downloads, to be polite to Yahoo
DIVIDEND_LOOKBACK_DAYS = 400            # dividends are saved from this long before the first trade
RECHECK_DAYS = 7                        # each update also re-reads the last week's saved closes (w413)
MAX_CORRECTION = 0.25                   # a "correction" bigger than 25% is held back as a likely glitch

# yfinance logs noisy messages for normal things like "no data on a holiday". We report problems ourselves.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


@dataclass
class PriceUpdate:
    ticker: str
    added: int = 0          # new days saved in this run
    corrected: int = 0      # saved days whose close Yahoo has since corrected, now fixed
    held_back: list = None  # [(day, saved close, Yahoo's new close)] changes too big to trust without a look
    latest: str = None      # newest saved day afterwards
    error: str = None


# ---------- Dates ----------

def last_complete_day(now=None):
    """The latest day whose closing price is final: today after 5:30pm Singapore time, else yesterday.

    Before the close, Yahoo's "price today" is still moving, and saving it would store a wrong close forever.
    """
    now = now or datetime.now(SGT)
    today = now.date()
    return today if now.time() >= MARKET_CLOSE else today - timedelta(days=1)


def _history_start(conn, ticker, end):
    """Where a ticker's history starts: its first trade, or for the benchmark, the first trade
    in anything, so "you vs the STI" covers the whole portfolio. A stock tried in the "what if" calculator (s12)
    reaches back as far as was asked for (db.history_wanted)."""
    if ticker == BENCHMARK:
        first = db.get_first_trade_date(conn)
    else:
        first = db.get_first_trade_date(conn, ticker)
    start = date.fromisoformat(first) if first else end - timedelta(days=DEFAULT_HISTORY_DAYS)
    wanted = db.history_since(conn, ticker)              # the "what if" calculator's longer history (s12)
    if wanted:
        start = min(start, date.fromisoformat(wanted))
    return start


def _next_weekday(day):
    while day.weekday() >= 5:           # 5 = Saturday, 6 = Sunday
        day += timedelta(days=1)
    return day


# ---------- Downloading ----------

def download_closes(ticker, start, end):
    """Downloads daily closes from Yahoo for start..end (both included).

    Returns a list of ('YYYY-MM-DD', close) pairs. auto_adjust=False leaves out the dividend
    adjustment, but Yahoo still adjusts for splits and bonus issues; update_prices undoes that.
    """
    df = yf.Ticker(ticker).history(
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),     # Yahoo's end date is not included, so add a day
        auto_adjust=False,
        actions=False,
    )
    if df.empty or "Close" not in df.columns:
        return []
    closes = df["Close"].dropna()
    return [(day.strftime("%Y-%m-%d"), round(float(close), 4)) for day, close in closes.items()]


def update_prices(conn, tickers, now=None, download=download_closes, pause=PAUSE_SECONDS):
    """Brings saved prices up to date for each ticker. One failing ticker doesn't stop the others.

    Whenever there's a new day to fetch, the last week's saved closes are downloaded again too (w413): Yahoo
    sometimes corrects a close a day or two later, and before this the first figure was kept forever. A saved
    close that has changed is corrected; one that has changed by more than 25% is held back and reported
    instead, since that's more likely a glitch (or an unrecorded split) than a correction.

    download is the function that fetches prices. Tests pass a fake one, so they never use the internet.
    """
    end = last_complete_day(now)
    results = []
    downloaded_before = False

    for ticker in tickers:
        update = PriceUpdate(ticker)
        latest = db.get_latest_price_date(conn, ticker)
        needed_from = _history_start(conn, ticker, end)

        # The date ranges still missing. Normally just the new days at the end. But if older trades
        # were added later (back-dating), the history now starts earlier than the saved prices, so
        # that gap at the start is downloaded too. (Before audit 3 it was never filled, and the app crashed.)
        if latest:
            earliest = date.fromisoformat(db.get_earliest_price_date(conn, ticker))
            newest = date.fromisoformat(latest)
            fresh_from = newest + timedelta(days=1)
            if _next_weekday(fresh_from) <= end:            # new days to fetch: re-read the last week as well
                fresh_from = max(earliest, newest - timedelta(days=RECHECK_DAYS))
            ranges = [(needed_from, earliest - timedelta(days=1)), (fresh_from, end)]
        else:
            ranges = [(needed_from, end)]

        for start, stop in ranges:
            if _next_weekday(start) > stop:                                 # nothing missing here
                continue
            if downloaded_before and pause:
                time.sleep(pause)
            downloaded_before = True
            try:
                rows = download(ticker, start, stop)
                # Keep only days in the range we asked for. Yahoo sometimes adds today's live price.
                rows = [(d, c) for d, c in rows if start.isoformat() <= d <= stop.isoformat()]
                # Undo Yahoo's split/bonus adjustment, so we store the price really traded.
                actions = yahoo_actions(conn, ticker)
                rows = [(d, round(c * price_factor(actions, d), 4)) for d, c in rows]
                if latest:                                  # days already saved: compare, correct if changed
                    fixed, held = db.correct_prices(conn, ticker, [(d, c) for d, c in rows if d <= latest],
                                                    MAX_CORRECTION)
                    update.corrected += fixed
                    if held:
                        update.held_back = (update.held_back or []) + held
                update.added += db.save_prices(conn, ticker, rows)
                if not rows and latest is None:
                    update.error = "no price data found. Is the ticker right?"
            except Exception as e:                                          # network down, rate limit, ...
                update.error = f"download failed ({type(e).__name__}: {e})"

        update.latest = db.get_latest_price_date(conn, ticker)
        results.append(update)
    return results


# ---------- Dividends ----------

@dataclass
class DividendUpdate:
    ticker: str
    saved: int = 0          # dividends added or corrected in this run
    total: int = 0          # dividends saved for this ticker afterwards
    error: str = None


def download_dividends(ticker):
    """Every dividend Yahoo has for a ticker, as ('YYYY-MM-DD' ex-date, amount per share) pairs.

    Like prices, old amounts are adjusted for splits and bonus issues; update_dividends undoes that.
    """
    series = yf.Ticker(ticker).dividends
    return [(day.strftime("%Y-%m-%d"), round(float(amount), 6)) for day, amount in series.items() if amount > 0]


def update_dividends(conn, tickers, now=None, download=download_dividends, pause=PAUSE_SECONDS):
    """Saves each ticker's dividends from its history start up to today.

    The whole list is fetched every time (it's one small request), so if Yahoo corrects an
    amount, the correction is saved too. Dividends entered by hand are never overwritten.
    """
    now = now or datetime.now(SGT)
    today = now.date().isoformat()
    results = []

    for i, ticker in enumerate(tickers):
        update = DividendUpdate(ticker)
        # A year before the history starts, so even a stock bought last week has a year of
        # payouts to forecast from. Dividends before you held a stock still aren't counted as yours.
        start = (_history_start(conn, ticker, now.date()) - timedelta(days=DIVIDEND_LOOKBACK_DAYS)).isoformat()
        if i and pause:
            time.sleep(pause)
        try:
            actions = yahoo_actions(conn, ticker)
            rows = [
                (d, round(a * price_factor(actions, d), 6))       # the amount really paid per share
                for d, a in download(ticker)
                if start <= d <= today
            ]
            update.saved = db.save_dividends(conn, ticker, rows)
        except Exception as e:
            update.error = f"download failed ({type(e).__name__}: {e})"
        update.total = len(db.get_dividends(conn, ticker))
        results.append(update)
    return results


# ---------- Announced ex-dates (s04) ----------

@dataclass
class AnnouncedUpdate:
    ticker: str
    dates: list = None      # announced ex-dates still to come, as saved
    error: str = None


def download_announced(ticker):
    """The ex-dividend date(s) Yahoo lists in a ticker's calendar, as 'YYYY-MM-DD' strings. Yahoo shows the
    next announced one, or the last one once it has passed (update_announced keeps only future dates). SGX
    stocks get no payment date or amount here, so SGXray never claims one."""
    cal = yf.Ticker(ticker).calendar or {}
    value = cal.get("Ex-Dividend Date")
    values = value if isinstance(value, (list, tuple)) else [value]
    out = []
    for v in values:
        if hasattr(v, "isoformat"):
            out.append(v.isoformat()[:10])
        elif isinstance(v, str) and len(v) >= 10:
            out.append(v[:10])
    return [d for d in out if _is_date(d)]


def _is_date(text):
    try:
        date.fromisoformat(text)
        return True
    except ValueError:
        return False


def update_announced(conn, tickers, now=None, download=download_announced, pause=PAUSE_SECONDS):
    """Saves each ticker's announced ex-dates still to come. A failed check keeps what was saved before."""
    today = (now or datetime.now(SGT)).date().isoformat()
    results = []
    for i, ticker in enumerate(tickers):
        update = AnnouncedUpdate(ticker)
        if i and pause:
            time.sleep(pause)
        try:
            db.save_announced(conn, ticker, download(ticker), today)
        except Exception as e:
            update.error = f"download failed ({type(e).__name__}: {e})"
        update.dates = db.get_announced(conn, ticker, today)
        results.append(update)
    return results


# ---------- Corporate actions ----------

@dataclass
class ActionUpdate:
    ticker: str
    saved: int = 0
    error: str = None


def download_actions(ticker):
    """Every split or bonus issue Yahoo knows for a ticker, as ('YYYY-MM-DD' ex-date, factor) pairs.
    Yahoo calls them all "splits": DBS's 1-for-10 bonus issue shows as a 1.1 split."""
    series = yf.Ticker(ticker).splits
    return [(day.strftime("%Y-%m-%d"), float(f)) for day, f in series.items() if f > 0 and f != 1]


def update_actions(conn, tickers, download=download_actions, pause=PAUSE_SECONDS):
    """Saves every ticker's splits and bonus issues. Runs BEFORE prices and dividends,
    because those are un-adjusted with these factors as they're saved."""
    results = []
    for i, ticker in enumerate(tickers):
        update = ActionUpdate(ticker)
        if i and pause:
            time.sleep(pause)
        try:
            update.saved = db.save_actions(conn, ticker, download(ticker))
        except Exception as e:
            update.error = f"download failed ({type(e).__name__}: {e})"
        results.append(update)
    return results


# ---------- Run directly ----------

def main():
    from fmt import safe_console
    safe_console()                     # never crash printing characters the terminal can't show
    conn = db.get_connection()
    db.init_db(conn)
    seed_instruments(conn)

    tickers = sorted(set(db.get_traded_tickers(conn)) | {BENCHMARK})

    print("Updating splits and bonus issues")
    act_results = update_actions(conn, tickers)
    for r in act_results:
        if r.error:
            print(f"  {r.ticker:<8} ERROR: {r.error}")
        else:
            total = len(db.get_actions(conn, r.ticker))
            print(f"  {r.ticker:<8} {r.saved:>4} new   {total} saved in total")

    print(f"Updating prices up to {last_complete_day()} for {', '.join(tickers)}")
    results = update_prices(conn, tickers)
    for r in results:
        if r.error:
            print(f"  {r.ticker:<8} ERROR: {r.error}")
        elif r.latest is None:
            print(f"  {r.ticker:<8} no prices yet")
        else:
            close = db.get_prices(conn, r.ticker, start=r.latest)[0]["close"]
            fixed = f"   {r.corrected} corrected" if r.corrected else ""
            print(f"  {r.ticker:<8} {r.added:>4} new days   latest {r.latest}   close {close:.3f}{fixed}")
            for day, old, new in r.held_back or []:
                print(f"           held back: {day} saved {old:g}, Yahoo now says {new:g} (more than "
                      f"{MAX_CORRECTION:.0%} apart: check it before changing it by hand)")

    print("Checking announced ex-dates")
    for r in update_announced(conn, sorted(set(db.get_traded_tickers(conn)))):
        if r.error:
            print(f"  {r.ticker:<8} ERROR: {r.error}")
        elif r.dates:
            print(f"  {r.ticker:<8} next ex-date {', '.join(r.dates)} (announced)")

    print("Updating dividends")
    div_results = update_dividends(conn, tickers)
    for r in div_results:
        if r.error:
            print(f"  {r.ticker:<8} ERROR: {r.error}")
        else:
            print(f"  {r.ticker:<8} {r.saved:>4} new or corrected   {r.total} saved in total")

    conn.close()
    return 1 if any(r.error for r in act_results + results + div_results) else 0


if __name__ == "__main__":
    sys.exit(main())
