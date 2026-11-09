"""Corporate actions: splits, bonus issues and consolidations.

The problem: Yahoo rewrites old prices after a split or bonus issue. After DBS's 1-for-10
bonus issue (ex-date 2024-04-22), Yahoo shows the 15 Mar 2024 close as $31.52, but it really
traded at $34.67. Your broker statement says you paid the real price.

SGXray's rule: EVERYTHING IS STORED AS IT REALLY WAS.
- Users enter real trades, exactly as on their broker statement.
- market.py turns Yahoo's prices and dividends back into real ones as it saves them
  (real = Yahoo's number x the factor of every Yahoo-known action after that day).
- Holdings follow the actions: owning 100 DBS before the bonus means owning 110 after.

Rights issues are different: you pay for the new shares. Record the shares you subscribed for
as a normal BUY at the rights price.

    python src/adjust.py list D05.SI
    python src/adjust.py add D05.SI 2024-04-22 1.1     (only for actions Yahoo doesn't know)
"""

import argparse
import math
import sys
from datetime import date

import db
from instruments import seed_instruments


def shares_after(shares, factor):
    """Shares held after an action. SGX drops fractions of a share (they're usually sold for cash)."""
    return math.floor(shares * factor + 1e-9)       # the tiny extra stops 109.99999 becoming 109


def price_factor(actions, day):
    """What to multiply Yahoo's number for `day` by to get the real one: every action after that day."""
    factor = 1.0
    for a in actions:
        if a["ex_date"] > day:
            factor *= a["factor"]
    return factor


def yahoo_actions(conn, ticker):
    """The actions Yahoo has already adjusted its prices for. Manual ones aren't in Yahoo's
    numbers (that's why they had to be typed in), so they must not be used to un-adjust them."""
    return db.get_actions(conn, ticker, source="yfinance")


def add_manual_action(conn, ticker, ex_date, factor, today=None):
    """Checks and saves one action typed in by hand. Returns a list of problems; empty means saved."""
    today = today or date.today()
    errors = []
    ticker = ticker.strip().upper()
    if ticker not in {i["ticker"] for i in db.get_instruments(conn)}:
        errors.append(f"unknown ticker '{ticker}'")
    try:
        day = date.fromisoformat(ex_date.strip())
        if len(ex_date.strip()) != 10:
            raise ValueError
        if day > today:
            errors.append(f"ex-date {day} is in the future")
    except ValueError:
        errors.append(f"ex-date '{ex_date}' must be a real date like 2024-04-22 (YYYY-MM-DD)")
        day = None
    try:
        value = float(factor)
    except ValueError:
        value = None
    if value is None or not math.isfinite(value) or value <= 0 or value == 1:
        errors.append(f"factor '{factor}' must be a number above 0 and not 1 (e.g. 1.1 for 1-for-10 bonus)")
    if not errors and any(a["ex_date"] == day.isoformat() for a in db.get_actions(conn, ticker)):
        errors.append(f"{ticker} already has an action on {day}")
    if not errors:
        db.add_manual_action(conn, ticker, day.isoformat(), value)
    return errors


def main(argv):
    from fmt import safe_console
    safe_console()                     # never crash printing characters the terminal can't show
    parser = argparse.ArgumentParser(description="See or add splits and bonus issues.")
    commands = parser.add_subparsers(dest="command", required=True)
    show = commands.add_parser("list")
    show.add_argument("ticker")
    add = commands.add_parser("add")
    add.add_argument("ticker")
    add.add_argument("ex_date")
    add.add_argument("factor", help="shares after per share before: 1.1 = 1-for-10 bonus, 2 = 2-for-1 split")

    args = parser.parse_args(argv)
    conn = db.get_connection()
    db.init_db(conn)
    seed_instruments(conn)
    if args.command == "add":
        errors = add_manual_action(conn, args.ticker, args.ex_date, args.factor)
        if errors:
            print("Not saved:")
            for e in errors:
                print("  -", e)
            return 1
        print("Saved. Holdings now follow this action.")

    ticker = args.ticker.strip().upper()
    rows = db.get_actions(conn, ticker)
    print(f"Corporate actions for {ticker}: {len(rows)}")
    for r in rows:
        print(f"  {r['ex_date']}   x{r['factor']:g}   {r['source']}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
