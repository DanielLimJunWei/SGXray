"""Dividend income: yields, and a forecast of the next 12 months.

THE FORECAST is an estimate, not a promise. It assumes each stock pays again what it paid
over the last 12 months, around the same dates, on the shares you hold now. That's how most
trackers do it, and it's a fair guess for steady payers like the banks, but:
- dividends can be cut or raised (DBS raised its dividend every year from 2024 to 2026);
- one-off payouts, like a REIT's "advanced distribution" before raising money, may not repeat;
- dates are estimates: the company announces the real ex-date shortly before.

DIVIDEND YIELD = a year's dividends per share / today's price. "Trailing" means it uses the
LAST 12 months of actual payouts, not a guess about the future.
YIELD ON COST = the same dividends / what YOU paid per share (your average cost).

    python src/income.py
"""

import sys

import pandas as pd

import db
from fmt import money, num, pct
from portfolio import positions, summary

FORECAST_COLUMNS = ["expected", "ticker", "shares", "amount", "total", "based_on"]


def _window(as_of):
    """The 12 months up to and including as_of."""
    end = pd.Timestamp(as_of)
    return end - pd.DateOffset(years=1), end


def trailing_dividends(conn, ticker, as_of):
    """The dividends `ticker` paid in the 12 months up to as_of (ignored ones left out),
    each restated PER SHARE YOU HOLD NOW.

    Why restate: after a 2-for-1 split, a $1.00 dividend paid on one old share was really
    $0.50 for each of today's shares. Using $1.00 doubled the yield and the forecast
    (found in the second audit). So each amount is divided by every split or bonus from its
    ex-date (a same-day bonus counts: those new shares didn't get that dividend) up to as_of.
    'paid' keeps the amount as really paid at the time.
    """
    start, end = _window(as_of)
    actions = db.get_actions(conn, ticker)
    out = []
    for d in db.get_dividends(conn, ticker, include_ignored=False):
        if not start < pd.Timestamp(d["ex_date"]) <= end:
            continue
        factor = 1.0
        for a in actions:
            if d["ex_date"] <= a["ex_date"] <= as_of:
                factor *= a["factor"]
        out.append({"ex_date": d["ex_date"], "amount": d["amount"] / factor, "paid": d["amount"]})
    return out


def _as_of(conn, user_id, as_of):
    return as_of or summary(positions(conn, user_id))["prices_as_of"]


def forecast(conn, user_id, as_of=None):
    """Expected dividends over the 12 months after as_of, one row per expected payout.

    Each of the last 12 months' dividends is assumed to come again one year later, on the
    shares held now. A stock you've sold out of isn't in the forecast.
    """
    as_of = _as_of(conn, user_id, as_of)
    if not as_of:
        return pd.DataFrame(columns=FORECAST_COLUMNS)
    held = positions(conn, user_id, as_of)
    held = held[held["shares"] > 0]

    rows = []
    for p in held.itertuples():
        for d in trailing_dividends(conn, p.ticker, as_of):
            last_time = pd.Timestamp(d["ex_date"])
            rows.append({
                "expected": last_time + pd.DateOffset(years=1),   # same date next year (29 Feb -> 28 Feb)
                "ticker": p.ticker,
                "shares": p.shares,
                "amount": d["amount"],
                "total": p.shares * d["amount"],
                "based_on": d["ex_date"],
            })
    df = pd.DataFrame(rows, columns=FORECAST_COLUMNS)
    return df.sort_values(["expected", "ticker"], ignore_index=True)


def yields(conn, user_id, as_of=None):
    """Trailing 12-month dividend yield per stock held: on today's price, and on your cost."""
    as_of = _as_of(conn, user_id, as_of)
    held = positions(conn, user_id, as_of)
    held = held[held["shares"] > 0]
    rows = []
    for p in held.itertuples():
        per_share = sum(d["amount"] for d in trailing_dividends(conn, p.ticker, as_of)) if as_of else 0.0
        rows.append({
            "ticker": p.ticker,
            "per_share_12m": per_share,
            "price": p.price,
            "div_yield": per_share / p.price if p.price == p.price and p.price else float("nan"),
            "avg_cost": p.avg_cost,
            "yield_on_cost": per_share / p.avg_cost if p.avg_cost else float("nan"),
            "income_12m": per_share * p.shares,
        })
    return pd.DataFrame(rows, columns=["ticker", "per_share_12m", "price", "div_yield", "avg_cost", "yield_on_cost", "income_12m"])


def by_year(conn, user_id, as_of=None):
    """Dividends you actually received, added up per calendar year (by ex-date), with a split per stock.

    Two years are usually only part-years, and each row says so:
    - "first": the year you started, if your first trade wasn't in January;
    - "so far": the year of the newest price, which isn't over yet.
    Comparing a part-year with a full year makes income look like it fell or jumped when it didn't.
    """
    from portfolio import dividends_received, trades_frame

    paid = dividends_received(conn, user_id, as_of)
    trades = trades_frame(conn, user_id, as_of)
    if paid.empty or trades.empty:
        return []
    as_of = _as_of(conn, user_id, as_of)
    first = pd.Timestamp(trades["trade_date"].min())
    newest = pd.Timestamp(as_of) if as_of else None
    paid = paid.assign(year=paid["ex_date"].str[:4].astype(int))

    rows = []
    for year in range(first.year, (newest.year if newest is not None else first.year) + 1):
        this = paid[paid["year"] == year]
        part = None
        if newest is not None and year == newest.year and (newest.month, newest.day) != (12, 31):
            part = "so far"
        elif year == first.year and first.month > 1:
            part = "first"
        rows.append({
            "year": year,
            "total": float(this["total"].sum()),
            "by_stock": {t: float(v) for t, v in this.groupby("ticker")["total"].sum().sort_values(ascending=False).items()},
            "part": part,
            "from_month": first.strftime("%B") if part == "first" else None,
            "to_date": newest.strftime("%Y-%m-%d") if part == "so far" else None,
        })
    return rows


def portfolio_yield(df_yields, df_positions):
    """The whole portfolio's yield: a year's dividends on what you hold / what it's worth now.
    Unknown (NaN) if any stock you hold has no price, rather than quietly too high."""
    held = df_positions[df_positions["shares"] > 0]
    if held["value"].isna().any():
        return float("nan")
    value = held["value"].sum()
    return df_yields["income_12m"].sum() / value if value else float("nan")


# ---------- Run directly ----------

def main():
    from fmt import safe_console
    safe_console()                     # never crash printing characters the terminal can't show
    from importer import DEMO_EMAIL

    conn = db.get_connection()
    db.init_db(conn)
    user = db.get_user_by_email(conn, DEMO_EMAIL)
    if not user:
        print("No demo portfolio yet. Run: python src/importer.py data/demo_trades.csv")
        return 1
    uid = user["id"]
    as_of = _as_of(conn, uid, None)
    y = yields(conn, uid)
    f = forecast(conn, uid)
    pos = positions(conn, uid)
    conn.close()

    if y.empty:
        print("You don't hold any stocks right now, so there are no yields or expected dividends.")
        return 0
    print(f"Dividend yields (last 12 months of payouts, prices as of {as_of or 'n/a'})")
    print(f"  {'Ticker':<8} {'Paid/share':>10} {'Price':>7} {'Yield':>7} {'Your cost':>9} {'On cost':>8}")
    for r in y.itertuples():
        print(f"  {r.ticker:<8} {r.per_share_12m:>10.4f} {num(r.price):>7} {pct(r.div_yield, False):>7} "
              f"{num(r.avg_cost, '.4f'):>9} {pct(r.yield_on_cost, False):>8}")
    print(f"  Whole portfolio: {pct(portfolio_yield(y, pos), False)} a year on today's value")

    print()
    if f.empty:
        print("No dividends expected: nothing you hold paid one in the last 12 months.")
        return 0
    print("Expected dividends, next 12 months (an ESTIMATE: last year's payouts on what you hold now)")
    for r in f.itertuples():
        print(f"  ~{r.expected:%d %b %Y}  {r.ticker:<8} {r.shares:>5,} x ${r.amount:<8g} = {money(r.total):>9}"
              f"   (like {pd.Timestamp(r.based_on):%d %b %Y})")
    by_month = f.groupby(f["expected"].dt.to_period("M"))["total"].sum()
    print()
    print("  By month: " + ", ".join(f"{m:%b %Y} {money(t)}" for m, t in by_month.items()))
    print(f"  Total: about {money(f['total'].sum())} over the next 12 months")
    print("  Dividends can be cut, raised or skipped, and one-off payouts may not repeat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
