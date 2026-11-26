"""REIT health (s17): for each REIT you hold, how much it has borrowed, how easily it pays its interest, and how its
payouts per unit have moved.

The borrowing and interest figures are the REIT's OWN, copied by hand from its results announcement, with the date
and a link to the document. Yahoo has debt and asset numbers too, but they don't match what MAS's rules count (MAS's
"aggregate leverage" includes the REIT's share of joint-venture debt; Yahoo's EBIT includes property revaluations),
so a beginner checking a REIT's own report would see two different answers. Checked 26 Nov 2026: Yahoo gives CICT
35.3% where CICT reports 37.4%.

The payouts come from the dividends SGXray already saves every evening.

MAS's rules for every REIT (Code on Collective Investment Schemes, revised 28 Nov 2024): aggregate leverage at most
50%, and an interest coverage ratio (ICR) of at least 1.5 times, with a REIT below 1.8 times having to say what it's
doing about it.

To add a REIT's newest results: append a line to FIGURES (newest last is fine; order doesn't matter), then run
    python src/reits.py            which REITs have figures, how old, and which are probably due an update
"""

import math
from dataclasses import dataclass
from datetime import date

import pandas as pd

import db
import sgtime

LEVERAGE_LIMIT = 50.0        # % (MAS)
LEVERAGE_NEAR = 45.0         # % : within 5 points of the limit, it has little room to borrow more
ICR_MINIMUM = 1.5            # times (MAS)
ICR_DISCLOSE = 1.8           # times (MAS): below this the manager must say how it will improve it
DUE_DAYS = 200               # REITs report within about 2 months of a half-year: older than this, newer are likely out


@dataclass(frozen=True)
class Figures:
    ticker: str
    period_end: str          # 'YYYY-MM-DD': the date the figures are "as at"
    leverage: float          # aggregate leverage, %
    icr: float               # interest coverage ratio, times (trailing 12 months, as the REIT reports it)
    announced: str           # 'YYYY-MM-DD': when the REIT published them
    source: str              # the document's title, as shown to people
    url: str                 # where to read it
    note: str = ""           # anything the REIT itself says makes the figure unusual, in plain words


CICT_1H26 = ("https://www.capitaland.com/content/dam/capitaland-newsroom/International/2026/august/cict-1h-2026/"
             "CICT%201H%202026%20Financial%20Statement.pdf")
MLT_2Q2627 = "https://investor.mapletreelogisticstrust.com/newsroom/20261028_173105_M44U_7E0E1I9HJFI4EQA9.1.pdf"
MPACT_2Q2627 = "https://investor.mapletreepact.com/newsroom/20261030_065806_N2IU_CBSN2B6U7O5VNW21.1.pdf"
CLAR_1H26 = ("https://www.capitaland.com/content/dam/capitaland-newsroom/International/2026/august/clar-1h2026-results/"
             "CLAR%20-%201H%202026%20Unaudited%20FS%20and%20Distribution.pdf")

# Each line was read from the document it links to (the "Aggregate leverage" and "Interest coverage ratio" rows).
# The earlier period comes from the same table's comparison column, so a change can be shown.
FIGURES = [
    Figures("C38U.SI", "2025-12-31", 38.6, 3.7, "2026-08-12", "CICT 1H 2026 financial statement", CICT_1H26),
    Figures("C38U.SI", "2026-06-30", 37.4, 3.9, "2026-08-12", "CICT 1H 2026 financial statement", CICT_1H26),
    Figures("A17U.SI", "2025-12-31", 39.0, 3.6, "2026-08-05", "CapitaLand Ascendas REIT 1H 2026 financial statements",
            CLAR_1H26),
    Figures("A17U.SI", "2026-06-30", 39.7, 3.5, "2026-08-05", "CapitaLand Ascendas REIT 1H 2026 financial statements",
            CLAR_1H26),
    Figures("M44U.SI", "2026-03-31", 40.6, 2.9, "2026-10-28", "Mapletree Logistics Trust 2Q FY26/27 financial statements",
            MLT_2Q2627),
    Figures("M44U.SI", "2026-09-30", 37.5, 2.9, "2026-10-28", "Mapletree Logistics Trust 2Q FY26/27 financial statements",
            MLT_2Q2627, note="Lower for a few weeks only: MLT paid down loans with money raised to redeem older perpetual "
                             "securities in November 2026. Its own figure without that is 40.4%."),
    Figures("N2IU.SI", "2026-03-31", 36.5, 3.2, "2026-10-30",
            "Mapletree Pan Asia Commercial Trust 2Q FY26/27 financial statements", MPACT_2Q2627),
    Figures("N2IU.SI", "2026-09-30", 38.1, 3.3, "2026-10-30",
            "Mapletree Pan Asia Commercial Trust 2Q FY26/27 financial statements", MPACT_2Q2627),
]


def figures_for(ticker, figures=None):
    """(latest, the one before) for a REIT, by period; either can be None."""
    rows = sorted((f for f in (figures if figures is not None else FIGURES) if f.ticker == ticker),
                  key=lambda f: f.period_end)
    return (rows[-1] if rows else None), (rows[-2] if len(rows) > 1 else None)


def _payouts(conn, ticker, as_of):
    """Distributions per unit (restated for any splits) in the 12 months to as_of, and the 12 months before that."""
    from income import trailing_dividends
    now = sum(d["amount"] for d in trailing_dividends(conn, ticker, as_of))
    before_end = (pd.Timestamp(as_of) - pd.DateOffset(years=1)).date().isoformat()
    before = sum(d["amount"] for d in trailing_dividends(conn, ticker, before_end))
    # A REIT that paid nothing in the earlier year (or wasn't listed) has no fair comparison.
    has_history = any(d["ex_date"] <= before_end for d in db.get_dividends(conn, ticker, include_ignored=False))
    return now, (before if has_history and before > 0 else None)


def health(conn, user_id, today=None, figures=None):
    """One dict per REIT you hold now, biggest first. Every value is a number or a reason in words."""
    from portfolio import positions, summary
    today = today or sgtime.today()
    df = positions(conn, user_id)
    if df.empty:
        return []
    kinds = {r["ticker"]: (r["type"], r["name"]) for r in db.get_instruments(conn)}
    held = df[(df["shares"] > 0) & df["ticker"].map(lambda t: kinds.get(t, ("",))[0] == "reit")]
    if held.empty:
        return []
    as_of = summary(df)["prices_as_of"] or today.isoformat()
    out = []
    for _, p in held.sort_values("value", ascending=False, na_position="last").iterrows():
        latest, before = figures_for(p["ticker"], figures)
        now, prior = _payouts(conn, p["ticker"], as_of)
        row = {"ticker": p["ticker"], "name": kinds[p["ticker"]][1], "figures": latest, "before": before,
               "age_days": None, "stale": False, "leverage_room": None, "flags": [],
               "dpu_12m": now, "dpu_prior": prior,
               "dpu_saved": bool(db.get_dividends(conn, p["ticker"], include_ignored=False)),
               "dpu_change": (now / prior - 1) if prior else None}
        if latest:
            row["age_days"] = (today - date.fromisoformat(latest.period_end)).days
            row["stale"] = row["age_days"] > DUE_DAYS
            row["leverage_room"] = LEVERAGE_LIMIT - latest.leverage
            if latest.leverage >= LEVERAGE_NEAR:
                row["flags"].append("near-limit")
            if latest.icr < ICR_MINIMUM:
                row["flags"].append("icr-below-minimum")
            elif latest.icr < ICR_DISCLOSE:
                row["flags"].append("icr-low")
        out.append(row)
    return out


def _period(iso):
    d = date.fromisoformat(iso)
    return f"{d.day} {d:%B %Y}"


def explain(rows):
    """The ⓘ box for REIT health."""
    from explain import Explanation
    lines = [
        "A REIT borrows to buy buildings. Two numbers from its own results show how safely: aggregate leverage "
        f"(what it has borrowed as a share of everything it owns; MAS allows at most {LEVERAGE_LIMIT:.0f}%) and its "
        f"interest coverage ratio (how many times a year's earnings would pay a year's interest; MAS requires at "
        f"least {ICR_MINIMUM} times).",
        "Lower leverage leaves room to borrow for new buildings or to ride out a fall in property values. A higher "
        "interest cover means rising interest rates are less likely to squeeze the payout to you.",
        "These figures are copied from each REIT's own results, with the date. REITs report every 3 or 6 months, so "
        "they can be a few months old; the source link opens the document they came from.",
        "Payouts per unit compare the last 12 months with the 12 months before, from the distributions SGXray has "
        "saved. One payout moving into the other year can shift this a little.",
    ]
    watch = []
    for r in rows:
        f = r["figures"]
        if "near-limit" in r["flags"]:
            watch.append(f"{r['name']}'s leverage is {f.leverage:.1f}%, within {r['leverage_room']:.1f} points of "
                         f"MAS's {LEVERAGE_LIMIT:.0f}% limit: it has little room to borrow more, and a fall in "
                         "property values pushes the figure up.")
        if "icr-below-minimum" in r["flags"]:
            watch.append(f"{r['name']}'s interest cover is {f.icr:.1f} times, below MAS's minimum of "
                         f"{ICR_MINIMUM} times: it can't borrow more until that improves.")
        elif "icr-low" in r["flags"]:
            watch.append(f"{r['name']}'s interest cover is {f.icr:.1f} times, below {ICR_DISCLOSE} times: MAS "
                         "requires the manager to explain how it will improve it.")
        if r["dpu_change"] is not None and r["dpu_change"] <= -0.10:
            watch.append(f"{r['name']} paid {abs(r['dpu_change']):.0%} less a unit over the last 12 months than the "
                         "12 months before. A falling payout is worth reading about in its results.")
    return Explanation(lines, watch)


def due(today=None, held=None, figures=None):
    """For the person who keeps FIGURES up to date: [(ticker, latest or None, age in days or None, due?)]."""
    today = today or sgtime.today()
    out = []
    for t in sorted(set(held or []) | {f.ticker for f in (figures if figures is not None else FIGURES)}):
        latest, _ = figures_for(t, figures)
        age = (today - date.fromisoformat(latest.period_end)).days if latest else None
        out.append((t, latest, age, latest is None or age > DUE_DAYS))
    return out


def main():
    from fmt import safe_console
    safe_console()
    conn = db.get_connection()
    db.init_db(conn)
    reits = [r["ticker"] for r in db.get_instruments(conn) if r["type"] == "reit"]
    print("REIT health figures (src/reits.py). 'DUE' = no figures, or newer results are probably out.\n")
    for t, latest, age, is_due in due(held=reits):
        if latest is None:
            print(f"  {t:9} DUE  no figures entered yet")
        else:
            print(f"  {t:9} {'DUE' if is_due else 'ok '}  as at {_period(latest.period_end)} ({age} days ago): "
                  f"leverage {latest.leverage:.1f}%, ICR {latest.icr:.1f}x  <- {latest.source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
