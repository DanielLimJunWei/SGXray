"""Story cards on the Market today page: each headline as a row (topic tag, headline, source, how long ago,
ticker chips with the day's move, and a small chart of the stock's last month), opening into the card below
(no AI, nothing rewritten).

A card puts the facts SGXray already has next to the publisher's own words:
- the publisher's own one-line summary (from its feed, or its article page's link-preview text), credited
- every SGX company the story names: its move on its latest trading day, and whether you own it (how many
  shares, and how much of your portfolio that is) or not
- the investing topics it touches, each linked to the lesson that explains it
- a link to the full story on the publisher's own site

Nothing here judges the news as good or bad, or says what to do: those ratings are often wrong and soon read like tips.
"""

from datetime import datetime

import db
import lessons
import news
from portfolio import positions


def holdings(conn, user_id):
    """{ticker: {"shares", "weight"}} for what this user holds now (weight = share of the portfolio's worth;
    None when a price is missing). {} for no user or no holdings."""
    if not user_id:
        return {}
    df = positions(conn, user_id)
    if df is None or df.empty:
        return {}
    held = df[df["shares"] > 0]
    total = held["value"].sum()
    out = {}
    for row in held.itertuples():
        weight = row.value / total if total and row.value == row.value and total == total else None
        out[row.ticker] = {"shares": int(row.shares), "weight": weight}
    return out


def _topic(key):
    label, _, slugs = news.TOPICS[key]
    return {"key": key, "label": label,
            "lessons": [{"slug": s, "number": lessons.BY_SLUG[s].number, "title": lessons.BY_SLUG[s].title,
                         "at": news.TOPIC_SPOTS.get((key, s), "")} for s in slugs]}


THUMB_DAYS = 22                 # about a month of trading days in each row's little chart
THUMB_W, THUMB_H = 112, 64


def ago(published, now):
    """'2026-11-17T08:33' -> '13m ago', '4h ago', 'Yesterday' or '15 Nov': how long ago, like a news app."""
    try:
        then = datetime.strptime(published, "%Y-%m-%dT%H:%M").replace(tzinfo=now.tzinfo)
    except (TypeError, ValueError):
        return ""
    mins = max(0, int((now - then).total_seconds() // 60))
    if mins < 60:
        return f"{max(1, mins)}m ago"
    if mins < 24 * 60:
        return f"{mins // 60}h ago"
    if (now.date() - then.date()).days == 1:
        return "Yesterday"
    return f"{then.day} {then:%b}"


def sparkline(conn, ticker):
    """The row's picture: {"code", "path", "area", "way", "change", "days", "end"} for the stock's last month of closes, drawn
    from SGXray's own saved prices (no publisher photos), or None with fewer than 2 closes."""
    rows = conn.execute("SELECT close FROM prices WHERE ticker = ? ORDER BY price_date DESC LIMIT ?",
                        (ticker, THUMB_DAYS)).fetchall()
    closes = [r["close"] for r in reversed(rows)]
    if len(closes) < 2:
        return None
    lo, hi = min(closes), max(closes)
    span = (hi - lo) or 1
    pad_x, top, bottom = 6, 24, THUMB_H - 8              # room at the top for the ticker and the month's change
    xs = [pad_x + (THUMB_W - 2 * pad_x) * i / (len(closes) - 1) for i in range(len(closes))]
    ys = [bottom - (bottom - top) * (c - lo) / span for c in closes]
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f} {y:.1f}" for i, (x, y) in enumerate(zip(xs, ys)))
    change = closes[-1] / closes[0] - 1
    way = "" if abs(change) < 0.0005 else ("up" if change > 0 else "down")
    return {"code": ticker.removesuffix(".SI"), "path": path, "area": f"{path} L{xs[-1]:.1f} {bottom} L{xs[0]:.1f} {bottom} Z",
            "way": way, "change": change, "days": len(closes), "end": (xs[-1], ys[-1])}


CHART_DAYS = 66                 # about three months of trading days in a card's chart


def closes(conn, ticker, days=CHART_DAYS):
    """[["YYYY-MM-DD", close], ...] oldest first: the card chart's data, from SGXray's own saved prices."""
    rows = conn.execute("SELECT price_date, close FROM prices WHERE ticker = ? ORDER BY price_date DESC LIMIT ?",
                        (ticker, days)).fetchall()
    return [[r["price_date"], round(r["close"], 4)] for r in reversed(rows)]


def build(conn, items, owned, practice=None, now=None):
    """Adds what a story card needs to each headline: "stocks" and "topic_list". owned: holdings() of the
    portfolio being looked at; practice: the same for the practice portfolio, or None."""
    names = {r["ticker"]: r["name"] for r in db.get_instruments(conn)}
    names.update({t: n for t, n, *_ in news.NEWS_COMPANIES if t not in names})
    moves, thumbs, charts = {}, {}, {}
    now = now or datetime.now(news.SGT)
    for it in items:
        stocks = []
        for t in it["tickers"]:
            if t not in moves:
                moves[t] = news.day_move(conn, t)
            stocks.append({"ticker": t, "code": t.removesuffix(".SI"), "name": names.get(t, t), "move": moves[t],
                           "owned": owned.get(t), "practice": (practice or {}).get(t)})
        # Yours first, then the rest by name: the card starts with what matters to you.
        stocks.sort(key=lambda s: (s["owned"] is None, s["name"].lower()))
        it["stocks"] = stocks
        it["topic_list"] = [_topic(k) for k in it["topics"]]
        it["tag"] = it["topic_list"][0]["label"] if it["topic_list"] else ""
        it["ago"] = ago(it["published"], now)
        # The picture: your own stock first, else the first company named; a market story shows the STI ETF.
        pick = next((s["ticker"] for s in stocks if s["owned"]), None) or next(
            (s["ticker"] for s in stocks if s["ticker"] not in STI_ETFS), None) or (
            "ES3.SI" if stocks or "market" in it["topics"] else None)
        if pick and pick not in thumbs:
            thumbs[pick] = sparkline(conn, pick)
            charts[pick] = closes(conn, pick)
        it["thumb"] = thumbs.get(pick) if pick else None
        # The card's bigger chart (static/js/news-chart.js): three months, with the story's own day marked.
        it["chart"] = ({"code": pick.removesuffix(".SI"), "name": names.get(pick, pick), "prices": charts[pick],
                        "story_day": it["published"][:10]} if pick and it["thumb"] else None)
    return items


def split(items, owned):
    """(about yours, other companies, market and economy) for the Market today page. A headline that only
    names the STI (tagged as the STI ETFs) is market news, unless you hold an STI ETF."""
    mine, others, market = [], [], []
    for it in items:
        if any(t in owned for t in it["tickers"]):
            mine.append(it)
        elif any(t not in STI_ETFS for t in it["tickers"]):
            others.append(it)
        else:
            market.append(it)
    return mine, others, market


STI_ETFS = ("ES3.SI", "G3B.SI")
