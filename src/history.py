"""Portfolio value over time: one row per trading day, for charts and the risk view.

Built the pandas way, as tables that line up by date:
1. PRICES: a table of closing prices, one column per ticker, one row per trading day.
2. HOLDINGS: a table of shares held, same shape, from the trades and bonus issues.
3. VALUE: holdings x prices, cell by cell, then added across each row.

Each row also has the money you've put in (minus what you took out), dividends so far,
and profit so far, plus the same money in the STI ETF, so a chart can show both lines.

    python src/history.py
"""

import sys

import pandas as pd

import db
from adjust import shares_after
from market import BENCHMARK
from performance import benchmark
from portfolio import dividends_received, trades_frame

COLUMNS = ["value", "net_invested", "dividends", "profit", "sti_value", "sti_dividends", "sti_profit"]


def _price_table(conn, tickers, days):
    """Closing prices: rows = days, columns = tickers.

    ffill ("forward fill") carries the last known price over a missing day, e.g. a stock
    that was suspended. A day before a stock's first saved price stays empty (NaN).
    """
    columns = {}
    for ticker in tickers:
        rows = db.get_prices(conn, ticker)
        series = pd.Series({pd.Timestamp(r["price_date"]): r["close"] for r in rows}, dtype=float)
        columns[ticker] = series
    table = pd.DataFrame(columns)
    return table.reindex(table.index.union(days)).sort_index().ffill().reindex(days)


def _holdings_table(conn, trades, days):
    """Shares held at each day's close: rows = days, columns = tickers.

    A bonus issue counts from the start of its ex-date; a trade counts by that day's close.
    So on each day: apply that day's bonus issues first, then that day's trades.
    """
    columns = {}
    for ticker, group in trades.groupby("ticker"):
        events = [(a["ex_date"], 0, "ACTION", a["factor"]) for a in db.get_actions(conn, ticker)]
        events += [(t.trade_date, 1, t.side, t.quantity) for t in group.itertuples()]
        events.sort(key=lambda e: (e[0], e[1]))           # stable: same-day trades keep their order

        shares, after_day = 0, {}
        for day, _, kind, x in events:
            if kind == "ACTION":
                shares = shares_after(shares, x)
            elif kind == "BUY":
                shares += x
            else:
                shares -= x
            after_day[pd.Timestamp(day)] = shares          # the last event of a day wins
        columns[ticker] = pd.Series(after_day, dtype=float)

    table = pd.DataFrame(columns)
    # Carry each day's holdings forward until the next change; before the first trade = 0 shares.
    return table.reindex(table.index.union(days)).sort_index().ffill().fillna(0).reindex(days)


def _cash_in_out(trades):
    """Net money put in per day: buys (with fees) add, sales (after fees) take away."""
    signed = trades.apply(
        lambda t: t.quantity * t.price + t.fees if t.side == "BUY" else -(t.quantity * t.price - t.fees),
        axis=1,
    )
    return signed.groupby(pd.to_datetime(trades["trade_date"])).sum()


def _running_total(amounts_by_day, days):
    """Running total (cumsum) of amounts, read off on each of `days`.

    The cumsum is taken over ALL the amounts' own dates first, and only then lined up with
    `days`. Lining up first would silently drop an amount whose date isn't in `days`, e.g. a
    dividend on a day with no saved price. (A test caught exactly that.)
    """
    if amounts_by_day.empty:
        return pd.Series(0.0, index=days)
    totals = amounts_by_day.sort_index().cumsum()
    return totals.reindex(totals.index.union(days)).ffill().fillna(0.0).reindex(days)


def value_history(conn, user_id, as_of=None):
    """One row per trading day from your first trade: value, money in, dividends, profit,
    and the same for the STI ETF version. A day where a held stock has no price yet is NaN."""
    trades = trades_frame(conn, user_id, as_of)
    if trades.empty:
        return pd.DataFrame(columns=COLUMNS)

    tickers = sorted(trades["ticker"].unique())
    first = pd.Timestamp(trades["trade_date"].min())
    all_days = sorted({pd.Timestamp(d) for d in db.get_trading_days(conn)})
    days = pd.DatetimeIndex([d for d in all_days if d >= first and (not as_of or d <= pd.Timestamp(as_of))])
    if days.empty:
        return pd.DataFrame(columns=COLUMNS)

    prices = _price_table(conn, tickers, days)
    holdings = _holdings_table(conn, trades, days)

    # A held stock with no price makes that day's value unknown, not lower:
    # 0 shares x unknown price is 0, but 100 shares x unknown price is unknown.
    cell_values = (holdings * prices).where(holdings > 0, 0.0)
    out = pd.DataFrame(index=days)
    out["value"] = cell_values.sum(axis=1, skipna=False)

    # Running totals: the money in, and dividends, up to and including each day.
    out["net_invested"] = _running_total(_cash_in_out(trades), days)
    paid = dividends_received(conn, user_id, as_of)
    paid_by_day = paid.groupby(pd.to_datetime(paid["ex_date"]))["total"].sum() if not paid.empty else pd.Series(dtype=float)
    out["dividends"] = _running_total(paid_by_day, days)
    out["profit"] = out["value"] - out["net_invested"] + out["dividends"]

    # The STI ETF version: its units on each day x its price.
    bench = benchmark(conn, user_id, as_of)
    units = pd.Series({pd.Timestamp(d): u for d, u in bench.units_history}, dtype=float)
    units = units.groupby(level=0).last()                   # several events on a day: keep the last
    units = units.reindex(units.index.union(days)).sort_index().ffill().fillna(0).reindex(days)
    sti_price = _price_table(conn, [BENCHMARK], days)[BENCHMARK]
    out["sti_value"] = units * sti_price
    sti_paid = pd.Series({pd.Timestamp(d): c for d, c in bench.dividend_history}, dtype=float)
    sti_paid = sti_paid.groupby(level=0).sum()
    out["sti_dividends"] = _running_total(sti_paid, days)
    out["sti_profit"] = out["sti_value"] - out["net_invested"] + out["sti_dividends"]
    return out[COLUMNS]


# ---------- Run directly ----------

def main():
    from importer import DEMO_EMAIL

    conn = db.get_connection()
    db.init_db(conn)
    user = db.get_user_by_email(conn, DEMO_EMAIL)
    if not user:
        print("No demo portfolio yet. Run: python src/importer.py data/demo_trades.csv")
        return 1
    h = value_history(conn, user["id"])
    trades = trades_frame(conn, user["id"])
    paid = dividends_received(conn, user["id"])
    conn.close()

    # What happened in each month, keyed by "YYYY-MM": trades by date, then dividends as one total.
    happened = {}
    for t in trades.itertuples():
        verb = "Bought" if t.side == "BUY" else "Sold"
        happened.setdefault(t.trade_date[:7], []).append(
            f"{verb} {t.quantity:,} {t.ticker} on {int(t.trade_date[8:])} {pd.Timestamp(t.trade_date):%b}"
        )
    for month, total in paid.groupby(paid["ex_date"].str[:7])["total"].sum().items():
        happened.setdefault(month, []).append(f"dividends ${total:,.2f}")

    # Group the days by month (to_period("M")) and keep each month's last row (tail(1)).
    # Unlike resample, this keeps the real date of that row: the last day SGX traded that month.
    monthly = h.groupby(h.index.to_period("M")).tail(1)
    print(f"{len(h)} trading days, {h.index[0].date()} to {h.index[-1].date()}.")
    print("Each row is a snapshot at the close on the last trading day of the month.")
    print(f"{'Snapshot':<11} {'Value':>11} {'Money in':>11} {'Profit':>10} {'STI profit':>11}  What happened that month")
    for day, r in monthly.iterrows():
        note = "; ".join(happened.get(f"{day:%Y-%m}", []))
        print(f"{day:%d %b %Y}  {r.value:>11,.2f} {r.net_invested:>11,.2f} {r.profit:>10,.2f} {r.sti_profit:>11,.2f}  {note}")

    best, worst = h["profit"].idxmax(), h["profit"].idxmin()
    print(f"\nHighest profit: ${h.loc[best, 'profit']:,.2f} on {best.date()}")
    print(f"Lowest profit:  ${h.loc[worst, 'profit']:,.2f} on {worst.date()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
