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
from portfolio import positions, summary


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
           "A CDP account holds shares in your own name; a custodian account holds them through your broker.", 4, True),
    # Added 11 Nov 2026: investment scams are the biggest danger for Singapore beginners.
    Lesson(4, "scams", "Spotting investment scams",
           "Before you send anyone money, check MAS's directory. Guaranteed high returns and chat-group tips are red flags.",
           4, True),
    Lesson(5, "fees", "What fees really cost",
           "Every trade has fees, and on small trades a minimum fee can cost more than a year of dividends.", 4, True),
    Lesson(6, "dividends", "Dividends",
           "Cash a company pays you for owning it: when you qualify, when it arrives, why it's tax-free in Singapore, "
           "and when a big yield is a warning.", 4, True),
    Lesson(7, "risk-and-time", "Risk and time",
           "Why cash loses value, how growth compounds, and how time, spreading out and investing monthly help you sit "
           "through falls.", 5, True),
    Lesson(8, "stocks-vs-market", "Picking stocks vs buying the market",
           "The STI ETF buys Singapore's 30 biggest companies at once. Your picks have to beat that to be worth it.",
           4, True),
    Lesson(9, "reading-sgxray", "Reading SGXray",
           "What the X-ray chart splits apart, and why SGXray shows two different returns.", 4, True),
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


def _safe(fn, *args):
    """Runs fn; None if it can't (e.g. no STI ETF prices yet raises ValueError), so a lesson shows its
    "not loaded yet" sentence instead of crashing."""
    try:
        return fn(*args)
    except (ValueError, ZeroDivisionError):
        return None


def money_summary(conn, user_id):
    """The demo's totals: what went in, what it's worth, fees, dividends. Used by lessons 3, 5 and 6.
    Returns None without trades."""
    df = positions(conn, user_id)
    trades = db.get_trades(conn, user_id)
    if df is None or df.empty or not trades:
        return None
    buys = [t for t in trades if t["side"] == "BUY"]
    bought = sum(t["quantity"] * t["price"] for t in buys)
    fees = float(df["fees"].sum())
    names = {r["ticker"]: r["name"] for r in db.get_instruments(conn)}
    by_stock = [{"ticker": r["ticker"], "name": names.get(r["ticker"], r["ticker"]), "dividends": float(r["dividends"])}
                for r in df.sort_values("dividends", ascending=False).to_dict("records") if r["dividends"] > 0]
    smallest = min(buys, key=lambda t: t["quantity"] * t["price"]) if buys else None
    return {"trades": len(trades), "buys": len(buys), "bought": bought, "fees": fees,
            "fees_pct": fees / bought if bought else 0.0,
            "fee_each": fees / len(trades) if trades else 0.0,
            "dividends": float(df["dividends"].sum()), "by_stock": by_stock,
            "profit": float(summary(df)["total_profit"]),
            "first_day": trades[0]["trade_date"], "last_buy": buys[-1]["trade_date"] if buys else None,
            "value": float(df["value"].sum()),
            "smallest": ({"amount": smallest["quantity"] * smallest["price"], "fees": float(smallest["fees"]),
                          "name": names.get(smallest["ticker"], smallest["ticker"]), "day": smallest["trade_date"]}
                         if smallest else None)}


def returns_summary(conn, user_id):
    """The demo's returns next to the STI ETF's, both ways (money-weighted and time-weighted), and stock by
    stock. Used by lessons 4, 8 and 9. Returns None without enough history or STI ETF prices."""
    from history import time_weighted
    from performance import compare, per_stock
    c = _safe(compare, conn, user_id)
    if not c or c.get("too_short") or c["you"] != c["you"]:
        return None
    t = _safe(time_weighted, conn, user_id)
    names = {r["ticker"]: r["name"] for r in db.get_instruments(conn)}
    ps = _safe(per_stock, conn, user_id)
    stocks = []
    if ps is not None and not ps.empty:
        for r in ps.to_dict("records"):
            if r.get("too_short"):
                continue
            stocks.append({"ticker": r["ticker"], "name": names.get(r["ticker"], r["ticker"]),
                           "your_profit": float(r["your_profit"]), "sti_profit": float(r["sti_profit"]),
                           "difference": float(r["difference"]), "verdict": r["verdict"]})
    return {"you": float(c["you"]), "sti": float(c["benchmark"]), "yearly": bool(c["yearly"]), "days": int(c["days"]),
            "your_value": float(c["your_value"]), "sti_value": float(c["benchmark_value"] + c["benchmark_dividends"]),
            "your_profit": float(c["your_profit"]), "sti_profit": float(c["benchmark_profit"]),
            "twr": float(t["you_year"]) if t and t.get("yearly") else None,
            "twr_sti": float(t["sti_year"]) if t and t.get("yearly") else None,
            "stocks": stocks}


def xray_layers(conn, user_id):
    """The X-ray chart's last month, split into its layers: your money, price gains, dividends, and the
    same money in the STI ETF. Lesson 9 uses it. None without history."""
    h = history.value_history(conn, user_id)
    if h is None or h.empty:
        return None
    h = h.dropna(subset=["value"])
    if h.empty:
        return None
    last = h.iloc[-1]
    sti = last["sti_value"] + last["sti_dividends"]
    return {"day": h.index[-1].date(), "money": float(last["net_invested"]),
            "gains": float(last["value"] - last["net_invested"]), "dividends": float(last["dividends"]),
            "total": float(last["value"] + last["dividends"]), "sti": float(sti) if sti == sti else None}


def scam_compare(returns):
    """A scam's "3% a month, guaranteed" next to what the demo really made. Lesson 4."""
    monthly = 0.03
    yearly = (1 + monthly) ** 12 - 1
    out = {"monthly": monthly, "yearly": yearly, "on_10k": 10_000 * (1 + yearly)}
    if returns:
        out["demo"] = returns["you"]
        out["sti"] = returns["sti"]
    return out


def facts_for(conn, slug):
    """Everything one lesson's "In the demo" box needs, from the demo portfolio. Missing pieces are None,
    and each lesson then says the demo isn't loaded yet instead of showing a blank."""
    uid = demo_user_id(conn)
    if uid is None:
        # No demo loaded: only the scams lesson's "3% a month" example works without it.
        return {"scam": scam_compare(None)} if slug == "scams" else {}
    if slug == "first-dollar":
        return {"dip": biggest_dip(conn, uid)}
    if slug == "what-you-own":
        return {"owned": what_you_own(conn, uid)}
    if slug in ("where-shares-live", "fees", "dividends"):
        return {"sums": money_summary(conn, uid)}
    if slug == "scams":
        r = returns_summary(conn, uid)
        return {"scam": scam_compare(r), "returns": r, "dip": biggest_dip(conn, uid)}
    if slug == "risk-and-time":
        return {"dip": biggest_dip(conn, uid), "sums": money_summary(conn, uid)}
    if slug == "stocks-vs-market":
        return {"returns": returns_summary(conn, uid)}
    if slug == "reading-sgxray":
        return {"returns": returns_summary(conn, uid), "layers": xray_layers(conn, uid)}
    return {}
