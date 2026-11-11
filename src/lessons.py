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
    """Everything one lesson's "In the demo" box needs, from the demo portfolio, plus its small film.
    Missing pieces are None, and each lesson then says the demo isn't loaded yet instead of a blank."""
    uid = demo_user_id(conn)
    if uid is None:
        # No demo loaded: only the scams lesson's "3% a month" example works without it.
        return {"scam": scam_compare(None)} if slug == "scams" else {}
    f = {}
    if slug in ("first-dollar", "scams", "risk-and-time"):
        f["dip"] = biggest_dip(conn, uid)
        f["film"] = dip_film(conn, uid, f["dip"])
    if slug == "what-you-own":
        f["owned"] = what_you_own(conn, uid)
        f["split"] = split_film([(h["name"], h["value"], h["type"]) for h in f["owned"]])
    if slug in ("where-shares-live", "fees", "dividends", "risk-and-time"):
        f["sums"] = money_summary(conn, uid)
    if slug in ("where-shares-live", "dividends") and f["sums"]:
        kinds = {r["ticker"]: r["type"] for r in db.get_instruments(conn)}
        f["split"] = split_film([(s["name"], s["dividends"], kinds.get(s["ticker"], "stock"))
                                 for s in f["sums"]["by_stock"]])
    if slug in ("scams", "stocks-vs-market", "reading-sgxray"):
        f["returns"] = returns_summary(conn, uid)
    if slug == "scams":
        f["scam"] = scam_compare(f["returns"])
    if slug == "stocks-vs-market" and f["returns"]:
        f["diffs"] = diff_film(f["returns"]["stocks"])
    if slug == "reading-sgxray":
        f["layers"] = xray_layers(conn, uid)
        if f["layers"]:
            L = f["layers"]
            f["split"] = split_film([("Your own money", L["money"], "money"), ("Price gains", L["gains"], "gains"),
                                     ("Dividends", L["dividends"], "dividends")])
    return f


# ---------- Small "films" for the In the demo boxes (drawn as plain SVG, no script) ----------
# Each is the demo's real data, scaled into a 400 x 80 box. Nothing decorative: if the data isn't there,
# there's no film.

FILM_W, FILM_H, FILM_PAD = 400, 80, 6


def _points(values):
    """Values -> "x,y x,y ..." across the film, highest value at the top."""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    n = len(values)
    out = []
    for i, v in enumerate(values):
        x = FILM_PAD + (FILM_W - 2 * FILM_PAD) * (i / (n - 1) if n > 1 else 0.5)
        y = FILM_PAD + (FILM_H - 2 * FILM_PAD) * (1 - (v - lo) / span)
        out.append((round(x, 1), round(y, 1)))
    return out


def dip_film(conn, user_id, dip, before=21, after=14):
    """The demo's line around its biggest fall: a few weeks before the peak to a little after it climbed
    back. The fall itself is its own piece of line, so the page can colour just that part.
    Returns {"line", "fall", "peak", "low", "label"} or None."""
    if not dip:
        return None
    import datetime as dt
    h = history.value_history(conn, user_id)
    if h is None or h.empty:
        return None
    h = h.dropna(subset=["value"])
    # Stay inside the stretch with no trades around the fall: a buy or sale is money moving, not the
    # market, and drawing its jump would make the film say something untrue.
    stretch = (h["net_invested"] != h["net_invested"].shift()).cumsum()
    at_peak = stretch[h.index.date == dip["peak_day"]]
    if at_peak.empty:
        return None
    same = h[stretch == at_peak.iloc[0]]
    start = max(dip["peak_day"] - dt.timedelta(days=before), same.index[0].date())
    end = min((dip["back_day"] or dip["now_day"]) + dt.timedelta(days=after), same.index[-1].date())
    part = h.loc[str(start):str(end), "value"]
    if len(part) < 3:
        return None
    days = [d.date() for d in part.index]
    pts = _points([float(v) for v in part.values])
    i_peak = days.index(dip["peak_day"]) if dip["peak_day"] in days else 0
    i_low = days.index(dip["low_day"]) if dip["low_day"] in days else len(days) - 1
    as_text = lambda ps: " ".join(f"{x},{y}" for x, y in ps)
    return {"line": as_text(pts), "fall": as_text(pts[i_peak:i_low + 1]), "peak": pts[i_peak], "low": pts[i_low],
            "label": f"The demo's value from {start.day} {start:%B %Y} to {end.day} {end:%B %Y}, falling from "
                     f"${dip['peak']:,.0f} to ${dip['low']:,.0f}"
                     + (f" and back above it by {dip['back_day'].day} {dip['back_day']:%B %Y}" if dip["back_day"] else "")}


def split_film(parts):
    """One bar split by share, like an X-ray of a total: parts = [(label, value, kind), ...].
    kind picks the colour (stock, etf, reit, money, gains, dividends). Returns a list of
    {"x", "w", "kind", "label", "share"}, or None if nothing to split."""
    parts = [p for p in parts if p[1] and p[1] > 0]
    total = sum(p[1] for p in parts)
    if not parts or not total:
        return None
    out, x = [], 0.0
    for label, value, kind in parts:
        w = FILM_W * value / total
        out.append({"x": round(x, 1), "w": round(max(w - 2, 1), 1), "kind": kind, "label": label,
                    "share": value / total})
        x += w
    return out


def diff_film(stocks):
    """Lesson 8: one short bar per stock, up from a middle line if it beat the STI ETF, down if it
    trailed. Returns [{"x", "y", "h", "up", "name", "difference"}] or None."""
    if not stocks:
        return None
    biggest = max(abs(s["difference"]) for s in stocks) or 1.0
    mid, reach = FILM_H / 2, FILM_H / 2 - FILM_PAD
    slot = FILM_W / len(stocks)
    out = []
    for i, s in enumerate(stocks):
        h = max(reach * abs(s["difference"]) / biggest, 1.0)
        up = s["difference"] >= 0
        out.append({"x": round(slot * i + slot * 0.3, 1), "w": round(slot * 0.4, 1),
                    "y": round(mid - h if up else mid, 1), "h": round(h, 1), "up": up,
                    "name": s["name"], "difference": s["difference"]})
    return out
