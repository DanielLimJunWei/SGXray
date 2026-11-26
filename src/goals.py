"""Goals (s16): "Put in $10,000 by December 2027" or "$50,000 worth by December 2030", with how far along you are.

Progress is worked out from your trades each time, on the same numbers as the dashboard:
- A money-in goal compares your goal with your own money in: what you paid for buys (fees included) minus what you
  got back from sales, the X-ray chart's "Your own money" ("money-in"). It's the one goal fully in your hands.
- A worth goal compares it with what you hold, at the latest closing prices (the dashboard's "Worth now").
With a date, either one also says how much a month the gap is: for a worth goal, if you added it yourself and prices
didn't move. Plain arithmetic, never a forecast of returns.

There's no dividend goal (removed 26 Nov 2026): a company decides its own payout, so the only quick way to "work
towards" one is to buy higher-yield stocks, and a very high yield often means a cut is expected.

Nothing here suggests what to buy. A goal you've reached says so; it doesn't say to stop or sell.
"""

import math

import db
import sgtime
from explain import Explanation

KINDS = ("money_in", "worth")
MAX_TARGET = 100_000_000
MAX_YEARS = 50


def from_form(form, today=None):
    """(values, problems) from the add-a-goal form."""
    today = today or sgtime.today()
    problems = []
    kind = str(form.get("kind", "")).strip()
    if kind not in KINDS:
        problems.append("Choose what the goal is: money you put in, or what your portfolio is worth.")
        kind = None
    raw = str(form.get("target", "")).replace(",", "").replace("$", "").strip()[:14]
    target = None
    try:
        target = float(raw)
    except ValueError:
        problems.append("The goal must be an amount in dollars, like 300 or 50,000.")
    if target is not None:
        if not (target == target and 1 <= target <= MAX_TARGET):
            problems.append(f"The goal must be between $1 and ${MAX_TARGET:,}.")
            target = None
    by_month = str(form.get("by_month", "")).strip()[:7] or None
    if by_month:
        try:
            y, m = map(int, by_month.split("-"))
            by_month = f"{y:04d}-{m:02d}"
            last = f"{today.year + MAX_YEARS:04d}-{today.month:02d}"
            if not (1 <= m <= 12 and today.strftime("%Y-%m") < by_month <= last):
                raise ValueError
        except ValueError:
            problems.append(f"The date must be a month after this one, up to {MAX_YEARS} years ahead.")
            by_month = None
    return {"kind": kind, "target": target, "by_month": by_month}, problems


def next_month(today):
    """'YYYY-MM' of the month after `today`: the earliest a dated goal can be for."""
    return f"{today.year + (today.month == 12):04d}-{today.month % 12 + 1:02d}"


def months_until(by_month, today):
    """Whole months from this month to the goal's month: December 2030 from November 2026 = 49."""
    y, m = map(int, by_month.split("-"))
    return (y - today.year) * 12 + (m - today.month)


def money_in(conn, user_id):
    """Your own money in: buys (fees included) minus what sales paid back (after fees), as the X-ray chart counts it.
    Never below $0: selling for more than you put in means you've taken out profit, not put in less than nothing."""
    from portfolio import trades_frame
    t = trades_frame(conn, user_id)
    if t.empty:
        return 0.0
    gross = t["quantity"] * t["price"]
    signed = (gross + t["fees"]).where(t["side"] == "BUY", -(gross - t["fees"]))
    return max(0.0, float(signed.sum()))


def progress(conn, user_id, today=None):
    """One dict per goal: what it is, where you are now (or a reason in words), and how far along."""
    from portfolio import positions, summary
    today = today or sgtime.today()
    goals = db.get_goals(conn, user_id)
    if not goals:
        return []
    kinds = {g["kind"] for g in goals}
    put_in = money_in(conn, user_id) if "money_in" in kinds else None
    worth = summary(positions(conn, user_id))["value"] if "worth" in kinds else None
    rows = []
    for g in goals:
        row = {"id": g["id"], "kind": g["kind"], "target": g["target"], "by_month": g["by_month"],
               "created_on": g["created_on"], "now": None, "reason": None, "share": None, "gap": None,
               "months_left": None, "per_month": None, "reached": False}
        now = put_in if g["kind"] == "money_in" else worth
        if now is None or (isinstance(now, float) and math.isnan(now)):
            row["reason"] = "no-price"                 # a stock you hold has no closing price yet
        else:
            row["now"] = now
            row["share"] = now / g["target"]
            row["reached"] = now >= g["target"]
            row["gap"] = max(0.0, g["target"] - now)
            if g["by_month"] and not row["reached"]:
                left = months_until(g["by_month"], today)
                row["months_left"] = left
                if left > 0:
                    row["per_month"] = row["gap"] / left
        rows.append(row)
    return rows


def explain(rows):
    """The ⓘ box for the goals."""
    lines = ["A goal is yours to set and change: SGXray only measures how far along you are, from your own trades."]
    kinds = {r["kind"] for r in rows}
    if "money_in" in kinds:
        lines.append("A money-in goal is measured by your own money in: what you paid for buys, fees included, minus "
                     "what you got back from sales. Dividends and price rises don't count: it's only what you put in.")
    if "worth" in kinds:
        lines.append("A worth goal is measured by what everything you hold would sell for at the latest closing "
                     "prices. Prices move every day, so this goes up and down even when you add nothing.")
    if any(r["per_month"] for r in rows):
        lines.append("\"About $X a month\" is the gap divided by the months left.")
    if any(r["per_month"] and r["kind"] == "worth" for r in rows):
        lines.append("For a worth goal, that's what you'd add yourself if prices didn't move at all: not a forecast, "
                     "since growth or a fall would change it.")
    watch = []
    if any(r["kind"] == "worth" and r["share"] is not None and r["share"] < 1 for r in rows):
        watch.append("A worth goal also depends on prices, which you don't control: a fall can push it further away "
                     "even while you keep adding. A money-in goal is the part that's fully up to you.")
    return Explanation(lines, watch)


def main():
    from fmt import safe_console
    from importer import DEMO_EMAIL
    safe_console()
    conn = db.get_connection()
    db.init_db(conn)
    user = db.get_user_by_email(conn, DEMO_EMAIL)
    for r in progress(conn, user["id"]) if user else []:
        print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
