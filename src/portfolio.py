"""Portfolio analysis with pandas: what you hold, what it cost, and how much you've made.

Uses the AVERAGE COST method, which Singapore brokers use:
- A BUY adds (quantity x price + fees) to the cost, so fees are part of what a share cost you.
- A SELL takes out its share of the cost at the average cost per share. The profit on the sale
  (sale money - fees - that cost) is REALISED: it's locked in.
- What you still hold has UNREALISED profit: market value now - its remaining cost. It changes
  every day with the price, and only becomes real when you sell.

    python src/portfolio.py
"""

import sys

import pandas as pd

import db
from adjust import shares_after

COLUMNS = [
    "ticker", "shares", "avg_cost", "cost", "price_date", "price", "value",
    "unrealised", "unrealised_pct", "realised", "fees",
]


def trades_frame(conn, user_id, as_of=None):
    """One user's trades as a pandas DataFrame, oldest first, optionally only up to as_of."""
    df = pd.DataFrame([dict(t) for t in db.get_trades(conn, user_id)])
    if df.empty:
        return df
    if as_of:
        df = df[df["trade_date"] <= as_of]    # dates are 'YYYY-MM-DD' text, so text order = date order
    return df


def _average_cost(trades, actions=()):
    """Walks one ticker's trades in order and returns its totals.

    This has to be a loop, not one pandas calculation: each SELL depends on the average cost
    at that moment, which depends on every trade before it.

    A split or bonus issue changes the number of shares but not the total cost, so the
    average cost per share drops. It counts from the start of its ex-date: shares bought on
    the ex-date don't get it, shares sold on the ex-date already did.
    """
    shares, cost, realised, fees = 0, 0.0, 0.0, 0.0
    pending = list(actions)                          # oldest first
    for t in trades.itertuples():
        while pending and pending[0]["ex_date"] <= t.trade_date:
            shares = shares_after(shares, pending.pop(0)["factor"])
        fees += t.fees
        if t.side == "BUY":
            shares += t.quantity
            cost += t.quantity * t.price + t.fees
        else:
            avg = cost / shares                       # the importer guarantees shares >= quantity
            realised += t.quantity * t.price - t.fees - t.quantity * avg
            cost -= t.quantity * avg
            shares -= t.quantity
            if shares == 0:
                cost = 0.0                            # sold out: start fresh, no rounding leftovers
    for action in pending:                            # actions after the last trade
        shares = shares_after(shares, action["factor"])
    return {"shares": shares, "cost": cost, "realised": realised, "fees": fees}


def positions(conn, user_id, as_of=None):
    """One row per ticker ever traded: holdings, average cost, value and profit, as of a date.

    Prices are the newest saved close on or before as_of. A ticker with no saved price yet
    has no value or unrealised profit (NaN), rather than a made-up number.
    """
    trades = trades_frame(conn, user_id, as_of)
    if trades.empty:
        return pd.DataFrame(columns=COLUMNS)

    rows = []
    for ticker, group in trades.groupby("ticker", sort=True):
        actions = [a for a in db.get_actions(conn, ticker) if not as_of or a["ex_date"] <= as_of]
        row = {"ticker": ticker, **_average_cost(group, actions)}
        latest = db.get_latest_close(conn, ticker, as_of)
        row["price_date"], row["price"] = latest if latest else (None, float("nan"))
        rows.append(row)

    df = pd.DataFrame(rows)
    # Whole-column maths: pandas does each line for every row at once.
    df["avg_cost"] = (df["cost"] / df["shares"]).where(df["shares"] > 0)
    df["value"] = df["shares"] * df["price"]
    df["unrealised"] = df["value"] - df["cost"]
    df["unrealised_pct"] = (df["unrealised"] / df["cost"]).where(df["cost"] > 0)
    return df[COLUMNS]


def summary(df):
    """Totals for the whole portfolio, from a positions() table."""
    cost, value = df["cost"].sum(), df["value"].sum(min_count=1)
    return {
        "cost": cost,
        "value": value,
        "unrealised": value - cost,
        "unrealised_pct": (value - cost) / cost if cost else float("nan"),
        "realised": df["realised"].sum(),
        "fees": df["fees"].sum(),
    }


# ---------- Run directly ----------

def _money(x):
    return "-" if pd.isna(x) else f"{x:,.2f}"


def main():
    from importer import DEMO_EMAIL

    conn = db.get_connection()
    db.init_db(conn)
    user = db.get_user_by_email(conn, DEMO_EMAIL)
    if not user:
        print("No demo portfolio yet. Run: python src/importer.py data/demo_trades.csv")
        return 1

    df = positions(conn, user["id"])
    conn.close()
    held = df[df["shares"] > 0]

    print(f"{'Ticker':<8} {'Shares':>7} {'Avg cost':>9} {'Price':>7} {'Cost':>10} {'Value':>10} {'Unrealised':>11} {'%':>7}")
    for r in held.itertuples():
        pct = "-" if pd.isna(r.unrealised_pct) else f"{r.unrealised_pct:+.1%}"
        print(f"{r.ticker:<8} {r.shares:>7} {r.avg_cost:>9.4f} {_money(r.price):>7} "
              f"{_money(r.cost):>10} {_money(r.value):>10} {_money(r.unrealised):>11} {pct:>7}")

    s = summary(df)
    print()
    print(f"Prices as of {held['price_date'].max()}")
    print(f"Total cost      ${_money(s['cost'])}")
    print(f"Value now       ${_money(s['value'])}")
    print(f"Unrealised      ${_money(s['unrealised'])} ({s['unrealised_pct']:+.1%})  - on paper, until you sell")
    print(f"Realised        ${_money(s['realised'])}  - locked in from sales")
    print(f"Fees paid       ${_money(s['fees'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
