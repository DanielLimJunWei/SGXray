"""Small extra numbers for the portfolio page: day's change, simple total return, weights,
sold-out stocks and each stock's 52-week range.

All prices are end-of-day closes, so "day's change" is the move from the previous close to the
latest close, labelled with its date. It's never a live price.
"""

import pandas as pd

import db
from portfolio import positions, summary, trades_frame


def day_change(conn, user_id, history):
    """How much your holdings moved on the latest trading day: the change in profit from the
    previous close to the latest one (so a buy or sale that day doesn't count as a gain),
    and which stock moved the most. None if there are fewer than two days of history."""
    h = history.dropna(subset=["value"]) if history is not None and not history.empty else None
    if h is None or len(h) < 2:
        return None
    today, before = h.iloc[-1], h.iloc[-2]
    change = float(today.profit - before.profit)
    movers = []
    for p in positions(conn, user_id, h.index[-1].date().isoformat()).itertuples():
        if p.shares <= 0:
            continue
        closes = [r["close"] for r in db.get_prices(conn, p.ticker, h.index[-2].date().isoformat())
                  if r["price_date"] <= h.index[-1].date().isoformat()]
        if len(closes) >= 2:
            movers.append({"ticker": p.ticker, "change": p.shares * (closes[-1] - closes[0]),
                           "pct": closes[-1] / closes[0] - 1})
    movers.sort(key=lambda m: abs(m["change"]), reverse=True)
    # The market on the same day (w302): the STI ETF's close on the same two days, if it has both.
    from market import BENCHMARK
    sti = {r["price_date"]: r["close"] for r in db.get_prices(conn, BENCHMARK, h.index[-2].date().isoformat())}
    a, b = sti.get(h.index[-2].date().isoformat()), sti.get(h.index[-1].date().isoformat())
    return {
        "date": h.index[-1].date().isoformat(),
        "previous": h.index[-2].date().isoformat(),
        "change": change,
        "pct": change / before.value if before.value else float("nan"),
        "movers": movers,
        "sti_pct": (b / a - 1) if a and b else float("nan"),
    }


def money_put_in(conn, user_id, as_of=None):
    """Everything you've ever paid for buys, fees included (sales don't reduce it)."""
    t = trades_frame(conn, user_id, as_of)
    if t.empty:
        return 0.0
    buys = t[t["side"] == "BUY"]
    return float((buys["quantity"] * buys["price"] + buys["fees"]).sum())


def simple_return(conn, user_id, as_of=None):
    """Total profit divided by all the money you've put in: one plain percentage, not a yearly rate."""
    s = summary(positions(conn, user_id, as_of))
    put_in = money_put_in(conn, user_id, as_of)
    profit = s["total_profit"]
    t = trades_frame(conn, user_id, as_of)
    days = (pd.Timestamp(s["prices_as_of"]) - pd.Timestamp(t["trade_date"].min())).days if s["prices_as_of"] and not t.empty else 0
    return {"put_in": put_in, "profit": profit, "pct": profit / put_in if put_in and profit == profit else float("nan"),
            "days": days}


def weights(df):
    """Each held stock's share of what the whole portfolio is worth, by ticker (NaN if a price is missing)."""
    held = df[df["shares"] > 0]
    total = held["value"].sum(skipna=False)
    if not total or total != total:
        return {t: float("nan") for t in held["ticker"]}
    return {r.ticker: float(r.value / total) for r in held.itertuples()}


def sold_out(conn, user_id, as_of=None):
    """Stocks you've sold completely: what you put in, got back, made from selling, and earned in dividends."""
    df = positions(conn, user_id, as_of)
    out = df[(df["shares"] == 0)]
    if out.empty:
        return []
    t = trades_frame(conn, user_id, as_of)
    rows = []
    for p in out.itertuples():
        mine = t[t["ticker"] == p.ticker]
        buys, sells = mine[mine["side"] == "BUY"], mine[mine["side"] == "SELL"]
        rows.append({
            "ticker": p.ticker,
            "first_buy": mine["trade_date"].min(),
            "last_sale": sells["trade_date"].max(),
            "put_in": float((buys["quantity"] * buys["price"] + buys["fees"]).sum()),
            "got_back": float((sells["quantity"] * sells["price"] - sells["fees"]).sum()),
            "realised": float(p.realised),
            "dividends": float(p.dividends),
            "total": float(p.realised + p.dividends),
        })
    return sorted(rows, key=lambda r: r["last_sale"], reverse=True)


def week52(conn, ticker, as_of):
    """The highest and lowest close over the 52 weeks to as_of, where today's close sits between them
    (0 = at the low, 1 = at the high), and whether a bonus issue or split in that time makes the
    range misleading (prices are real, so they drop on those days without any loss in value)."""
    end = pd.Timestamp(as_of)
    start = (end - pd.DateOffset(weeks=52)).date().isoformat()
    closes = [(r["price_date"], r["close"]) for r in db.get_prices(conn, ticker, start) if r["price_date"] <= as_of]
    if len(closes) < 20:                               # not enough of a year to call it a range
        return None
    values = [c for _, c in closes]
    hi, lo, now = max(values), min(values), values[-1]
    actions = [a for a in db.get_actions(conn, ticker) if start < a["ex_date"] <= as_of]
    return {
        "high": hi, "high_date": next(d for d, c in closes if c == hi),
        "low": lo, "low_date": next(d for d, c in closes if c == lo),
        "now": now, "position": (now - lo) / (hi - lo) if hi > lo else 0.5,
        "full_year": closes[0][0] <= (end - pd.DateOffset(weeks=51)).date().isoformat(),
        "action_inside": bool(actions),
    }
