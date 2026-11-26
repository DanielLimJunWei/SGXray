"""The watchlist (s14): stocks you're researching, with the facts a beginner should look at before buying, and no
advice. Each row: the latest close, how it has moved since you added it, where it sits in its 52-week range, its
dividend yield over the last 12 months, and whether you already own some.

Every value is either a number or a reason in words (the page rule): "no-price" before the first close is saved,
"no-move-yet" when the price you added it at is still the latest one, "too-soon" for a range with under a month of
prices. Nothing here suggests buying or selling.

    python src/watchlist.py            (the demo account's watchlist, if it has one)
"""

import pandas as pd

import db
from explain import Explanation, _day
from fmt import money
from income import trailing_dividends
from insights import week52
from portfolio import positions


def _close_on_or_before(conn, ticker, day):
    """(date, close) of the newest saved close on or before `day`, or None."""
    row = conn.execute("SELECT price_date, close FROM prices WHERE ticker = ? AND price_date <= ? "
                       "ORDER BY price_date DESC LIMIT 1", (ticker, day)).fetchone()
    return (row["price_date"], row["close"]) if row else None


def rows(conn, user_id):
    """One dict per watched stock, earliest added first."""
    names = {r["ticker"]: r["name"] for r in db.get_instruments(conn)}
    held = positions(conn, user_id)
    owned = {r.ticker: int(r.shares) for r in held.itertuples() if r.shares > 0} if not held.empty else {}
    out = []
    for w in db.get_watchlist(conn, user_id):
        t = w["ticker"]
        latest_day = db.get_latest_price_date(conn, t)
        row = {"ticker": t, "name": names.get(t, ""), "added_on": w["added_on"], "note": w["note"] or "",
               "owned": owned.get(t, 0), "close": None, "close_date": None, "since": None, "since_from": None,
               "since_reason": None, "range": None, "range_reason": None, "yield": None, "per_share_12m": 0.0,
               "payouts_12m": 0, "next_ex": None}
        if latest_day is None:
            row.update(since_reason="no-price", range_reason="no-price")
            out.append(row)
            continue
        close = db.get_prices(conn, t, start=latest_day)[0]["close"]
        row.update(close=close, close_date=latest_day)
        # Since you added it: from the close of the day you added it (or the last one before, if you added it on
        # a weekend or before that day's close was saved) to the latest close.
        base = _close_on_or_before(conn, t, w["added_on"])
        if base is None:                                      # prices only start after the day you added it
            base = (latest_day, close) if latest_day == w["added_on"] else None
        if base is None or base[0] == latest_day:
            row["since_reason"] = "no-move-yet"
        else:
            # A split or bonus issue in between: one share then is `factor` shares now, so compare like with like
            # (a 1-for-10 bonus drops the price about 9% without anyone losing money).
            factor = 1.0
            for a in db.get_actions(conn, t):
                if base[0] < a["ex_date"] <= latest_day:
                    factor *= a["factor"]
            row.update(since=close * factor / base[1] - 1, since_from=base[0])
        r = week52(conn, t, latest_day)
        if r is None:
            row["range_reason"] = "too-soon"
        else:
            row["range"] = r
        upcoming = db.get_announced(conn, t, latest_day)
        row["next_ex"] = upcoming[0] if upcoming else None
        divs = trailing_dividends(conn, t, latest_day)
        per_share = sum(d["amount"] for d in divs)
        row.update(per_share_12m=per_share, payouts_12m=len(divs), **{"yield": per_share / close if close else None})
        out.append(row)
    return out


def explain(rows_):
    """The "What does this mean?" box for the watchlist."""
    if not rows_:
        return Explanation(["Your watchlist is empty. Add a stock you're curious about to keep an eye on it "
                            "before deciding anything: SGXray shows its price, how it has moved since you added it, "
                            "its year's range and its dividends."])
    lines = [
        "These are stocks you're watching, not necessarily ones you own (under each name it says if you do). Nothing here is "
        "a recommendation: it's what to look at before you decide for yourself.",
    ]
    moved = [r for r in rows_ if r["since"] is not None]
    if moved:
        r = max(moved, key=lambda x: abs(x["since"]))
        lines.append(f"Since you added it on {_day(pd.Timestamp(r['added_on']))}, {r['ticker']} has gone "
                     f"{'up' if r['since'] >= 0 else 'down'} {abs(r['since']):.1%} (closing prices, "
                     f"{_day(pd.Timestamp(r['since_from']))} to {_day(pd.Timestamp(r['close_date']))}). "
                     "A short move says little about a company: prices wobble every day.")
    ranged = [r for r in rows_ if r["range"]]
    if ranged:
        r = ranged[0]
        g = r["range"]
        lines.append(f"The 52-week range shows the lowest and highest close over the last year. {r['ticker']} has "
                     f"closed between ${g['low']:,.3f} and ${g['high']:,.3f}, and is now {g['position']:.0%} of the way "
                     "from the low to the high. Near the low isn't automatically cheap, and near the high isn't "
                     "automatically expensive.")
    paying = [r for r in rows_ if r["yield"]]
    if paying:
        r = paying[0]
        lines.append(f"Dividend yield is the last 12 months of dividends divided by today's price: {r['ticker']} paid "
                     f"${r['per_share_12m']:g} a share over {r['payouts_12m']} payout{'s' if r['payouts_12m'] != 1 else ''}, "
                     f"{r['yield']:.2%} of its {money(r['close'])} price. Future dividends can be higher, lower or none.")
    watch = ["A watchlist is for learning about a company before you buy, not for timing the market. Read what the "
             "company does, how it makes money and why the price moved, not just the numbers here."]
    high = [r for r in rows_ if r["yield"] and r["yield"] > 0.08]
    if high:
        watch.append(f"{', '.join(r['ticker'] for r in high)}: a yield above 8% often means the price has fallen "
                     "because people expect the dividend to be cut. Check why before counting on it.")
    return Explanation(lines, watch)


def main():
    from fmt import safe_console
    from importer import DEMO_EMAIL
    safe_console()
    conn = db.get_connection()
    db.init_db(conn)
    user = db.get_user_by_email(conn, DEMO_EMAIL)
    if not user:
        print("No demo account yet.")
        return 1
    for r in rows(conn, user["id"]):
        print(r["ticker"], r["close"], r["since"], r["since_reason"], r["range_reason"], r["yield"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
