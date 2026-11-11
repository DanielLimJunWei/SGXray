"""The "Before you invest" lesson path (w313): the list of lessons, and the demo's real numbers they teach with.

Each lesson's words live in its own template (templates/learn/<slug>.html). The numbers in its "In the demo"
box come from here, worked out live from the demo portfolio by the same code as the dashboard, so a
lesson never goes out of date when prices move.

Education, not advice: no lesson ever says what to buy.
"""

from dataclasses import dataclass

import db
import history
from importer import DEMO_EMAIL
from portfolio import positions


@dataclass(frozen=True)
class Lesson:
    number: int
    slug: str            # its address: /learn/<slug>
    title: str
    idea: str            # the whole lesson in one line, shown on the Learn page and at the top
    minutes: int         # roughly how long it takes to read
    ready: bool          # written yet? Lessons still being written show on the Learn page, not as links


LESSONS = [
    Lesson(1, "first-dollar", "Before your first dollar",
           "Invest only money you won't need for years, after an emergency fund and any expensive debt.", 4, True),
    Lesson(2, "what-you-own", "What you actually own",
           "A share is a small piece of a real business; a REIT is a piece of buildings; an ETF is a basket of many.",
           4, True),
    Lesson(3, "where-shares-live", "Where your shares are kept",
           "A CDP account holds shares in your own name; a custodian account holds them through your broker.", 4, False),
    # Added 11 Nov 2026: investment scams are the biggest danger for Singapore beginners.
    Lesson(4, "scams", "Spotting investment scams",
           "Before you send anyone money, check MAS's directory. Guaranteed high returns and chat-group tips are red flags.",
           4, False),
    Lesson(5, "fees", "What fees really cost",
           "Every trade has fees, and on small trades a minimum fee can cost more than a year of dividends.", 4, False),
    Lesson(6, "dividends", "Dividends",
           "Cash a company pays you for owning it: when you qualify, when it arrives, why it's tax-free in Singapore, "
           "and when a big yield is a warning.", 4, False),
    Lesson(7, "risk-and-time", "Risk and time",
           "Why cash loses value, how growth compounds, and how time, spreading out and investing monthly help you sit "
           "through falls.", 5, False),
    Lesson(8, "stocks-vs-market", "Picking stocks vs buying the market",
           "The STI ETF buys Singapore's 30 biggest companies at once. Your picks have to beat that to be worth it.",
           4, False),
    Lesson(9, "reading-sgxray", "Reading SGXray",
           "What the X-ray chart splits apart, and why SGXray shows two different returns.", 4, False),
]

BY_SLUG = {lesson.slug: lesson for lesson in LESSONS}


def get(slug):
    """The lesson at this address, or None if there isn't one (or it isn't written yet)."""
    lesson = BY_SLUG.get(slug)
    return lesson if lesson and lesson.ready else None


def next_lesson(lesson):
    """The next written lesson after this one, or None at the end of the path."""
    return next((x for x in LESSONS if x.number > lesson.number and x.ready), None)


def demo_user_id(conn):
    user = db.get_user_by_email(conn, DEMO_EMAIL)
    return user["id"] if user else None


# ---------- The demo's numbers, for each lesson's "In the demo" box ----------

def biggest_dip(conn, user_id):
    """The demo's biggest fall in value with no trades in between, so it's the market moving, not money
    going in or out. Returns {"peak_day", "peak", "low_day", "low", "fall", "fall_pct", "days",
    "back_day" (when it climbed back to the peak, or None), "now", "now_day"}, or None without history.

    Lesson 1 uses it: money you'd have needed on the low day would have come out that much smaller.
    """
    h = history.value_history(conn, user_id)
    if h is None or h.empty:
        return None
    h = h.dropna(subset=["value"])
    if h.empty:
        return None
    # A new stretch starts whenever money goes in or comes out (net_invested changes).
    stretch = (h["net_invested"] != h["net_invested"].shift()).cumsum()
    best = None
    for _, part in h.groupby(stretch):
        values = part["value"]
        peak_so_far = values.cummax()
        fall = values / peak_so_far - 1
        low_day = fall.idxmin()
        if best is not None and fall[low_day] >= best["fall_pct"]:
            continue
        peak_day = values.loc[:low_day].idxmax()
        after = values.loc[low_day:]
        back = after[after >= values[peak_day]]
        best = {"peak_day": peak_day.date(), "peak": float(values[peak_day]), "low_day": low_day.date(),
                "low": float(values[low_day]), "fall_pct": float(fall[low_day]),
                "back_day": back.index[0].date() if len(back) else None}
    if best is None or best["fall_pct"] >= 0:
        return None
    best["fall"] = best["peak"] - best["low"]
    best["days"] = (best["low_day"] - best["peak_day"]).days
    best["now"] = float(h["value"].iloc[-1])
    best["now_day"] = h.index[-1].date()
    return best


TYPE_WORDS = {"stock": "Shares in a company", "reit": "A REIT", "etf": "An ETF"}
TYPE_NOUNS = {"stock": "company", "reit": "REIT", "etf": "fund"}


def what_you_own(conn, user_id):
    """The demo's holdings with what kind of thing each one is. Lesson 2 uses it.
    Returns a list of {"ticker", "name", "type", "kind", "noun", "shares", "value", "weight"}, biggest first."""
    df = positions(conn, user_id)
    if df is None or df.empty:
        return []
    info = {r["ticker"]: r for r in db.get_instruments(conn)}
    held = df[df["shares"] > 0].sort_values("value", ascending=False)
    total = held["value"].sum()
    out = []
    for row in held.to_dict("records"):
        i = info.get(row["ticker"])
        kind = i["type"] if i else "stock"
        out.append({"ticker": row["ticker"], "name": i["name"] if i else row["ticker"], "type": kind,
                    "kind": TYPE_WORDS.get(kind, "Shares in a company"), "noun": TYPE_NOUNS.get(kind, "company"), "shares": int(row["shares"]),
                    "value": float(row["value"]), "weight": float(row["value"] / total) if total else 0.0})
    return out
