"""News (w312) and today's move vs the STI (w302): safe feeds, accurate matching, headline + source + link only."""

from datetime import datetime, timedelta, timezone

import pytest

import db
import news
import updater
from test_trades import add, app, db_path, downloads, signed_up  # noqa: F401  (fixtures)

SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 12, 15, 0, tzinfo=SGT)
KNOWN = [("D05.SI", "DBS Group Holdings"), ("C6L.SI", "Singapore Airlines Limited"), ("ES3.SI", "SPDR Straits Times Index ETF"),
         ("Z74.SI", "Singapore Telecommunications"), ("K71U.SI", "Keppel REIT")]


def feed(*items, extra=b""):
    body = b"".join(b"<item><title>" + t.encode() + b"</title><link>" + u.encode() + b"</link><pubDate>"
                    + d.encode() + b"</pubDate></item>" for t, u, d in items)
    return b'<?xml version="1.0"?>' + extra + b"<rss><channel>" + body + b"</channel></rss>"


# ---------- Matching ----------

@pytest.mark.parametrize("title, expected", [
    ("SIA's first-half profit falls as fuel costs bite", {"C6L.SI"}),
    ("SIA’s new seats draw praise", {"C6L.SI"}),                    # a curly apostrophe
    ("Singapore Airlines adds flights", {"C6L.SI"}),
    ("Asia stocks slip", set()),                                          # "Asia" contains "sia": no match
    ("Sia the singer tours Singapore", set()),                            # capitals only for short forms
    ("DBS, OCBC or UOB? Investors urged to be selective", {"D05.SI"}),
    ("Singtel shares jump", {"Z74.SI"}),
    ("Singapore shares rise; STI up 0.6%", {"ES3.SI"}),
    ("FTSE ST Index and the STIX fund", set()),                           # "STIX" isn't "STI"
    ("Keppel REIT occupancy holds", {"K71U.SI"}),                          # a looked-up stock: its own name
])
def test_headlines_match_the_right_stocks_and_nothing_else(title, expected):
    assert news.tickers_in(title, KNOWN) == expected


# ---------- Safe parsing ----------

def test_only_https_links_on_the_publishers_own_site_are_kept():
    raw = feed(("Good", "https://www.businesstimes.com.sg/a", "Wed, 12 Nov 2026 01:00:00 GMT"),
               ("Plain http", "http://www.businesstimes.com.sg/b", "Wed, 12 Nov 2026 01:00:00 GMT"),
               ("Elsewhere", "https://evil.example/c", "Wed, 12 Nov 2026 01:00:00 GMT"),
               ("Look-alike", "https://businesstimes.com.sg.evil.example/d", "Wed, 12 Nov 2026 01:00:00 GMT"),
               ("Script link", "javascript:alert(1)", "Wed, 12 Nov 2026 01:00:00 GMT"))
    items = news.parse(raw, "The Business Times", "businesstimes.com.sg", NOW)
    assert [i["title"] for i in items] == ["Good"]
    assert items[0]["published"] == "2026-11-12T09:00"                     # GMT turned into Singapore time


def test_feeds_with_a_doctype_or_entities_are_refused():
    trick = b'<!DOCTYPE lolz [<!ENTITY lol "lol">]>'
    assert news.parse(feed(("x", "https://www.cna.com/a", ""), extra=trick), "CNA", "cna.com", NOW) == []
    assert news.parse(b"not xml at all <", "CNA", "cna.com", NOW) == []


def test_titles_are_cleaned_to_plain_text_and_future_dates_are_capped():
    raw = feed(("DBS &amp; OCBC &lt;b&gt;rise&lt;/b&gt;\n today", "https://www.cna.com/a", "Fri, 01 Jan 2100 00:00:00 GMT"))
    [item] = news.parse(raw, "CNA", "cna.com", NOW)
    assert item["title"] == "DBS & OCBC rise today" and item["published"] == "2026-11-12T15:00"


# ---------- Saving and reading ----------

def test_only_headlines_about_known_stocks_are_kept_once_each(db_path):
    conn = db.get_connection(db_path)
    items = [{"title": "DBS profit rises", "url": "https://www.cna.com/1", "source": "CNA", "published": "2026-11-12T09:00"},
             {"title": "Oil prices fall", "url": "https://www.cna.com/2", "source": "CNA", "published": "2026-11-12T09:00"}]
    assert news.save(conn, items) == 1 and news.save(conn, items) == 0           # the same link isn't added twice
    assert conn.execute("SELECT COUNT(*) FROM news").fetchone()[0] == 1
    conn.close()


def test_recent_headlines_come_newest_first_and_old_ones_are_left_out(db_path):
    conn = db.get_connection(db_path)
    fresh = datetime.now(SGT)
    stamp = lambda days: (fresh - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")
    news.save(conn, [{"title": "DBS one", "url": "https://x.cna.com/1", "source": "CNA", "published": stamp(2)},
                     {"title": "DBS two", "url": "https://x.cna.com/2", "source": "CNA", "published": stamp(1)},
                     {"title": "DBS old", "url": "https://x.cna.com/3", "source": "CNA", "published": stamp(40)}])
    assert [h["title"] for h in news.for_tickers(conn, ["D05.SI"])] == ["DBS two", "DBS one"]   # 30 days
    assert news.for_tickers(conn, ["O39.SI"]) == []
    conn.close()


def test_the_news_check_runs_every_3_hours_and_only_then(db_path):
    conn = db.get_connection(db_path)
    calls = []
    fake = lambda c: calls.append(1) or True
    assert updater.news_once(conn, NOW, fake) == "updated"
    assert updater.news_once(conn, NOW + timedelta(hours=2), fake) == "not due"
    assert updater.news_once(conn, NOW + timedelta(hours=3, minutes=1), fake) == "updated"
    assert len(calls) == 2
    conn.close()


def test_a_failing_feed_never_stops_the_others():
    def fetcher(url):
        return None if "cna" in url else feed(("DBS rises", "https://www.straitstimes.com/a", ""))
    seen = []
    import types
    conn = types.SimpleNamespace()
    orig = news.save
    news.save = lambda c, items: seen.extend(items) or len(items)
    try:
        assert news.update(conn, fetcher) is True
    finally:
        news.save = orig
    assert [i["source"] for i in seen] == ["The Straits Times"]


# ---------- On the page ----------

def test_the_portfolio_shows_headlines_as_safe_links(app, db_path):
    c = signed_up(app)
    add(c)                                                                       # holds DBS
    conn = db.get_connection(db_path)
    db.save_prices(conn, "D05.SI", [("2025-03-04", 31.0)])                         # so DBS gets a price chart
    now = datetime.now(SGT).strftime("%Y-%m-%dT%H:%M")
    news.save(conn, [{"title": 'DBS <script>alert(1)</script> "results"', "url": "https://www.cna.com/a",
                      "source": "CNA", "published": now}])
    conn.close()
    page = c.get("/portfolio").get_data(as_text=True)
    assert 'id="news-title"' in page and "<script>alert(1)</script>" not in page
    assert 'href="https://www.cna.com/a" target="_blank" rel="noopener noreferrer nofollow"' in page
    chart_data = page.split('class="stock-data"')[1].split("</script>")[0]
    assert '"news": [' in chart_data and '"source": "CNA"' in chart_data              # the price chart's markers
    assert "<script>" not in chart_data                                            # escaped inside the data too
    from test_page_rules import check_page_rules
    check_page_rules(page)


def test_no_headlines_says_so(app):
    c = signed_up(app)
    add(c)
    assert "No headlines from the last 30 days mention what you hold" in c.get("/portfolio").get_data(as_text=True)


# ---------- Today's move vs the STI (w302) ----------

def test_the_days_change_shows_the_sti_etfs_move_on_the_same_day(db_path):
    import insights
    from history import value_history
    conn = db.get_connection(db_path)
    uid = db.create_user(conn, "zed@example.com", "x")
    db.save_prices(conn, "D05.SI", [("2025-01-03", 31.0)])
    db.save_prices(conn, "ES3.SI", [("2025-01-03", 30.6)])                       # 30.00 -> 30.60: +2.0%
    db.add_trade(conn, uid, "D05.SI", "2025-01-02", "BUY", 100, 30.0, 0.0)
    d = insights.day_change(conn, uid, value_history(conn, uid))
    conn.close()
    assert d["date"] == "2025-01-03" and abs(d["sti_pct"] - 0.02) < 1e-12
