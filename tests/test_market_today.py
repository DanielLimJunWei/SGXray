"""Market today (/news), story cards, and the charts' data (17 Nov 2026).

News: only headlines that matter to someone investing in Singapore; the same story from two papers shown once;
names that overlap ("Keppel REIT" / "Keppel") matched to the right company; each stock's day move; whether you
own it; topics linked to lessons; the publisher's own summary shown as plain text; nothing personal cached or
shown to anyone else.
"""

from datetime import datetime, timedelta, timezone

import pytest

import db
import news
import stories
from test_practice import buy, text as _text
from test_trades import add, app, db_path, downloads, signed_up  # noqa: F401  (fixtures)

SGT = timezone(timedelta(hours=8))
KNOWN = [("D05.SI", "DBS Group Holdings"), ("K71U.SI", "Keppel REIT"), ("BN4.SI", "Keppel Ltd"),
         ("AJBU.SI", "Keppel DC REIT"), ("BS6.SI", "Yangzijiang Shipbuilding"), ("ES3.SI", "SPDR STI ETF"),
         ("G3B.SI", "Nikko AM Singapore STI ETF")]


def text(r):
    import html
    return html.unescape(_text(r))                    # "don&#39;t" -> "don't"


def now(hours_ago=1):
    return (datetime.now(SGT) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M")


def item(title, url, summary="", source="The Business Times", hours_ago=1):
    return {"title": title, "url": url, "summary": summary, "source": source, "published": now(hours_ago)}


# ---------- Which headlines, and which companies ----------

@pytest.mark.parametrize("title, expected", [
    ("Keppel REIT occupancy holds at 96%", {"K71U.SI"}),               # not Keppel Ltd too
    ("Keppel DC REIT buys a data centre", {"AJBU.SI"}),
    ("Keppel Ltd profit rises", {"BN4.SI"}),
    ("Yangzijiang Maritime eyes profit surge", set()),                 # a different company from the shipbuilder
    ("Yangzijiang Shipbuilding wins orders", {"BS6.SI"}),
    ("STI down 0.9% as Singapore shares fall", {"ES3.SI"}),            # the market: one STI ETF, not both
])
def test_overlapping_names_go_to_the_right_company(title, expected):
    assert news.tickers_in(title, KNOWN) == expected


@pytest.mark.parametrize("title, summary, keep", [
    ("Microsoft bug triggered worldwide outage", "Singapore users were hit too", False),   # Singapore in passing
    ("Nvidia profit beats forecasts", "", False),                     # a topic alone isn't enough
    ("Singapore's key exports surge 79.8%", "", True),
    ("DBS launches a new service", "", True),
    ("Police warn of fake investment scams", "", True),               # scams: always worth knowing
])
def test_only_news_that_matters_to_a_singapore_investor_is_kept(title, summary, keep):
    assert news.relevant(title, summary, news.tickers_in(title, KNOWN)) is keep


@pytest.mark.parametrize("text_, topics", [
    ("DBS declares a 54-cent dividend", ["dividends"]),
    ("OCBC third-quarter results beat estimates", ["results"]),
    ("Fed signals rate cuts ahead", ["rates"]),
    ("I'm fed up with my sti", []),                                   # short forms only in their own capitals
    ("As a result, trading was quiet", []),                           # "a result" isn't company results
    ("MAS warns of a scam using its name", ["scams"]),
])
def test_topics_are_spotted_from_the_words(text_, topics):
    assert news.topics_in(text_) == topics


def test_the_publishers_summary_is_kept_as_plain_text(db_path):
    raw = (b'<?xml version="1.0"?><rss><channel><item><title>DBS profit rises</title>'
           b'<link>https://www.businesstimes.com.sg/a</link><description>&lt;p&gt;Net profit rose &lt;b&gt;9%&lt;/b&gt;'
           b'&lt;script&gt;x&lt;/script&gt;&lt;/p&gt;</description><pubDate>Mon, 16 Nov 2026 01:00:00 GMT</pubDate>'
           b'</item></channel></rss>')
    [it] = news.parse(raw, "The Business Times", "businesstimes.com.sg")
    assert it["summary"] == "Net profit rose 9%x" and "<" not in it["summary"]


def test_the_same_story_from_two_papers_shows_once(db_path):
    conn = db.get_connection(db_path)
    news.save(conn, [item("SIA logs 3.5% rise in traffic", "https://www.businesstimes.com.sg/1", hours_ago=2),
                     item("SIA logs 3.5% rise in traffic", "https://www.straitstimes.com/1", "Passenger numbers rose.",
                          source="The Straits Times", hours_ago=1)])
    [one] = news.recent(conn)
    assert one["also"] == ["The Business Times"] and one["summary"] == "Passenger numbers rose."
    conn.close()


def test_a_named_company_joins_the_list_so_its_prices_come(db_path):
    conn = db.get_connection(db_path)
    news.save(conn, [item("Seatrium wins another contract", "https://www.theedgesingapore.com/1",
                          source="The Edge Singapore")])
    assert any(r["ticker"] == "5E2.SI" for r in db.get_instruments(conn))
    assert "5E2.SI" in news.recent_tickers(conn)
    conn.close()


def test_retag_applies_a_corrected_name_list_to_older_headlines(db_path):
    conn = db.get_connection(db_path)
    news.save(conn, [item("DBS profit rises", "https://www.businesstimes.com.sg/1")])
    conn.execute("INSERT INTO news (url, title, source, published) VALUES ('https://www.cna.com/x', "
                 "'US airline outage', 'CNA', ?)", (now(),))
    conn.commit()
    news.retag(conn)
    assert [r["title"] for r in news.recent(conn)] == ["DBS profit rises"]           # the irrelevant one is gone
    conn.close()


def test_day_move_is_from_the_previous_close_and_says_which_way(db_path):
    conn = db.get_connection(db_path)
    assert news.day_move(conn, "U11.SI") is None                                      # no price at all
    db.save_prices(conn, "U11.SI", [("2026-11-13", 40.0)])
    assert news.day_move(conn, "U11.SI")["pct"] is None                               # one close: no move yet
    db.save_prices(conn, "U11.SI", [("2026-11-16", 39.84)])
    m = news.day_move(conn, "U11.SI")
    assert m["pct"] == pytest.approx(-0.004) and m["way"] == "down" and m["date"] == "2026-11-16"   # 0.4% is a move
    conn.close()


# ---------- The page ----------

def test_market_today_is_open_to_everyone_and_explains_itself(app, db_path):
    conn = db.get_connection(db_path)
    news.save(conn, [item("DBS declares a dividend", "https://www.businesstimes.com.sg/1", "A bigger payout."),
                     item("Singapore's exports rise", "https://www.straitstimes.com/2", source="The Straits Times")])
    conn.close()
    r = app.test_client().get("/news")
    page = text(r)
    assert r.status_code == 200 and "Market today" in page and "What does this mean?" in page
    assert "Companies in the news" in page and "Singapore's market and economy" in page
    assert "About your stocks" not in page                                           # logged out: nothing personal
    assert "lesson 6, Dividends" in page and "The Business Times sums it up" in page
    assert 'href="https://www.businesstimes.com.sg/1" target="_blank" rel="noopener noreferrer nofollow"' in r.get_data(as_text=True)


def test_logged_in_your_stocks_come_first_and_say_you_own_them(app, db_path):
    c = signed_up(app)
    add(c)                                                                            # 100 DBS
    buy(c)                                                                            # and 100 in practice
    conn = db.get_connection(db_path)
    news.save(conn, [item("DBS profit rises", "https://www.businesstimes.com.sg/1"),
                     item("UOB opens a branch", "https://www.businesstimes.com.sg/2")])
    conn.close()
    r = c.get("/news")
    page = text(r)
    assert page.index("About your stocks") < page.index("DBS profit rises") < page.index("Other companies in the news")
    assert "You own 100 shares" in page and "practice: 100 shares" in page and "You don't own this" in page
    assert r.headers["Cache-Control"] == "no-store"                                  # personal: never cached
    mine = text(c.get("/news?show=mine"))
    assert "DBS profit rises" in mine and "UOB opens a branch" not in mine


def test_nobody_sees_someone_elses_holdings_on_the_news(app, db_path):
    ann = signed_up(app)
    add(ann)
    conn = db.get_connection(db_path)
    news.save(conn, [item("DBS profit rises", "https://www.businesstimes.com.sg/1")])
    conn.close()
    bob = signed_up(app, "bob@example.com")
    page = text(bob.get("/news"))
    assert "You own 100 shares" not in page and "You don't own this" in page
    assert "About your stocks" in text(bob.get("/news?show=mine"))


def test_headline_html_never_runs(app, db_path):
    conn = db.get_connection(db_path)
    news.save(conn, [item('DBS <img src=x onerror=alert(1)> "rises"', "https://www.businesstimes.com.sg/1",
                          "<script>alert(2)</script>")])
    conn.close()
    page = app.test_client().get("/news").get_data(as_text=True)
    assert "<img src=x" not in page and "<script>alert(2)" not in page


def test_the_portfolio_news_opens_into_story_cards_with_the_move(app, db_path):
    c = signed_up(app)
    add(c)
    conn = db.get_connection(db_path)
    db.save_prices(conn, "D05.SI", [("2025-01-03", 31.5)])                           # +5% on the day
    news.save(conn, [item("DBS profit rises", "https://www.businesstimes.com.sg/1")])
    conn.close()
    page = text(c.get("/portfolio"))
    assert "DBS profit rises" in page and "▲ up 5.0%" in page and "You own 100 shares" in page
    assert "See all of today's market news" in page


def test_empty_news_says_why(app):
    page = text(app.test_client().get("/news"))
    assert "No company has been named in a headline yet" in page
    assert "No market or economy headlines in the last 3 days yet" in page


def test_holdings_counts_shares_and_weight(db_path, app):
    c = signed_up(app)
    add(c)
    conn = db.get_connection(db_path)
    uid = db.get_user_by_email(conn, "ann@example.com")["id"]
    assert stories.holdings(conn, uid) == {"D05.SI": {"shares": 100, "weight": pytest.approx(1.0)}}
    assert stories.holdings(conn, None) == {}
    conn.close()


# ---------- The X-ray chart's data: daily while the history is short ----------

def test_a_short_history_gives_a_point_for_every_trading_day(app, db_path):
    import app as web
    from history import value_history
    c = signed_up(app)
    add(c, date="2025-01-02", price="30")
    conn = db.get_connection(db_path)
    db.save_prices(conn, "D05.SI", [("2025-01-03", 31.0), ("2025-01-06", 32.0)])
    db.save_prices(conn, "ES3.SI", [("2025-01-03", 30.0), ("2025-01-06", 30.0)])
    uid = db.get_user_by_email(conn, "ann@example.com")["id"]
    rows = web._monthly_chart(value_history(conn, uid))
    conn.close()
    assert len(rows) >= 3 and {r["unit"] for r in rows} == {"day"}                   # not one lonely month-end dot
    assert rows[0]["label"] == "2 Jan"


# ---------- 17 Nov follow-ups: types explained, one "Learn", news in pages ----------



def test_portfolio_news_comes_in_pages_of_5(app, db_path):
    c = signed_up(app)
    add(c)
    conn = db.get_connection(db_path)
    news.save(conn, [item(f"DBS story number {i}", f"https://www.businesstimes.com.sg/{i}", hours_ago=i + 1)
                     for i in range(12)])
    conn.close()
    page = c.get("/portfolio").get_data(as_text=True)
    assert 'id="portfolio-news" data-per-page="5"' in page and "news-pages.js" in page
    assert page.count("DBS story number") == 12                                      # all sent: the script pages them


def test_headlines_that_differ_only_in_numbers_are_different_stories(db_path):
    conn = db.get_connection(db_path)
    news.save(conn, [item("Singapore shares rise; STI up 0.6%", "https://www.businesstimes.com.sg/a", hours_ago=30),
                     item("Singapore shares rise; STI up 1.1%", "https://www.businesstimes.com.sg/b", hours_ago=2)])
    assert len(news.recent(conn)) == 2
    conn.close()


def test_each_market_today_section_pages_on_its_own(app, db_path):
    c = signed_up(app)
    add(c)
    conn = db.get_connection(db_path)
    news.save(conn, [item(f"Singapore exports report {i}", f"https://www.straitstimes.com/{i}", hours_ago=i + 1)
                     for i in range(8)])
    conn.close()
    page = c.get("/news").get_data(as_text=True)
    for name in ("mine", "others", "market"):
        assert f'id="news-{name}" data-per-page="5"' in page or name != "market"
    assert "news-pages.js" in page and page.count("Singapore exports report") == 8
