"""News headlines (w312): recent headlines that mention the stocks you hold, from credible publishers.

Sources: the public RSS feeds four Singapore newsrooms publish for sharing (checked 12 Nov 2026). Only the
headline as published, the source, the date and a link straight to the full article are kept and shown:
no summaries, no images, no editing, and no ads beside them (Mediacorp's feed terms ask exactly that; the
other publishers' terms weren't found, so the same safe rules apply to all).

Safety: only these fixed addresses are ever fetched (no user-supplied URL, so no SSRF); a size cap and a
time-out; feeds that declare a DOCTYPE or entities are refused (the "billion laughs" XML trick); every
link must be https and on the publisher's own site; headlines are stored as plain text and always shown
escaped.

Matching a headline to a stock uses each stock's names and short forms (ALIASES). Short forms in capitals
(DBS, SIA, STI) only match in capitals, so a word that merely contains them doesn't count.
"""

import html
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import db

SGT = timezone(timedelta(hours=8))
FEEDS = [
    ("CNA", "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6936", "channelnewsasia.com"),
    ("The Business Times", "https://www.businesstimes.com.sg/rss/companies-markets", "businesstimes.com.sg"),
    ("The Straits Times", "https://www.straitstimes.com/news/business/rss.xml", "straitstimes.com"),
    ("The Edge Singapore", "https://www.theedgesingapore.com/rss.xml", "theedgesingapore.com"),
]
MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 10
KEEP_DAYS = 60
USER_AGENT = "SGXray/1.0 (headlines with links to the full article)"

# Names a headline might use for each stock. Words in capitals match only in capitals.
ALIASES = {
    "D05.SI": ["DBS"],
    "O39.SI": ["OCBC"],
    "U11.SI": ["UOB", "United Overseas Bank"],
    "Z74.SI": ["Singtel", "Singapore Telecommunications"],
    "C38U.SI": ["CICT", "CapitaLand Integrated Commercial Trust", "CapitaLand Integrated"],
    "A17U.SI": ["CLAR", "CapitaLand Ascendas Reit", "CapitaLand Ascendas REIT", "Ascendas Reit"],
    "M44U.SI": ["Mapletree Logistics", "MLT"],
    "N2IU.SI": ["Mapletree Pan Asia Commercial", "MPACT"],
    "C6L.SI": ["SIA", "Singapore Airlines"],
    "ES3.SI": ["STI", "Straits Times Index"],
    "G3B.SI": ["STI", "Straits Times Index"],
}
SUFFIXES = re.compile(r"\b(limited|ltd|holdings|group|corporation|corp|inc|plc|reit|trust)\b\.?", re.I)


def aliases_for(ticker, name):
    """Known short forms, or the company's name without "Limited", "Holdings" and the like."""
    if ticker in ALIASES:
        return ALIASES[ticker]
    core = " ".join(SUFFIXES.sub("", name or "").split())
    return [core] if len(core) >= 5 else []           # too short a name would match by accident


def _pattern(alias):
    flags = 0 if alias.isupper() else re.I
    return re.compile(r"(?<![\w-])" + re.escape(alias) + r"(?![\w-])", flags)


def tickers_in(title, instruments):
    """The tickers a headline mentions. instruments: [(ticker, name), ...]."""
    found = set()
    for ticker, name in instruments:
        if any(_pattern(a).search(title) for a in aliases_for(ticker, name)):
            found.add(ticker)
    return found


def _clean(text, limit=300):
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", "", text)                     # a feed title should be plain; strip any tags
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    return " ".join(text.split())[:limit]


def _when(raw, now):
    try:
        d = parsedate_to_datetime(raw)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        d = d.astimezone(SGT)
        return min(d, now).strftime("%Y-%m-%dT%H:%M")       # a date in the future is a feed mistake
    except (TypeError, ValueError, IndexError):
        return now.strftime("%Y-%m-%dT%H:%M")


def parse(xml_bytes, source, domain, now=None):
    """Headlines from one feed: [{"title", "url", "source", "published"}]. Refuses unsafe XML."""
    now = now or datetime.now(SGT)
    if len(xml_bytes) > MAX_BYTES or b"<!DOCTYPE" in xml_bytes.upper() or b"<!ENTITY" in xml_bytes.upper():
        return []
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError:
        return []
    out = []
    for item in root.iter("item"):
        title = _clean(item.findtext("title"))
        url = (item.findtext("link") or "").strip()
        host = re.match(r"^https://([^/?#]+)", url)
        if not title or not host or not (host.group(1) == domain or host.group(1).endswith("." + domain)):
            continue                                           # only https links to the publisher's own site
        out.append({"title": title, "url": url[:500], "source": source,
                    "published": _when(item.findtext("pubDate"), now)})
    return out


def fetch(url):
    """One feed's bytes, at most MAX_BYTES, or None. Only ever called with the fixed FEEDS addresses."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read(MAX_BYTES + 1)
    except Exception:
        return None


def save(conn, items):
    """Stores new headlines that mention a stock SGXray knows (others aren't kept). Returns how many."""
    instruments = [(r["ticker"], r["name"]) for r in db.get_instruments(conn)]
    added = 0
    with conn:
        for it in items:
            tickers = tickers_in(it["title"], instruments)
            if not tickers:
                continue
            cur = conn.execute("INSERT OR IGNORE INTO news (url, title, source, published) VALUES (?, ?, ?, ?)",
                               (it["url"], it["title"], it["source"], it["published"]))
            if cur.rowcount:
                nid = cur.lastrowid
                conn.executemany("INSERT OR IGNORE INTO news_tickers (news_id, ticker) VALUES (?, ?)",
                                 [(nid, t) for t in sorted(tickers)])
                added += 1
        conn.execute("DELETE FROM news WHERE published < ?",
                     ((datetime.now(SGT) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%dT%H:%M"),))
    return added


def update(conn, fetcher=fetch):
    """Fetches every feed and saves the headlines about known stocks. True if at least one feed answered."""
    answered, items = False, []
    for source, url, domain in FEEDS:
        raw = fetcher(url)
        if raw:
            answered = True
            items += parse(raw, source, domain)
    save(conn, items)
    return answered


def for_tickers(conn, tickers, days=30, limit=8):
    """Recent headlines about these stocks, newest first: [{"title", "url", "source", "published", "tickers"}]."""
    tickers = sorted(set(tickers))
    if not tickers:
        return []
    since = (datetime.now(SGT) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")
    marks = ",".join("?" * len(tickers))
    rows = conn.execute(
        f"SELECT n.id, n.title, n.url, n.source, n.published, GROUP_CONCAT(t.ticker) AS tickers "
        f"FROM news n JOIN news_tickers t ON t.news_id = n.id "
        f"WHERE t.ticker IN ({marks}) AND n.published >= ? GROUP BY n.id ORDER BY n.published DESC LIMIT ?",
        (*tickers, since, limit)).fetchall()
    return [{**dict(r), "tickers": sorted(r["tickers"].split(","))} for r in rows]


def for_chart(conn, ticker, start):
    """One stock's headlines from `start` ('YYYY-MM-DD'), oldest first, for its price chart's markers."""
    rows = conn.execute("SELECT n.title, n.url, n.source, substr(n.published, 1, 10) AS date FROM news n "
                        "JOIN news_tickers t ON t.news_id = n.id WHERE t.ticker = ? AND n.published >= ? "
                        "ORDER BY n.published", (ticker, start)).fetchall()
    return [dict(r) for r in rows]
