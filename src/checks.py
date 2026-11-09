"""Sanity checks: compare what the user typed with real market data.

The importer already rejects impossible values (a weekend, a future date, a word as a price).
These checks catch values that look fine but are probably wrong: a trade on a public holiday,
a price far from that day's close, a dividend at an unusual time of year.

They give WARNINGS, not errors. Prices move during the day and Yahoo's data isn't perfect,
so the user decides. They need saved prices, so they work after market.py has run.

    python src/checks.py
"""

import sys
from datetime import date

import db

PRICE_GAP_LIMIT = 0.10          # warn if a trade price is more than 10% from that day's close
DIVIDEND_DAYS_LIMIT = 45        # how far from the usual time of year a dividend can be
SPIKE_LIMIT = 0.30              # warn if a saved price moves more than 30% in one day


def _days_apart(a, b):
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def check_trades(conn, user_id, gap_limit=PRICE_GAP_LIMIT):
    """Warnings about one user's trades that don't match the market data we have."""
    days = db.get_trading_days(conn)
    if not days:
        return []                                   # no prices yet: nothing to compare with
    trading_days, first, last = set(days), days[0], days[-1]

    warnings = []
    for t in db.get_trades(conn, user_id):
        ticker, side, day, price = t["ticker"], t["side"], t["trade_date"], t["price"]
        if not first <= day <= last:
            continue                                # outside the dates we have prices for

        if day not in trading_days:
            warnings.append(
                f"{ticker} {side} on {day}: SGX didn't trade that day (a public holiday?). Check the date."
            )
            continue

        close = db.get_close(conn, ticker, day)
        if close is None:
            continue                                # no price for this ticker that day (e.g. suspended)
        gap = abs(price - close) / close
        if gap > gap_limit:
            warnings.append(
                f"{ticker} {side} on {day} at ${price:.2f}: it closed at ${close:.2f} that day "
                f"({gap:.0%} apart). Check the date and price. (A split or bonus issue since then "
                f"also makes Yahoo's older prices lower.)"
            )
    return warnings


def check_manual_dividends(conn, days_limit=DIVIDEND_DAYS_LIMIT):
    """Warnings about hand-entered dividends that look out of place.

    Companies pay at roughly the same times each year, so a manual dividend with no Yahoo
    dividend near the same date (this year, a year before or a year after) is suspicious.
    """
    days = db.get_trading_days(conn)
    trading_days = set(days)
    warnings = []

    for d in db.get_manual_dividends(conn):
        ticker, ex_date = d["ticker"], d["ex_date"]

        if days and days[0] <= ex_date <= days[-1] and ex_date not in trading_days:
            warnings.append(
                f"{ticker} dividend on {ex_date}: SGX didn't trade that day, but ex-dates are "
                f"always trading days. Check the date."
            )
            continue

        yahoo_dates = [
            r["ex_date"] for r in db.get_dividends(conn, ticker)
            if r["source"] == "yfinance" and not r["ignored"] and r["ex_date"] != ex_date
        ]
        if len(yahoo_dates) < 2:
            continue                                # not enough history to know the pattern

        year = int(ex_date[:4])
        same_time_each_year = [ex_date.replace(str(year), str(y), 1) for y in (year - 1, year, year + 1)]
        near = any(
            _days_apart(when, y) <= days_limit
            for when in same_time_each_year
            for y in yahoo_dates
            if _valid(when)
        )
        if not near:
            warnings.append(
                f"{ticker} dividend on {ex_date}: {ticker} doesn't usually pay around this time "
                f"of year. Check the ex-date."
            )
    return warnings


def check_price_spikes(conn, tickers, jump_limit=SPIKE_LIMIT):
    """Warnings about saved prices that jump too far in one day.

    Free price feeds sometimes have a bad tick (a price off by 10x, or a missing decimal).
    A real move this big in one day is rare for SGX blue chips, so it's worth a look.
    A split or bonus issue on that day explains a jump, so those days are skipped.
    """
    warnings = []
    for ticker in tickers:
        action_days = {a["ex_date"] for a in db.get_actions(conn, ticker)}
        prices = db.get_prices(conn, ticker)
        for before, after in zip(prices, prices[1:]):
            change = after["close"] / before["close"] - 1
            if abs(change) > jump_limit and after["price_date"] not in action_days:
                warnings.append(
                    f"{ticker} price on {after['price_date']}: {before['close']:g} -> {after['close']:g} "
                    f"({change:+.0%} in a day). Possibly a bad price from Yahoo; check it."
                )
    return warnings


def _valid(day):
    """False for dates that don't exist, like 29 Feb moved to a non-leap year."""
    try:
        date.fromisoformat(day)
        return True
    except ValueError:
        return False


def print_warnings(warnings):
    if not warnings:
        print("Checks: everything matches the market data.")
        return
    print(f"Checks: {len(warnings)} thing(s) to look at:")
    for w in warnings:
        print("  !", w)


# ---------- Run directly ----------

def main():
    from fmt import safe_console
    safe_console()                     # never crash printing characters the terminal can't show
    from importer import DEMO_EMAIL

    conn = db.get_connection()
    db.init_db(conn)
    user = db.get_user_by_email(conn, DEMO_EMAIL)
    warnings = (check_trades(conn, user["id"]) if user else []) + check_manual_dividends(conn)
    warnings += check_price_spikes(conn, db.get_traded_tickers(conn))
    print_warnings(warnings)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
