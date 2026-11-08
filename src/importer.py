"""Imports trades from a CSV file into the database, checking every row first.

The whole file is checked before anything is saved. If any row is wrong, nothing is
imported and every problem is listed with its row number, so the user can fix the file
and try again. Half-imported portfolios are worse than none.

Run it directly to import a file for the demo user:
    python src/importer.py data/demo_trades.csv
"""

import math
import re
import sys
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

import db
from adjust import shares_after
from checks import check_trades, print_warnings
from instruments import seed_instruments

REQUIRED_COLUMNS = ["ticker", "date", "side", "quantity", "price"]
OPTIONAL_COLUMNS = ["fees"]
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class ImportResult:
    imported: int = 0
    skipped: int = 0                              # trades already in the database
    errors: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.errors


# ---------- Checking one row ----------

def _parse_number(text):
    """Turns text into a float, or None if it isn't a normal number ('abc', 'nan', 'inf')."""
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _check_row(row, row_no, known_tickers, today):
    """Checks one CSV row. Returns (trade, errors). trade is None if the row has errors."""
    errors = []

    ticker = row["ticker"].strip().upper()
    if not ticker:
        errors.append("ticker is empty")
    elif ticker not in known_tickers:
        errors.append(f"unknown ticker '{ticker}'")

    date_text = row["date"].strip()
    trade_date = None
    if not DATE_PATTERN.match(date_text):
        errors.append(f"date '{date_text}' must look like 2024-03-15 (YYYY-MM-DD)")
    else:
        try:
            trade_date = date.fromisoformat(date_text)
        except ValueError:
            errors.append(f"date '{date_text}' doesn't exist")
        else:
            if trade_date > today:
                errors.append(f"date {date_text} is in the future")
            elif trade_date.weekday() >= 5:
                errors.append(f"date {date_text} is a {trade_date.strftime('%A')}, when SGX is closed")

    side = row["side"].strip().upper()
    if side not in ("BUY", "SELL"):
        errors.append(f"side '{row['side'].strip()}' must be BUY or SELL")

    qty_text = row["quantity"].strip()
    quantity = int(qty_text) if qty_text.isdigit() else None
    if quantity is None or quantity == 0:
        errors.append(f"quantity '{qty_text}' must be a whole number above 0")

    price = _parse_number(row["price"].strip())
    if price is None or price <= 0:
        errors.append(f"price '{row['price'].strip()}' must be a number above 0")

    fees_text = row.get("fees", "").strip()
    fees = 0.0 if fees_text == "" else _parse_number(fees_text)
    if fees is None or fees < 0:
        errors.append(f"fees '{fees_text}' must be a number, 0 or more")

    if errors:
        return None, [f"Row {row_no}: {e}" for e in errors]
    trade = {
        "row": row_no,
        "ticker": ticker,
        "trade_date": trade_date.isoformat(),
        "side": side,
        "quantity": quantity,
        "price": price,
        "fees": fees,
    }
    return trade, []


# ---------- Checking the file as a whole ----------

def _check_sells(existing, new_trades, actions=()):
    """Goes through every trade in date order and reports any SELL of more shares than held.

    Splits and bonus issues (actions) change holdings on their ex-date, before that day's trades.
    Saved trades come next on the same day; new trades keep their order in the file.
    """
    events = [(a["ex_date"], -1, a, False) for a in actions]
    events += [(t["trade_date"], 0, t, False) for t in existing]
    events += [(t["trade_date"], 1, t, True) for t in new_trades]
    events.sort(key=lambda e: (e[0], e[1]))    # sort is stable, so file order is kept

    held = {}
    errors = []
    for trade_date, kind, t, is_new in events:
        if kind == -1:
            held[t["ticker"]] = shares_after(held.get(t["ticker"], 0), t["factor"])
            continue
        ticker, qty = t["ticker"], t["quantity"]
        if t["side"] == "BUY":
            held[ticker] = held.get(ticker, 0) + qty
            continue
        have = held.get(ticker, 0)
        if qty > have:
            if is_new:
                errors.append(
                    f"Row {t['row']}: sells {qty} {ticker} on {trade_date}, but only {have} are held then"
                )
            else:
                errors.append(
                    f"{ticker}: these trades leave too few shares for the sale of {qty} already saved on {trade_date}"
                )
            continue                            # don't apply an impossible sale
        held[ticker] = have - qty
    return errors


def _trade_key(t):
    """What makes two trades the same, used to spot trades that were already imported."""
    return (t["ticker"], t["trade_date"], t["side"], t["quantity"], round(t["price"], 4))


def import_trades_csv(conn, user_id, source, today=None):
    """Checks and imports a trades CSV for one user.

    source is a file path, or an uploaded file object (the web app will pass one).
    Returns an ImportResult. If result.errors isn't empty, nothing was saved.
    """
    today = today or date.today()
    result = ImportResult()

    # dtype=str: read every value as text, so we check it ourselves instead of pandas guessing.
    # keep_default_na=False: an empty cell stays "" instead of becoming NaN.
    try:
        df = pd.read_csv(source, dtype=str, keep_default_na=False)
    except FileNotFoundError:
        result.errors.append(f"File not found: {source}")
        return result
    except pd.errors.EmptyDataError:
        result.errors.append("The file is empty")
        return result
    except (pd.errors.ParserError, UnicodeDecodeError) as e:
        result.errors.append(f"This isn't a readable CSV file ({e})")
        return result

    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        result.errors.append(
            "Missing column(s): " + ", ".join(missing)
            + ". The first line must be: ticker,date,side,quantity,price,fees"
        )
        return result
    if df.empty:
        result.errors.append("The file has a header but no trades")
        return result
    if "fees" not in df.columns:
        df["fees"] = ""

    known_tickers = {i["ticker"] for i in db.get_instruments(conn)}

    # 1. Check each row on its own. Row 2 is the first trade, like in Excel.
    new_trades = []
    for i, row in enumerate(df.to_dict("records")):
        trade, errors = _check_row(row, i + 2, known_tickers, today)
        result.errors.extend(errors)
        if trade:
            new_trades.append(trade)
    if result.errors:
        return result

    # 2. Skip trades that are already saved, so importing the same file twice is harmless.
    existing = [dict(t) for t in db.get_trades(conn, user_id)]
    saved_keys = {_trade_key(t) for t in existing}
    to_save = [t for t in new_trades if _trade_key(t) not in saved_keys]
    result.skipped = len(new_trades) - len(to_save)

    # 3. Check sells against everything held at that date, old and new trades together.
    tickers = {t["ticker"] for t in existing + to_save}
    actions = [dict(a, ticker=tk) for tk in sorted(tickers) for a in db.get_actions(conn, tk)]
    result.errors.extend(_check_sells(existing, to_save, actions))
    if result.errors:
        return result

    # 4. Save everything in one transaction.
    if to_save:
        result.imported = db.add_trades(conn, user_id, to_save)
    return result


# ---------- Run directly ----------

DEMO_EMAIL = "demo@sgxray.local"


def main(argv):
    if len(argv) != 2:
        print("Usage: python src/importer.py <trades.csv>")
        return 1

    conn = db.get_connection()
    db.init_db(conn)
    seed_instruments(conn)

    # A demo user until sign-up exists. "!" is never a valid password hash, so nobody can log in as it.
    user = db.get_user_by_email(conn, DEMO_EMAIL)
    user_id = user["id"] if user else db.create_user(conn, DEMO_EMAIL, "!demo-no-login")

    result = import_trades_csv(conn, user_id, argv[1])
    if not result.ok:
        print("Nothing was imported. Fix these and try again:")
        for e in result.errors:
            print("  -", e)
        conn.close()
        return 1

    print(f"Imported {result.imported} trades ({result.skipped} already saved, skipped).")
    from portfolio import positions     # here, not at the top: portfolio imports this file too

    print("Holdings now (splits and bonus issues are added once market.py has fetched them):")
    for h in positions(conn, user_id).itertuples():
        if h.shares > 0:
            print(f"  {h.ticker:<8} {h.shares:>6} shares")
    print_warnings(check_trades(conn, user_id))   # only finds things once prices are saved
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
