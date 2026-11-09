"""Portfolio analysis with pandas: what you hold, what it cost, and how much you've made.

Uses the AVERAGE COST method, which Singapore brokers use:
- A BUY adds (quantity x price + fees) to the cost, so fees are part of what a share cost you.
- A SELL takes out its share of the cost at the average cost per share. The profit on the sale
  (sale money - fees - that cost) is REALISED: it's locked in.
- What you still hold has UNREALISED profit: market value now - its remaining cost. It changes
  every day with the price, and only becomes real when you sell.
- DIVIDENDS count for every share held at the start of each ex-date. Total profit =
  unrealised + realised + dividends.

    python src/portfolio.py
"""

import sys

import pandas as pd

import db
from adjust import shares_after
from fmt import money, num, pct

COLUMNS = [
    "ticker", "shares", "avg_cost", "cost", "price_date", "price", "value",
    "unrealised", "unrealised_pct", "realised", "dividends", "fees",
]
DIVIDEND_COLUMNS = ["ticker", "ex_date", "shares", "amount", "total"]


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
            if t.quantity > shares:                   # the importer stops this; guard anything else that saves trades
                raise ValueError(
                    f"{t.ticker} sells {t.quantity} on {t.trade_date} but only {shares} are held then"
                )
            avg = cost / shares
            realised += t.quantity * t.price - t.fees - t.quantity * avg
            cost -= t.quantity * avg
            shares -= t.quantity
            if shares == 0:
                cost = 0.0                            # sold out: start fresh, no rounding leftovers
    for action in pending:                            # actions after the last trade
        shares = shares_after(shares, action["factor"])
    return {"shares": shares, "cost": cost, "realised": realised, "fees": fees}


def dividends_received(conn, user_id, as_of=None):
    """Every dividend the user was entitled to: one row per ticker and ex-date.

    Shares held = trades BEFORE the ex-date (buying on the ex-date is too late), with any
    split or bonus issue BEFORE that day. If a bonus issue has the same ex-date as a dividend,
    the new shares arrive after the record date, so they don't get that dividend.
    Ignored dividends don't count.
    The cash usually arrives a few weeks after the ex-date; SGXray counts it from the ex-date.
    Singapore dividends and REIT distributions are tax-free for individuals, so there's no tax to take off.
    """
    trades = trades_frame(conn, user_id, as_of)
    if trades.empty:
        return pd.DataFrame(columns=DIVIDEND_COLUMNS)

    rows = []
    for ticker, group in trades.groupby("ticker", sort=True):
        actions = db.get_actions(conn, ticker)
        for d in db.get_dividends(conn, ticker, include_ignored=False):
            day = d["ex_date"]
            if as_of and day > as_of:
                continue
            before = group[group["trade_date"] < day]
            if before.empty:
                continue
            shares = _average_cost(before, [a for a in actions if a["ex_date"] < day])["shares"]
            if shares > 0:
                rows.append({"ticker": ticker, "ex_date": day, "shares": shares, "amount": d["amount"]})

    df = pd.DataFrame(rows, columns=DIVIDEND_COLUMNS)
    df["total"] = df["shares"] * df["amount"]
    return df.sort_values(["ex_date", "ticker"], ignore_index=True)    # newest last, like a statement


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
    # Dividends per ticker: group the dividend rows and add up their totals.
    paid = dividends_received(conn, user_id, as_of).groupby("ticker")["total"].sum()
    df["dividends"] = df["ticker"].map(paid).fillna(0.0)
    # Whole-column maths: pandas does each line for every row at once.
    df["avg_cost"] = (df["cost"] / df["shares"]).where(df["shares"] > 0)
    # Sold out = worth $0, even if we have no price (0 shares x unknown price is still 0).
    df["value"] = (df["shares"] * df["price"]).where(df["shares"] > 0, 0.0)
    df["unrealised"] = df["value"] - df["cost"]
    df["unrealised_pct"] = (df["unrealised"] / df["cost"]).where(df["cost"] > 0)
    return df[COLUMNS]


STALE_DAYS = 5      # a price this many days older than the newest one is flagged as stale


def summary(df):
    """Totals for the whole portfolio, from a positions() table.

    If any stock you still hold has no price, the value and profit totals are NaN (unknown)
    and the stock is listed in 'missing_prices'. Adding up only the stocks that have prices
    would quietly show a total that's too low.
    """
    held = df[df["shares"] > 0]
    missing = sorted(held.loc[held["price"].isna(), "ticker"])
    cost = df["cost"].sum()
    value = float("nan") if missing else df["value"].sum()
    realised, dividends = df["realised"].sum(), df["dividends"].sum()

    dates = pd.to_datetime(held["price_date"].dropna())
    newest = dates.max() if len(dates) else None
    stale = sorted(
        held.loc[pd.to_datetime(held["price_date"]) < newest - pd.Timedelta(days=STALE_DAYS), "ticker"]
    ) if newest is not None else []

    return {
        "missing_prices": missing,
        "stale_prices": stale,
        "prices_as_of": newest.date().isoformat() if newest is not None else None,
        "cost": cost,
        "value": value,
        "unrealised": value - cost,
        "unrealised_pct": (value - cost) / cost if cost else float("nan"),
        "realised": realised,
        "dividends": dividends,
        "total_profit": (value - cost) + realised + dividends,
        "fees": df["fees"].sum(),
    }


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

    df = positions(conn, user["id"])
    dividends = dividends_received(conn, user["id"])
    conn.close()
    if df.empty:
        print("No trades yet.")
        return 0
    held = df[df["shares"] > 0]

    if held.empty:
        print("You don't hold any stocks right now.")
    else:
        print(f"{'Ticker':<8} {'Shares':>7} {'Avg cost':>9} {'Price':>7} {'Cost':>11} {'Value':>11} {'Unrealised':>12} {'%':>8}")
        for r in held.itertuples():
            print(f"{r.ticker:<8} {r.shares:>7} {num(r.avg_cost, '.4f'):>9} {num(r.price):>7} "
                  f"{money(r.cost):>11} {money(r.value):>11} {money(r.unrealised):>12} {pct(r.unrealised_pct):>8}")

    s = summary(df)
    print()
    print(f"Prices as of {s['prices_as_of'] or 'n/a (no prices saved yet)'}")
    if s["missing_prices"]:
        print(f"  ! No price yet for {', '.join(s['missing_prices'])}: run python src/market.py. Totals can't be worked out until then.")
    if s["stale_prices"]:
        print(f"  ! Older prices for {', '.join(s['stale_prices'])} (suspended, or the download failed?)")
    print(f"Total cost      {money(s['cost'])}")
    print(f"Value now       {money(s['value'])}")
    print(f"Unrealised      {money(s['unrealised'])} ({pct(s['unrealised_pct'])})  - on paper, until you sell")
    print(f"Realised        {money(s['realised'])}  - locked in from sales")
    print(f"Dividends       {money(s['dividends'])}  - cash paid to you")
    print(f"Total profit    {money(s['total_profit'])}  - all three added up")
    print(f"Fees paid       {money(s['fees'])}  - already counted in the costs above")

    if not dividends.empty:
        print()
        print("Dividends received")
        for d in dividends.itertuples():
            print(f"  {d.ex_date}  {d.ticker:<8} {d.shares:>5} x ${d.amount:<8g} = {money(d.total)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
