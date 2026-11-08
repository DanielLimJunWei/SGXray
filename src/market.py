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
from instruments import seed_instruments

SGT = timezone(timedelta(hours=8))      # Singapore time. No daylight saving, so a fixed offset is exact.
MARKET_CLOSE = clock_time(17, 30)       # SGX closes at 5pm; the closing price is final shortly after.
BENCHMARK = "ES3.SI"                    # STI ETF, to compare portfolios against the market
DEFAULT_HISTORY_DAYS = 365              # how far back to start when nobody has traded yet
PAUSE_SECONDS = 0.5                     # wait between downloads, to be polite to Yahoo

# yfinance logs noisy messages for normal things like "no data on a holiday". We report problems ourselves.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


@dataclass
class PriceUpdate:
    ticker: str
    added: int = 0          # new days saved in this run
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
    in anything, so "you vs the STI" covers the whole portfolio."""
    if ticker == BENCHMARK:
        first = db.get_first_trade_date(conn)
    else:
        first = db.get_first_trade_date(conn, ticker)
    return date.fromisoformat(first) if first else end - timedelta(days=DEFAULT_HISTORY_DAYS)


def _next_weekday(day):
    while day.weekday() >= 5:           # 5 = Saturday, 6 = Sunday
        day += timedelta(days=1)
    return day


# ---------- Downloading ----------

def download_closes(ticker, start, end):
    """Downloads daily closes from Yahoo for start..end (both included).

    Returns a list of ('YYYY-MM-DD', close) pairs. auto_adjust=False gives the price actually
    traded that day (only splits and bonus issues are still adjusted; see NOTES.md).
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

    download is the function that fetches prices. Tests pass a fake one, so they never use the internet.
    """
    end = last_complete_day(now)
    results = []
    downloaded_before = False

    for ticker in tickers:
        update = PriceUpdate(ticker)
        latest = db.get_latest_price_date(conn, ticker)

        if latest:
            start = date.fromisoformat(latest) + timedelta(days=1)          # only the new days
        else:
            start = _history_start(conn, ticker, end)                       # first time

        if _next_weekday(start) <= end:                                     # else already up to date
            if downloaded_before and pause:
                time.sleep(pause)
            downloaded_before = True
            try:
                rows = download(ticker, start, end)
                # Keep only days in the range we asked for. Yahoo sometimes adds today's live price.
                rows = [(d, c) for d, c in rows if start.isoformat() <= d <= end.isoformat()]
                update.added = db.save_prices(conn, ticker, rows)
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

    Like prices, old amounts are adjusted for splits and bonus issues (see NOTES.md).
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
        start = _history_start(conn, ticker, now.date()).isoformat()
        if i and pause:
            time.sleep(pause)
        try:
            rows = [(d, a) for d, a in download(ticker) if start <= d <= today]
            update.saved = db.save_dividends(conn, ticker, rows)
        except Exception as e:
            update.error = f"download failed ({type(e).__name__}: {e})"
        update.total = len(db.get_dividends(conn, ticker))
        results.append(update)
    return results


# ---------- Run directly ----------

def main():
    conn = db.get_connection()
    db.init_db(conn)
    seed_instruments(conn)

    tickers = sorted(set(db.get_traded_tickers(conn)) | {BENCHMARK})
    print(f"Updating prices up to {last_complete_day()} for {', '.join(tickers)}")

    results = update_prices(conn, tickers)
    for r in results:
        if r.error:
            print(f"  {r.ticker:<8} ERROR: {r.error}")
        elif r.latest is None:
            print(f"  {r.ticker:<8} no prices yet")
        else:
            close = db.get_prices(conn, r.ticker, start=r.latest)[0]["close"]
            print(f"  {r.ticker:<8} {r.added:>4} new days   latest {r.latest}   close {close:.2f}")

    print("Updating dividends")
    div_results = update_dividends(conn, tickers)
    for r in div_results:
        if r.error:
            print(f"  {r.ticker:<8} ERROR: {r.error}")
        else:
            print(f"  {r.ticker:<8} {r.saved:>4} new or corrected   {r.total} saved in total")

    conn.close()
    return 1 if any(r.error for r in results + div_results) else 0


if __name__ == "__main__":
    sys.exit(main())
