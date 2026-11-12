"""Regular savings plans (w314): "I invest $X in this stock every month".

This follows how Singapore banks' plans work (POSB Invest-Saver, OCBC Blue Chip Investment Plan, checked
12 Nov 2026):
- A fixed amount is taken once a month on a set day. If that day has no SGX trading (a weekend or holiday),
  the buy happens on the next trading day.
- Only whole shares are bought. The fee is taken first, then as many whole shares as the rest covers; the
  leftover cash isn't invested (POSB refunds it).
- The fee is a percentage of the month's amount, with a minimum (e.g. 0.3% or $5, whichever is higher).
  Banks' fees differ and change, so the person types their own.

SGXray records each month's purchase itself, at that day's real closing price. The bank's own price can differ
by a few cents, so any month's trade can be changed to match the statement. Each month is recorded once
(trades.plan_month), and new months are added when new closing prices arrive (updater.download_all calls
catch_up_all).
"""

import math
from datetime import date

import db

MIN_AMOUNT, MAX_AMOUNT = 1, 100_000


def fee(amount, rate, minimum):
    """One month's fee: the rate on the amount, but never less than the minimum. Rounded to cents."""
    return round(max(amount * rate, minimum), 2)


def buy(amount, price, rate, minimum):
    """(shares, fee) for one month: the fee first, then whole shares only. (0, fee) if one share is too dear."""
    f = fee(amount, rate, minimum)
    return max(0, math.floor((amount - f) / price + 1e-9)), f


def _months(start_month, last_month):
    """'YYYY-MM' strings from start to last, inclusive."""
    y, m = map(int, start_month.split("-"))
    ly, lm = map(int, last_month.split("-"))
    while (y, m) <= (ly, lm):
        yield f"{y:04d}-{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _buy_day(conn, ticker, month, day):
    """(date, close) of the first trading day on or after the plan's day that month, from saved prices,
    or None if that day's close isn't saved yet."""
    target = f"{month}-{day:02d}"
    row = conn.execute("SELECT price_date, close FROM prices WHERE ticker = ? AND price_date >= ? "
                       "ORDER BY price_date LIMIT 1", (ticker, target)).fetchone()
    return (row["price_date"], row["close"]) if row else None


def catch_up(conn, plan):
    """Records every month this plan should have bought but hasn't yet, up to the newest saved close.
    Returns how many trades were added. Months where one share costs more than the amount are skipped."""
    latest = db.get_latest_price_date(conn, plan["ticker"])
    if latest is None:
        return 0
    last_month = min(plan["end_month"] or latest[:7], latest[:7])
    done = {r["plan_month"] for r in conn.execute("SELECT plan_month FROM trades WHERE plan_id = ?", (plan["id"],))}
    added = 0
    for month in _months(plan["start_month"], last_month):
        if month in done:
            continue
        found = _buy_day(conn, plan["ticker"], month, plan["day"])
        if found is None:
            continue                                # that day's close isn't in yet: next time
        day, price = found
        shares, f = buy(plan["amount"], price, plan["fee_rate"], plan["fee_min"])
        if shares == 0:
            continue
        note = f"Monthly plan: ${plan['amount']:,.0f} on the {_ordinal(plan['day'])}"
        with conn:
            conn.execute("INSERT INTO trades (user_id, ticker, trade_date, side, quantity, price, fees, note, "
                         "plan_id, plan_month) VALUES (?, ?, ?, 'BUY', ?, ?, ?, ?, ?, ?)",
                         (plan["user_id"], plan["ticker"], day, shares, price, f, note, plan["id"], month))
        added += 1
    return added


def catch_up_all(conn):
    """Every plan's missing months. Called after each daily price update."""
    return sum(catch_up(conn, p) for p in conn.execute("SELECT * FROM plans").fetchall())


def _ordinal(n):
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def from_form(conn, form, today=None):
    """A new plan from the form: (values, problems). The fee rate is typed as a percentage."""
    today = today or date.today()
    problems = []
    ticker = str(form.get("ticker", "")).strip()[:16]
    if ticker not in {i["ticker"] for i in db.get_instruments(conn)}:
        problems.append("Choose a stock, REIT or ETF from the list.")

    def number(name, label, lo, hi, cast=float):
        raw = str(form.get(name, "")).replace(",", "").replace("$", "").replace("%", "").strip()[:12]
        try:
            v = cast(raw)
        except ValueError:
            problems.append(f"{label} must be a number.")
            return None
        if not lo <= v <= hi:
            problems.append(f"{label} must be between {lo:g} and {hi:,g}.")
            return None
        return v
    amount = number("amount", "The monthly amount", MIN_AMOUNT, MAX_AMOUNT)
    day = number("day", "The buy day", 1, 28, int)
    rate = number("fee_rate", "The fee rate (%)", 0, 5)
    minimum = number("fee_min", "The minimum fee", 0, 100)
    start = str(form.get("start", "")).strip()[:7]
    try:
        y, m = map(int, start.split("-"))
        if not (2000 <= y and 1 <= m <= 12) or (y, m) > (today.year, today.month):
            raise ValueError
    except ValueError:
        problems.append("Choose the month the plan started (this month or earlier).")
    if problems:
        return None, problems
    return {"ticker": ticker, "amount": amount, "day": day, "start_month": f"{y:04d}-{m:02d}",
            "fee_rate": rate / 100, "fee_min": minimum}, []


def add(conn, user_id, v):
    with conn:
        cur = conn.execute("INSERT INTO plans (user_id, ticker, amount, day, start_month, fee_rate, fee_min) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?)", (user_id, v["ticker"], v["amount"], v["day"],
                                                            v["start_month"], v["fee_rate"], v["fee_min"]))
    return cur.lastrowid


def get(conn, user_id, plan_id):
    """One plan, only if it's this person's (someone else's id gives None, like one that doesn't exist)."""
    return conn.execute("SELECT * FROM plans WHERE id = ? AND user_id = ?", (plan_id, user_id)).fetchone()


def for_user(conn, user_id):
    """This person's plans with a summary: months bought, total put in, shares bought."""
    out = []
    for p in conn.execute("SELECT * FROM plans WHERE user_id = ? ORDER BY id", (user_id,)).fetchall():
        t = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(quantity), 0) AS shares, "
                         "COALESCE(SUM(quantity * price + fees), 0) AS paid FROM trades WHERE plan_id = ?",
                         (p["id"],)).fetchone()
        out.append({**dict(p), "months": t["n"], "shares": t["shares"], "paid": t["paid"],
                    "day_words": _ordinal(p["day"])})
    return out


def stop(conn, user_id, plan_id):
    """No more months: it ends at the last month it actually bought (or before it started, if none), so a
    month that hasn't happened yet is never recorded later. Its past trades stay: they really happened."""
    row = conn.execute("SELECT MAX(plan_month) AS m FROM trades WHERE plan_id = ?", (plan_id,)).fetchone()
    with conn:
        cur = conn.execute("UPDATE plans SET end_month = ? WHERE id = ? AND user_id = ? AND end_month IS NULL",
                           (row["m"] or "0000-00", plan_id, user_id))
    return cur.rowcount == 1


def delete(conn, user_id, plan_id):
    """For a plan typed in by mistake: the plan and every trade it recorded (ON DELETE CASCADE)."""
    with conn:
        cur = conn.execute("DELETE FROM plans WHERE id = ? AND user_id = ?", (plan_id, user_id))
    return cur.rowcount == 1
