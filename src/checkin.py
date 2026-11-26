"""The monthly check-in (s11): one calm look a month instead of watching prices every day.

For a calendar month it says, from the same numbers as the dashboard:
- what your portfolio was worth at the last close before the month and at the month's last close;
- how that change splits into money you added (or took out) and the market's move;
- the dividends you became entitled to that month (ex-dates in the month, counted as SGXray always counts them);
- how the investments did that month, time-weighted, next to the STI ETF over the same days;
- which stock moved most, the trades you made, and the dividends expected in the next month.

A month you're in the middle of is "so far". Nothing here is advice.

    python src/checkin.py            (the demo account's last complete month)
"""

import pandas as pd

import db
import sgtime
from explain import Explanation
from history import _growth, value_history
from portfolio import dividends_received, trades_frame


def months(conn, user_id):
    """Every month from your first trade to the latest close, newest first, as 'YYYY-MM'."""
    h = value_history(conn, user_id)
    if h.empty:
        return []
    first, last = h.index[0], h.index[-1]
    out, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out[::-1]


def default_month(all_months, latest_close):
    """The latest complete month: last month, unless your history only started this month."""
    if not all_months:
        return None
    if len(all_months) > 1 and all_months[0] == latest_close[:7]:
        return all_months[1]
    return all_months[0]


def _price_move(conn, ticker, start_day, end_day):
    """A held stock's price change from one close to another, allowing for splits and bonus issues in between
    (one share then is `factor` shares now). None without both closes."""
    a, b = db.get_latest_close(conn, ticker, start_day), db.get_latest_close(conn, ticker, end_day)
    if not a or not b or a[0] == b[0]:
        return None
    a, b = a[1], b[1]
    factor = 1.0
    for act in db.get_actions(conn, ticker):
        if start_day < act["ex_date"] <= end_day:
            factor *= act["factor"]
    return b * factor / a - 1


def summary(conn, user_id, month):
    """The check-in for one month ('YYYY-MM'), or None if your history doesn't reach it."""
    h = value_history(conn, user_id)
    if h.empty:
        return None
    start = pd.Timestamp(f"{month}-01")
    end = start + pd.offsets.MonthEnd(0)
    inside = h[(h.index >= start) & (h.index <= end)]
    if inside.empty:
        return None
    before = h[h.index < start]
    last = inside.iloc[-1]
    base = before.iloc[-1] if not before.empty else None        # None: you started during this month
    v0 = float(base["value"]) if base is not None else 0.0
    n0 = float(base["net_invested"]) if base is not None else 0.0
    d0 = float(base["dividends"]) if base is not None else 0.0
    r = {
        "month": month,
        "so_far": month >= sgtime.today().strftime("%Y-%m"),      # the month hasn't ended yet
        "from_day": before.index[-1].date().isoformat() if base is not None else None,
        "to_day": inside.index[-1].date().isoformat(),
        "worth_start": v0, "worth_end": float(last["value"]),
        "added": float(last["net_invested"]) - n0,
        "dividends": float(last["dividends"]) - d0,
    }
    r["missing_price"] = r["worth_end"] != r["worth_end"] or r["worth_start"] != r["worth_start"]
    r["change"] = r["worth_end"] - r["worth_start"]
    r["market"] = r["change"] - r["added"]                       # what prices did, apart from your own money
    # Time-weighted, over the trading days in the month (each day's growth is from the previous close).
    g = _growth(conn, user_id, None, h)
    if g is not None:
        days = g[(g.index >= start) & (g.index <= end)]
        r["you"], r["sti"] = float(days["you"].prod() - 1), float(days["sti"].prod() - 1)
    else:
        r["you"] = r["sti"] = float("nan")
    # Trades that month, and the dividends you became entitled to (ex-dates in the month).
    t = trades_frame(conn, user_id)
    t = t[(t["trade_date"] >= start.date().isoformat()) & (t["trade_date"] <= end.date().isoformat())] if not t.empty else t
    r["buys"] = int((t["side"] == "BUY").sum()) if not t.empty else 0
    r["sells"] = int((t["side"] == "SELL").sum()) if not t.empty else 0
    d = dividends_received(conn, user_id)
    d = d[(d["ex_date"] >= start.date().isoformat()) & (d["ex_date"] <= end.date().isoformat())]
    r["paid"] = [{"ticker": x.ticker, "ex_date": x.ex_date, "total": float(x.total)} for x in d.itertuples()]
    # The biggest price move among the stocks you held at the month's end.
    from portfolio import positions
    p = positions(conn, user_id, r["to_day"])
    moves = []
    from_day = r["from_day"] or start.date().isoformat()
    for ticker in sorted(p[p["shares"] > 0]["ticker"]):
        mv = _price_move(conn, ticker, from_day, r["to_day"])
        if mv is not None:
            moves.append((ticker, mv))
    r["mover"] = max(moves, key=lambda x: abs(x[1])) if moves else None
    return r


def coming_up(conn, user_id, days=31):
    """Dividends expected in the next `days` days after the latest close, from the dashboard's forecast."""
    from income import forecast
    f = forecast(conn, user_id)
    if f.empty:
        return []
    h = value_history(conn, user_id)
    latest = h.index[-1]
    f = f[(f["expected"] > latest) & (f["expected"] <= latest + pd.Timedelta(days=days))]
    return [{"ticker": x.ticker, "expected": x.expected.date().isoformat(), "total": x.total, "status": x.status}
            for x in f.itertuples()]


def explain(r):
    """The ⓘ box for the check-in."""
    lines = [
        "Once a month is enough to see how your investments are doing: prices move every day, and most daily moves "
        "mean nothing for a long-term investor.",
        "The change in worth has two parts: money you added (buys minus sales) and the market's move (everything "
        "else: price changes, fees). Money you add isn't a gain, so it's kept apart.",
        "Dividends are counted in the month of their ex-date, when you became entitled to them, as everywhere in "
        "SGXray. The cash usually arrives a few weeks later.",
    ]
    if r["you"] == r["you"]:
        lines.append("\"Your investments\" is time-weighted: how the stocks themselves did, not counting money you "
                     "added. The STI ETF figure is the same, over the same days, so the two compare fairly.")
    watch = []
    if r["you"] == r["you"] and abs(r["you"]) >= 0.05:
        watch.append("A move of 5% or more in one month is common for shares and REITs. One month says little about "
                     "the years ahead.")
    return Explanation(lines, watch)


def main():
    from fmt import safe_console
    from importer import DEMO_EMAIL
    safe_console()
    conn = db.get_connection()
    db.init_db(conn)
    user = db.get_user_by_email(conn, DEMO_EMAIL)
    if not user:
        return 1
    ms = months(conn, user["id"])
    h = value_history(conn, user["id"])
    m = default_month(ms, h.index[-1].date().isoformat())
    print(summary(conn, user["id"], m))
    print(coming_up(conn, user["id"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
