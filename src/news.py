"""News (w312, and the Market today page): Singapore business headlines from credible publishers, and which
SGX companies and investing topics each one is about.

Sources: the public RSS feeds four Singapore newsrooms publish for sharing (checked 12 Nov 2026, again
17 Nov 2026). Kept and shown: the headline as published, the publisher's own one-line standfirst from
the feed (credited to them, never edited or rewritten), the source, the date and a link straight to the
full article. No images, no AI summaries, no ads beside them (Mediacorp's feed terms ask exactly that; the
other publishers' terms weren't found, so the same safe rules apply to all).
Checked and NOT added (17 Nov 2026): MAS has no RSS feed and its terms forbid republishing without written
permission; TODAY's feed didn't answer; SGX publishes no public announcements feed.

Only headlines that matter to someone investing in Singapore are kept: ones that name an SGX company, are
about Singapore's market or economy, or warn about scams. A story about a US airline's IT outage is left out.
Each kept headline is also tagged with the investing topics it touches (dividends, results, rates...), and
each topic links to the lesson that explains it.

Safety: only the fixed FEEDS addresses are ever fetched (no user-supplied URL, so no SSRF); a size cap and
a time-out; feeds that declare a DOCTYPE or entities are refused (the "billion laughs" XML trick); every
link must be https and on the publisher's own site; text is stored plain and always shown escaped.

Matching a headline to a stock uses each stock's names and short forms. Short forms in capitals (DBS, SIA,
STI) only match in capitals, so a word that merely contains them doesn't count. When two names overlap
("Keppel REIT" contains "Keppel"), only the longer one counts, so Keppel REIT news isn't Keppel Ltd news.
"""

import html
import re
import urllib.request
from collections import Counter
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
SOURCES = [f[0] for f in FEEDS]
MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 10
KEEP_DAYS = 60
SUMMARY_MAX = 400                 # the publisher's standfirst is a sentence or two; anything longer is cut
USER_AGENT = "SGXray/1.0 (headlines with links to the full article)"

# Names a headline might use for the starter stocks. Words in capitals match only in capitals.
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
    "G3B.SI": ["Nikko AM Singapore STI ETF", "Nikko AM STI ETF"],    # "STI" alone means the market: ES3 stands for it
}

# Other big SGX companies the news often names (Straits Times Index members and well-known REITs, all traded
# in Singapore dollars). When a kept headline names one, it's added to SGXray's list of stocks, so its daily
# closing price is downloaded and the Market today page can show how it moved. (ticker, name, type, sector, aliases)
NEWS_COMPANIES = [
    ("C6L.SI", "Singapore Airlines", "stock", "Airlines", ["SIA", "Singapore Airlines"]),
    ("S68.SI", "Singapore Exchange", "stock", "Financial services", ["SGX Group", "Singapore Exchange"]),
    ("BN4.SI", "Keppel Ltd", "stock", "Conglomerate", ["Keppel Ltd", "Keppel Corp", "Keppel Corporation"]),
    ("S63.SI", "ST Engineering", "stock", "Industrials", ["ST Engineering", "ST Engg", "Singapore Technologies Engineering"]),
    ("U96.SI", "Sembcorp Industries", "stock", "Utilities", ["Sembcorp Industries", "Sembcorp"]),
    ("5E2.SI", "Seatrium", "stock", "Industrials", ["Seatrium"]),
    ("BS6.SI", "Yangzijiang Shipbuilding", "stock", "Industrials", ["Yangzijiang Shipbuilding", "YZJ Shipbuilding"]),
    ("Y92.SI", "Thai Beverage", "stock", "Food and drink", ["Thai Beverage", "ThaiBev"]),
    ("F34.SI", "Wilmar International", "stock", "Food and drink", ["Wilmar"]),
    ("G13.SI", "Genting Singapore", "stock", "Leisure", ["Genting Singapore"]),
    ("C09.SI", "City Developments", "stock", "Property", ["City Developments", "CDL"]),
    ("U14.SI", "UOL Group", "stock", "Property", ["UOL"]),
    ("9CI.SI", "CapitaLand Investment", "stock", "Property", ["CapitaLand Investment", "CLI"]),
    ("V03.SI", "Venture Corporation", "stock", "Technology", ["Venture Corp", "Venture Corporation"]),
    ("S58.SI", "SATS", "stock", "Industrials", ["SATS"]),
    ("C07.SI", "Jardine Cycle & Carriage", "stock", "Conglomerate", ["Jardine Cycle & Carriage", "Jardine C&C", "JC&C"]),
    ("ME8U.SI", "Mapletree Industrial Trust", "reit", "Industrial", ["Mapletree Industrial Trust", "Mapletree Industrial"]),
    ("BUOU.SI", "Frasers Logistics & Commercial Trust", "reit", "Logistics", ["Frasers Logistics", "FLCT"]),
    ("J69U.SI", "Frasers Centrepoint Trust", "reit", "Retail and office", ["Frasers Centrepoint Trust", "FCT"]),
    ("AJBU.SI", "Keppel DC REIT", "reit", "Data centres", ["Keppel DC Reit", "Keppel DC REIT"]),
    ("K71U.SI", "Keppel REIT", "reit", "Retail and office", ["Keppel Reit", "Keppel REIT"]),
    ("HMN.SI", "CapitaLand Ascott Trust", "reit", "Hospitality", ["CapitaLand Ascott Trust", "CLAS"]),
    ("T82U.SI", "Suntec REIT", "reit", "Retail and office", ["Suntec Reit", "Suntec REIT"]),
]
NEWS_ALIASES = {t: aliases for t, _, _, _, aliases in NEWS_COMPANIES}

SUFFIXES = re.compile(r"\b(limited|ltd|holdings|group|corporation|corp|inc|plc|reit|trust)\b\.?", re.I)

# Investing topics, each linked to the lesson that explains it (agreed 17 Nov 2026). A headline can have
# several. key: (label shown, pattern, [lesson slugs])
TOPICS = {
    "results": ("Company results", r"\b(results|earnings|profits?|net income|revenue|quarter|Q[1-4]|half-year|"
                r"H[12]|full-year|first-half|second-half)\b", ["risk-and-time"]),
    "dividends": ("Dividends", r"\b(dividends?|distributions?|DPU|payouts?)\b", ["dividends"]),
    "rates": ("Interest rates", r"\b(rate cuts?|rate hikes?|interest rates?|Fed|Federal Reserve|MAS policy|"
              r"monetary policy|SORA)\b", ["risk-and-time"]),
    "market": ("The Singapore market", r"\b(STI|Straits Times Index|Singapore (shares|stocks|equities)|SGX)\b",
               ["stocks-vs-market"]),
    "reits": ("REITs", r"\b(S-REITs?|REITs?|real estate investment trusts?|rental|occupancy)\b", ["what-you-own"]),
    "scams": ("Scams and warnings", r"\b(scams?|scammers?|fraud|investor alert|MAS warns?|Ponzi)\b", ["scams"]),
    "fees": ("Fees and brokers", r"\b(brokerages?|brokers?|fees?|CDP|trading platforms?|commissions?)\b",
             ["where-shares-live", "fees"]),
    "listings": ("New listings", r"\b(IPOs?|listings?|debuts?|to list|lists on)\b", ["what-you-own"]),
}
# The word-only topics need these exact capitals (Fed, STI, SGX, DPU...): the rest match in any case.
_CASED = {"Fed", "STI", "SGX", "DPU", "SORA", "CDP", "IPO", "IPOs", "MAS", "Q1", "Q2", "Q3", "Q4", "H1", "H2"}
TOPIC_PATTERNS = {k: re.compile(p, re.I) for k, (_, p, _) in TOPICS.items()}
# Singapore's market and economy, for headlines that name no company and no topic.
SINGAPORE = re.compile(r"\b(Singapore|SGX|STI|MAS|S-REITs?|CPF|SGS bonds?|Straits Times Index)\b")


def aliases_for(ticker, name):
    """Known short forms, or the company's name without "Limited", "Holdings" and the like."""
    if ticker in ALIASES:
        return ALIASES[ticker]
    if ticker in NEWS_ALIASES:
        return NEWS_ALIASES[ticker]
    core = " ".join(SUFFIXES.sub("", name or "").split())
    return [core] if len(core) >= 5 else []           # too short a name would match by accident


def _pattern(alias):
    flags = 0 if alias.isupper() or "&" in alias else re.I
    return re.compile(r"(?<![\w-])" + re.escape(alias) + r"(?![\w-])", flags)


def tickers_in(text, instruments):
    """The tickers a headline mentions. instruments: [(ticker, name), ...].

    Where names overlap, the longer wins: "Keppel REIT" is Keppel REIT, not also Keppel Ltd."""
    hits = []                                            # (start, end, ticker)
    for ticker, name in instruments:
        for a in aliases_for(ticker, name):
            hits += [(m.start(), m.end(), ticker) for m in _pattern(a).finditer(text)]
    hits.sort(key=lambda h: (-(h[1] - h[0]), h[0]))     # longest first
    taken, found = [], set()
    for start, end, ticker in hits:
        inside = any(s <= start and end <= e and t != ticker for s, e, t in taken)
        if not inside:
            found.add(ticker)
        taken.append((start, end, ticker))
    return found


_CASED_UPPER = {w.upper() for w in _CASED}


def topics_in(text):
    """The investing topics a headline (and its standfirst) is about: a list of TOPICS keys, in TOPICS order.
    Short forms count only in their own capitals: "fed up" isn't the Fed, "Sti" isn't the STI."""
    found = []
    for key, pattern in TOPIC_PATTERNS.items():
        for m in pattern.finditer(text or ""):
            word = m.group(0)
            if word.upper() in _CASED_UPPER and word not in _CASED:
                continue
            found.append(key)
            break
    return found


def relevant(title, summary, tickers):
    """Worth keeping for someone investing in Singapore: the headline names an SGX company or Singapore's market
    or economy, or the story warns about scams. A topic on its own isn't enough ("Nvidia's profit" is about
    results, but not about anything a Singapore beginner owns), and neither is Singapore turning up only in the
    standfirst (a US chip story that mentions Singapore once in passing)."""
    return bool(tickers) or bool(SINGAPORE.search(title)) or "scams" in topics_in(f"{title} {summary or ''}")


def _clean(text, limit=300):
    text = html.unescape(text or "")
    text = re.sub(r"<(script|style)\b.*?(</\1\s*>|$)", " ", text, flags=re.I | re.S)   # code is never text
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
    """Headlines from one feed: [{"title", "summary", "url", "source", "published"}]. Refuses unsafe XML."""
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
        summary = tidy_summary(item.findtext("description"))
        out.append({"title": title, "summary": "" if summary == title else summary, "url": url[:500],
                    "source": source, "published": _when(item.findtext("pubDate"), now)})
    return out


def fetch(url):
    """One feed's bytes, at most MAX_BYTES, or None. Only ever called with the fixed FEEDS addresses."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read(MAX_BYTES + 1)
    except Exception:
        return None


def _known(conn):
    """[(ticker, name)] for matching: SGXray's stocks plus the big companies the news often names."""
    known = {r["ticker"]: r["name"] for r in db.get_instruments(conn)}
    for ticker, name, *_ in NEWS_COMPANIES:
        known.setdefault(ticker, name)
    return list(known.items())


def save(conn, items):
    """Stores new headlines that matter to an investor in Singapore (see `relevant`). Returns how many.
    A company from NEWS_COMPANIES named in a kept headline joins SGXray's list of stocks, so its prices come."""
    instruments = _known(conn)
    listed = {r["ticker"] for r in db.get_instruments(conn)}
    extra = {t: (n, ty, se) for t, n, ty, se, _ in NEWS_COMPANIES}
    added = 0
    with conn:
        for it in items:
            summary = it.get("summary", "")
            tickers = tickers_in(it["title"], instruments)        # the headline only: a name in passing isn't the story
            if not relevant(it["title"], summary, tickers):
                continue
            cur = conn.execute("INSERT OR IGNORE INTO news (url, title, summary, source, published) "
                               "VALUES (?, ?, ?, ?, ?)",
                               (it["url"], it["title"], summary or None, it["source"], it["published"]))
            if cur.rowcount:
                nid = cur.lastrowid
                for t in sorted(tickers - listed):
                    if t in extra:
                        conn.execute("INSERT OR IGNORE INTO instruments (ticker, name, type, sector) VALUES (?, ?, ?, ?)",
                                     (t, *extra[t]))
                        listed.add(t)
                conn.executemany("INSERT OR IGNORE INTO news_tickers (news_id, ticker) VALUES (?, ?)",
                                 [(nid, t) for t in sorted(tickers)])
                added += 1
        conn.execute("DELETE FROM news WHERE published < ?",
                     ((datetime.now(SGT) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%dT%H:%M"),))
    return added


def update(conn, fetcher=fetch, page_fetcher=None):
    """Fetches every feed and saves the headlines that matter, then fills in summaries the feeds left out.
    True if at least one feed answered."""
    answered, items = False, []
    for source, url, domain in FEEDS:
        raw = fetcher(url)
        if raw:
            answered = True
            items += parse(raw, source, domain)
    save(conn, items)
    retag(conn)
    fill_summaries(conn, page_fetcher or fetch_page)
    return answered


# ---------- Summaries the feeds leave out ----------
# CNA's feed has no standfirst, and some headlines in the others don't either. Every article page carries the
# publisher's own one-line description for link previews (what WhatsApp or Telegram shows when the link is
# shared): SGXray reads that, once per article, and shows it credited to the publisher, exactly like a feed's.
# Only article links already saved from FEEDS are fetched, re-checked to be https on that publisher's own site.

PAGE_MAX = 600_000             # the description is in the page's <head>, near the top
SUMMARIES_PER_RUN = 40         # a 3-hourly run fills at most this many, newest first
_META = [re.compile(p, re.I | re.S) for p in (
    r"<meta[^>]+(?:property|name)=[\"'](?:og:description|description|twitter:description)[\"'][^>]*content=[\"']([^\"']*)",
    r"<meta[^>]+content=[\"']([^\"']*)[\"'][^>]*(?:property|name)=[\"'](?:og:description|description|twitter:description)[\"']",
)]


def tidy_summary(text):
    """A publisher's summary as one plain line: no tags, no "[SINGAPORE]" dateline tag, no "Read more at ..."."""
    text = _clean(text, SUMMARY_MAX * 2)
    text = re.sub(r"\s*Read more at\s.*$", "", text, flags=re.I)
    text = re.sub(r"^\[[A-Z ]{2,30}\]\s*", "", text)
    text = re.split(r"\(function\s*\(|\bvar\s+\w+\s*=|window\.\w+|document\.\w+", text)[0]   # leftover script
    return text[:SUMMARY_MAX].strip()


def summary_from_page(page):
    """The page's own description for link previews, tidied; "" if it has none."""
    head = page[:PAGE_MAX]
    for pattern in _META:
        m = pattern.search(head)
        if m and m.group(1).strip():
            return tidy_summary(m.group(1))
    return ""


def _publisher_link(url):
    host = re.match(r"^https://([^/?#]+)/", url or "")
    return bool(host) and any(host.group(1) == d or host.group(1).endswith("." + d) for _, _, d in FEEDS)


def fetch_page(url):
    """One article page as text, at most PAGE_MAX bytes, or None. Only for saved links on a publisher's site."""
    if not _publisher_link(url):
        return None
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            if not _publisher_link(r.geturl()):           # redirected somewhere else: not used
                return None
            return r.read(PAGE_MAX).decode("utf-8", "replace")
    except Exception:
        return None


def fill_summaries(conn, fetcher=fetch_page, limit=SUMMARIES_PER_RUN):
    """Reads the description of up to `limit` saved headlines that have no summary yet, newest first. A page with
    none is marked "" (tried), so it isn't fetched again. Returns how many summaries were found."""
    rows = conn.execute("SELECT id, url FROM news WHERE summary IS NULL ORDER BY published DESC LIMIT ?",
                        (limit,)).fetchall()
    found = 0
    for r in rows:
        page = fetcher(r["url"]) if _publisher_link(r["url"]) else None
        if page is None:
            continue                                     # couldn't reach it: try again next run
        text = summary_from_page(page)
        found += bool(text)
        with conn:
            conn.execute("UPDATE news SET summary = ? WHERE id = ?", (text, r["id"]))
    return found


def retag(conn):
    """Matches every saved headline again with today's name list, so a corrected or added name applies to
    older headlines too, and drops any that no longer matter. A few hundred short titles: quick."""
    instruments = _known(conn)
    with conn:
        for r in conn.execute("SELECT id, title, summary FROM news").fetchall():
            tickers = tickers_in(r["title"], instruments)
            if not relevant(r["title"], r["summary"], tickers):
                conn.execute("DELETE FROM news WHERE id = ?", (r["id"],))
                continue
            have = {x["ticker"] for x in conn.execute("SELECT ticker FROM news_tickers WHERE news_id = ?", (r["id"],))}
            if have != tickers:
                conn.execute("DELETE FROM news_tickers WHERE news_id = ?", (r["id"],))
                conn.executemany("INSERT INTO news_tickers (news_id, ticker) VALUES (?, ?)",
                                 [(r["id"], t) for t in sorted(tickers)])


def _since(days):
    return (datetime.now(SGT) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")


def _same(title):
    """A headline reduced to its words and numbers, to spot the same story from two papers (The Business Times
    and The Straits Times often carry the same one). Numbers count: "STI up 0.6%" today and "STI up 1.1%"
    tomorrow are different stories, so they're never merged (a headline re-sent with a fixed number shows twice)."""
    words = re.sub(r"[^a-z0-9.% ]+", " ", title.lower().replace("’", "'")).split()
    return " ".join(words)


def _rows(conn, where, args, limit):
    rows = conn.execute(
        "SELECT n.id, n.title, n.summary, n.url, n.source, n.published, GROUP_CONCAT(t.ticker) AS tickers "
        "FROM news n LEFT JOIN news_tickers t ON t.news_id = n.id "
        f"WHERE {where} GROUP BY n.id ORDER BY n.published DESC, n.id DESC LIMIT ?", (*args, limit * 2)).fetchall()
    out, seen = [], {}
    for r in rows:
        key = _same(r["title"])
        if key in seen:                                   # the same story again: name the other paper on the first
            first = seen[key]
            if r["source"] != first["source"] and r["source"] not in first["also"]:
                first["also"].append(r["source"])
            if not first["summary"] and r["summary"]:
                first["summary"], first["summary_source"] = r["summary"], r["source"]
            continue
        item = {**dict(r), "tickers": sorted(r["tickers"].split(",")) if r["tickers"] else [], "also": []}
        item["summary"] = tidy_summary(item["summary"]) if item["summary"] else ""   # older rows, tidied too
        item["summary_source"] = item["source"]
        seen[key] = item
        out.append(item)
    for item in out:
        item["topics"] = topics_in(f"{item['title']} {item['summary']}")
    return out[:limit]


def for_tickers(conn, tickers, days=30, limit=8):
    """Recent headlines about these stocks, newest first: [{"title", "summary", "url", "source", "published",
    "tickers", "topics"}]. "tickers" lists every stock the headline names, not only these."""
    tickers = sorted(set(tickers))
    if not tickers:
        return []
    marks = ",".join("?" * len(tickers))
    return _rows(conn, f"n.published >= ? AND n.id IN (SELECT news_id FROM news_tickers WHERE ticker IN ({marks}))",
                 (_since(days), *tickers), limit)


def recent(conn, days=3, limit=60):
    """Every kept headline from the last few days, newest first (the Market today page)."""
    return _rows(conn, "n.published >= ?", (_since(days),), limit)


def most_mentioned(items, limit=5):
    """The companies named in the most of these headlines: [(ticker, count)], most first. A headline naming
    a company twice counts once; the STI and its ETFs aren't companies, so they're left out."""
    counts = Counter(t for it in items for t in set(it["tickers"]) if t not in ("ES3.SI", "G3B.SI"))
    return counts.most_common(limit)


def recent_tickers(conn, days=7):
    """Stocks named in the last week's headlines: their prices are downloaded too, so the day's move shows."""
    rows = conn.execute("SELECT DISTINCT t.ticker FROM news_tickers t JOIN news n ON n.id = t.news_id "
                        "WHERE n.published >= ?", (_since(days),)).fetchall()
    listed = {r["ticker"] for r in db.get_instruments(conn)}
    return sorted(r["ticker"] for r in rows if r["ticker"] in listed)


def day_move(conn, ticker):
    """How the stock moved on its latest trading day: {"pct", "date", "close"} from the previous close to the
    latest one, {"pct": None, "date", "close"} with only one close saved, or None with none."""
    rows = conn.execute("SELECT price_date, close FROM prices WHERE ticker = ? ORDER BY price_date DESC LIMIT 2",
                        (ticker,)).fetchall()
    if not rows:
        return None
    pct = rows[0]["close"] / rows[1]["close"] - 1 if len(rows) == 2 else None
    # Up or down as soon as it shows as at least 0.1% (what's printed), so a 0.4% fall never reads "unchanged".
    way = "" if pct is None or abs(pct) < 0.0005 else ("up" if pct > 0 else "down")
    return {"pct": pct, "way": way, "date": rows[0]["price_date"], "close": rows[0]["close"]}


def last_checked(conn):
    """When the feeds last answered ('YYYY-MM-DDTHH:MM:SS+08:00'), or None if never."""
    try:
        row = conn.execute("SELECT last_ok FROM jobs WHERE name = 'news'").fetchone()
    except Exception:                                    # no jobs table yet: never checked
        return None
    return row["last_ok"] if row else None
