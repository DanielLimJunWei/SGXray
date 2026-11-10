"""One stock's story on a chart: its closing prices, your buys and sells, its dividends, and your
average cost over time.

The average cost is a STEP line: it only changes when you buy or sell, or on a bonus issue or
split (more shares for the same total cost, so each share cost you less). Prices are real
(un-adjusted), so on a bonus issue the price drops on the ex-date and the average cost drops too.
"""

import pandas as pd

import db
from performance import valuation_date
from portfolio import _average_cost, dividends_received, trades_frame

MAX_POINTS = 400            # enough for a smooth line on any screen; fewer points keep the page light


def stock_history(conn, user_id, ticker, as_of=None):
    """Everything the price chart for one stock needs, as plain values for the page's script.

    Returns None if you never traded this stock.
    """
    trades = trades_frame(conn, user_id, as_of)
    if trades.empty or ticker not in set(trades["ticker"]):
        return None
    mine = trades[trades["ticker"] == ticker].reset_index(drop=True)
    first = mine["trade_date"].min()
    end = valuation_date(conn, trades, as_of)
    end = end.isoformat() if hasattr(end, "isoformat") else str(end)

    prices = [(r["price_date"], r["close"]) for r in db.get_prices(conn, ticker, first) if r["price_date"] <= end]
    actions = [a for a in db.get_actions(conn, ticker) if a["ex_date"] <= end]

    # Average cost after each event (trade, bonus issue or split), oldest first.
    events = sorted(set(mine["trade_date"]) | {a["ex_date"] for a in actions if a["ex_date"] >= first})
    steps = []
    for day in events:
        totals = _average_cost(mine[mine["trade_date"] <= day], [a for a in actions if a["ex_date"] <= day])
        steps.append({"date": day, "avg": round(totals["cost"] / totals["shares"], 4) if totals["shares"] else None,
                      "shares": totals["shares"]})

    paid = dividends_received(conn, user_id, as_of)
    paid = paid[paid["ticker"] == ticker] if not paid.empty else paid
    dividends = [{"date": d.ex_date, "amount": float(d.amount), "shares": int(d.shares), "total": round(float(d.total), 2)}
                 for d in paid.itertuples()] if not paid.empty else []

    return {
        "ticker": ticker,
        "prices": _thin(prices, keep={t for t in mine["trade_date"]} | {d["date"] for d in dividends}),
        "trades": [{"date": t.trade_date, "side": t.side, "qty": int(t.quantity), "price": float(t.price),
                    "fees": float(t.fees)} for t in mine.itertuples()],
        "dividends": dividends,
        "actions": [{"date": a["ex_date"], "factor": a["factor"]} for a in actions if a["ex_date"] >= first],
        "avg_steps": steps,
    }


def _thin(prices, keep):
    """At most MAX_POINTS prices, evenly spaced, always keeping the first, the last, and the days
    something happened (a buy, a sell or a dividend), so every marker sits on the line."""
    if len(prices) <= MAX_POINTS:
        return [[d, round(c, 4)] for d, c in prices]
    step = len(prices) / MAX_POINTS
    picked = {int(i * step) for i in range(MAX_POINTS)} | {0, len(prices) - 1}
    picked |= {i for i, (d, _) in enumerate(prices) if d in keep}
    return [[prices[i][0], round(prices[i][1], 4)] for i in sorted(picked)]


def price_on(history, day):
    """The closing price on a day, or the last one before it (for markers on non-trading days)."""
    before = [c for d, c in history["prices"] if d <= day]
    return before[-1] if before else None


def last_avg(history):
    return history["avg_steps"][-1]["avg"] if history["avg_steps"] else None


def to_frame(history):
    """The prices as a pandas Series indexed by date (handy for tests and explanations)."""
    return pd.Series({pd.Timestamp(d): c for d, c in history["prices"]}, dtype=float)
