"""Story cards: what opens when you click a headline, on the Market today page and in a portfolio's
"In the news" (no AI, nothing rewritten).

A card puts the facts SGXray already has next to the publisher's own words:
- the publisher's one-line standfirst from its feed, credited to it (or a note that it gave none)
- every SGX company the story names: its move on its latest trading day, and whether you own it (how many
  shares, and how much of your portfolio that is) or not
- the investing topics it touches, each linked to the lesson that explains it
- a link to the full story on the publisher's own site

Nothing here judges the news as good or bad, or says what to do: see explain_market_today for why.
"""

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
            "lessons": [{"slug": s, "number": lessons.BY_SLUG[s].number, "title": lessons.BY_SLUG[s].title}
                        for s in slugs]}


def build(conn, items, owned, practice=None):
    """Adds what a story card needs to each headline: "stocks" and "topic_list". owned: holdings() of the
    portfolio being looked at; practice: the same for the practice portfolio, or None."""
    names = {r["ticker"]: r["name"] for r in db.get_instruments(conn)}
    names.update({t: n for t, n, *_ in news.NEWS_COMPANIES if t not in names})
    moves = {}
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
