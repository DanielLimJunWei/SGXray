"""Goals (s16): "$300 of dividends a month" or "$50,000 worth by December 2030", with how far along you are.

Progress is worked out from your trades each time, on the same numbers as the dashboard:
- A dividend goal compares your goal with a year's income divided by 12: what the last 12 months of dividends would
  pay on the shares you hold now (income.yields, "income-12m"). It's last year's payouts, not a promise.
- A worth goal compares it with what you hold, at the latest closing prices (the dashboard's "Worth now"). With a
  date, it also says how much a month the gap is, if you added it yourself and prices didn't move: plain arithmetic,
  never a forecast of returns.

Nothing here suggests what to buy. A goal you've reached says so; it doesn't say to stop or sell.
"""

import math

import db
import sgtime
from explain import Explanation

KINDS = ("dividends", "worth")
MAX_TARGET = {"dividends": 1_000_000, "worth": 100_000_000}
MAX_YEARS = 50


def from_form(form, today=None):
    """(values, problems) from the add-a-goal form."""
    today = today or sgtime.today()
    problems = []
    kind = str(form.get("kind", "")).strip()
    if kind not in KINDS:
        problems.append("Choose what the goal is: dividends a month, or what your portfolio is worth.")
        kind = None
    raw = str(form.get("target", "")).replace(",", "").replace("$", "").strip()[:14]
    target = None
    try:
        target = float(raw)
    except ValueError:
        problems.append("The goal must be an amount in dollars, like 300 or 50,000.")
    if target is not None:
        top = MAX_TARGET.get(kind, MAX_TARGET["worth"])
        if not (target == target and 1 <= target <= top):
            problems.append(f"The goal must be between $1 and ${top:,}.")
            target = None
    by_month = str(form.get("by_month", "")).strip()[:7] or None
    if by_month:
        if kind == "dividends":
            by_month = None                     # dividend goals have no date: the form only offers one for worth
        else:
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


def progress(conn, user_id, today=None):
    """One dict per goal: what it is, where you are now (or a reason in words), and how far along."""
    from income import yields
    from portfolio import positions, summary
    today = today or sgtime.today()
    goals = db.get_goals(conn, user_id)
    if not goals:
        return []
    s = summary(positions(conn, user_id))
    y = yields(conn, user_id)
    a_month = float(y["income_12m"].sum()) / 12 if len(y) else 0.0
    rows = []
    for g in goals:
        row = {"id": g["id"], "kind": g["kind"], "target": g["target"], "by_month": g["by_month"],
               "created_on": g["created_on"], "now": None, "reason": None, "share": None, "gap": None,
               "months_left": None, "per_month": None, "reached": False}
        now = a_month if g["kind"] == "dividends" else s["value"]
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
    if "dividends" in kinds:
        lines.append("A dividend goal is measured by a year's income divided by 12: what the last 12 months of "
                     "dividends would pay on the shares you hold now. Companies pay unevenly (often twice a year), so "
                     "it's an average, and next year's dividends can be higher, lower or none.")
    if "worth" in kinds:
        lines.append("A worth goal is measured by what everything you hold would sell for at the latest closing "
                     "prices. Prices move every day, so this goes up and down even when you add nothing.")
    if any(r["per_month"] for r in rows):
        lines.append("\"About $X a month\" is the gap divided by the months left: what you'd add yourself if prices "
                     "didn't move at all. It isn't a forecast: growth or a fall would change it.")
    watch = []
    if any(r["kind"] == "dividends" and r["share"] is not None and r["share"] < 1 for r in rows):
        watch.append("Chasing a dividend goal with very high-yield stocks is risky: a high yield often means the "
                     "price fell because people expect the dividend to be cut.")
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
