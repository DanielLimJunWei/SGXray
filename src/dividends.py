"""Manual dividend entry, for when Yahoo's dividend data is missing or wrong.

Check the amount against the company's own announcement (on the SGX website or the
company's investor relations page) before entering it. A manual entry always wins:
later yfinance downloads never overwrite it.

    python src/dividends.py list D05.SI
    python src/dividends.py add D05.SI 2024-04-10 0.54
"""

import argparse
import math
import sys
from datetime import date

import db
from instruments import seed_instruments


def add_manual_dividend(conn, ticker, ex_date, amount, today=None):
    """Checks and saves one dividend typed in by hand. Returns a list of problems; empty means saved."""
    today = today or date.today()
    errors = []

    ticker = ticker.strip().upper()
    if ticker not in {i["ticker"] for i in db.get_instruments(conn)}:
        errors.append(f"unknown ticker '{ticker}'")

    try:
        day = date.fromisoformat(ex_date.strip())
        if len(ex_date.strip()) != 10:
            raise ValueError
    except ValueError:
        errors.append(f"ex-date '{ex_date}' must be a real date like 2024-04-10 (YYYY-MM-DD)")
    else:
        if day > today:
            errors.append(f"ex-date {day} is in the future")

    try:
        value = float(amount)
    except ValueError:
        value = None
    if value is None or not math.isfinite(value) or value <= 0:
        errors.append(f"amount '{amount}' must be a number above 0 (dollars per share)")

    if not errors:
        db.set_manual_dividend(conn, ticker, day.isoformat(), value)
    return errors


def main(argv):
    parser = argparse.ArgumentParser(description="See or add dividends by hand.")
    commands = parser.add_subparsers(dest="command", required=True)

    show = commands.add_parser("list", help="show saved dividends for a ticker")
    show.add_argument("ticker")

    add = commands.add_parser("add", help="add or correct a dividend")
    add.add_argument("ticker")
    add.add_argument("ex_date", help="ex-dividend date, YYYY-MM-DD")
    add.add_argument("amount", help="dollars per share, e.g. 0.54")

    args = parser.parse_args(argv)
    conn = db.get_connection()
    db.init_db(conn)
    seed_instruments(conn)

    if args.command == "add":
        errors = add_manual_dividend(conn, args.ticker, args.ex_date, args.amount)
        if errors:
            print("Not saved:")
            for e in errors:
                print("  -", e)
            conn.close()
            return 1
        print(f"Saved: {args.ticker.upper()} ex-date {args.ex_date}, ${float(args.amount)} per share (manual)")

    ticker = args.ticker.strip().upper()
    rows = db.get_dividends(conn, ticker)
    print(f"Dividends saved for {ticker}: {len(rows)}")
    for r in rows:
        print(f"  {r['ex_date']}   ${r['amount']:<9g} {r['source']}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
