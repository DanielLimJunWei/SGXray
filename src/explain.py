"""Plain-English explanations of SGXray's numbers: the "What does this mean?" box.

These are written by code from the numbers themselves, not by AI, so they're free, instant
and can never disagree with the table. (The AI box is only for "why did the price move?",
which needs news.)

    python src/explain.py 2024-03        explain the March 2024 row of the monthly table
"""

import sys

import pandas as pd

import db
from history import value_history
from portfolio import dividends_received, trades_frame


def money(x):
    return f"${abs(x):,.2f}"


def up_down(x):
    """'$131.00 up' / '$5.00 down' / 'exactly even'."""
    if round(x, 2) == 0:
        return "exactly even"
    return f"{money(x)} {'up' if x > 0 else 'down'}"


def _day(d):
    return f"{d.day} {d:%B %Y}"                     # 28 March 2024 (no leading zero)


def _reason(from_prices, from_dividends):
    """Why profit changed, in words: price moves and dividends, and how they combined."""
    p, d = round(from_prices, 2), round(from_dividends, 2)
    rose = f"prices rose by {money(p)}"
    fell = f"prices fell by {money(p)}"
    if p and d:
        if p > 0:
            return f"{rose}, and you received {money(d)} in dividends"
        if p + d > 0:
            return f"{fell}, but {money(d)} of dividends more than made up for it"
        return f"{fell}, partly made up for by {money(d)} of dividends"
    if d:
        return f"you received {money(d)} in dividends (prices ended about where they were)"
    return rose if p > 0 else fell


def _trade_sentences(trades, month):
    lines = []
    for t in trades[trades["trade_date"].str[:7] == month].itertuples():
        when = _day(pd.Timestamp(t.trade_date))
        if t.side == "BUY":
            lines.append(f"On {when} you bought {t.quantity:,} {t.ticker} for "
                         f"{money(t.quantity * t.price + t.fees)} (including {money(t.fees)} in fees).")
        else:
            lines.append(f"On {when} you sold {t.quantity:,} {t.ticker} and got back "
                         f"{money(t.quantity * t.price - t.fees)} after fees.")
    return lines


def explain_month(conn, user_id, month, history=None):
    """Sentences explaining one row of the monthly table. month is 'YYYY-MM'.

    Returns a list of short paragraphs, or a one-line message if there's no such row.
    """
    h = history if history is not None else value_history(conn, user_id)
    rows = h[h.index.to_period("M") == pd.Period(month)]
    if rows.empty:
        return [f"There's no snapshot for {month}: it's before your first trade or after the newest price."]
    day, r = rows.index[-1], rows.iloc[-1]
    earlier = h[h.index < rows.index[0]]
    before = earlier.iloc[-1] if not earlier.empty else None

    trades = trades_frame(conn, user_id)
    paid = dividends_received(conn, user_id)
    month_paid = paid[paid["ex_date"].str[:7] == month] if not paid.empty else paid

    out = []
    # 1. What you did this month.
    did = _trade_sentences(trades, month)
    if did:
        out.append(" ".join(did))
    if not month_paid.empty:
        parts = [f"{money(d.total)} from {d.ticker} ({d.shares:,} shares x ${d.amount:g})" for d in month_paid.itertuples()]
        out.append("You earned dividends this month: " + "; ".join(parts) + ".")
    if not did and month_paid.empty:
        out.append("You didn't buy or sell anything this month, and no dividends were due.")

    # 2. The snapshot.
    if r.value != r.value:                                 # NaN: a held stock has no price yet
        out.append(f"The value on {_day(day)} can't be worked out yet: a stock you hold has no saved price.")
        return out
    out.append(f"Money in: you had put {money(r.net_invested)} of your own money into the portfolio by then "
               f"(what you paid for buys, minus what you got back from sales).")
    out.append(f"Value: at the close on {_day(day)}, your shares were worth {money(r.value)}.")
    div_note = f", plus {money(r.dividends)} of dividends received so far" if r.dividends else ""
    out.append(f"Profit: {money(r.value)} worth - {money(r.net_invested)} put in{div_note} "
               f"= {up_down(r.profit)}.")

    # 3. What changed since the last snapshot, and why.
    if before is not None:
        change = r.profit - before.profit
        new_divs = r.dividends - before.dividends
        from_prices = change - new_divs
        if round(change, 2) == 0:
            out.append("Your profit didn't change since last month.")
        else:
            out.append(f"Since last month your profit {'grew' if change > 0 else 'shrank'} by {money(change)}: "
                       f"{_reason(from_prices, new_divs)}.")
        if did:
            out.append("Buying or selling doesn't change your profit by itself: it moves Money in and "
                       "Value by the same amount. Only price moves and dividends change profit.")

    # 4. Against the STI ETF.
    gap = r.profit - r.sti_profit
    out.append(f"STI profit: the same money put into the STI ETF on the same days would have been "
               f"{up_down(r.sti_profit)}. So you were {money(gap)} {'ahead of' if gap >= 0 else 'behind'} the market.")
    return out


def main(argv):
    if len(argv) != 2 or len(argv[1]) != 7:
        print("Usage: python src/explain.py YYYY-MM     e.g. python src/explain.py 2024-03")
        return 1
    from importer import DEMO_EMAIL

    conn = db.get_connection()
    db.init_db(conn)
    user = db.get_user_by_email(conn, DEMO_EMAIL)
    if not user:
        print("No demo portfolio yet. Run: python src/importer.py data/demo_trades.csv")
        return 1
    try:
        lines = explain_month(conn, user["id"], argv[1])
    except ValueError:
        print(f"'{argv[1]}' isn't a month. Use YYYY-MM, e.g. 2024-03")
        return 1
    finally:
        conn.close()
    print("What does this mean?")
    for line in lines:
        print(" -", line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
