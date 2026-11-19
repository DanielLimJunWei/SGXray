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
    assert it["summary"] == "Net profit rose 9%" and "<" not in it["summary"]     # the script's text is gone too


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


# ---------- The page: one feed with tabs, story rows, nothing personal unless logged in ----------

def test_market_today_is_open_to_everyone_as_one_feed(app, db_path):
    conn = db.get_connection(db_path)
    news.save(conn, [item("DBS declares a dividend", "https://www.businesstimes.com.sg/1", "A bigger payout.", hours_ago=3),
                     item("Singapore's exports rise", "https://www.straitstimes.com/2", source="The Straits Times")])
    conn.close()
    r = app.test_client().get("/news")
    page, raw = text(r), r.get_data(as_text=True)
    assert r.status_code == 200 and "Market today" in page
    assert page.index("Singapore's exports rise") < page.index("DBS declares a dividend")     # newest first
    assert "Other companies" in page and "Market & economy" in page
    assert "Your stocks" not in page                                                 # logged out: nothing personal
    assert "lesson 6, Dividends" in page and "A bigger payout." in page
    assert "3h ago" in page and 'class="story-tag"' in raw
    assert 'href="https://www.businesstimes.com.sg/1" target="_blank" rel="noopener noreferrer nofollow"' in raw
    assert 'popovertarget="market-what"' not in raw and "term-news-topic" not in raw   # no explanation prompts


def test_tabs_filter_the_feed_and_ignore_anything_else(app, db_path):
    c = signed_up(app)
    add(c)                                                                            # 100 DBS
    conn = db.get_connection(db_path)
    news.save(conn, [item("DBS profit rises", "https://www.businesstimes.com.sg/1"),
                     item("UOB opens a branch", "https://www.businesstimes.com.sg/2"),
                     item("Singapore's exports rise", "https://www.straitstimes.com/3", source="The Straits Times")])
    conn.close()
    feed = lambda r: r.get_data(as_text=True).split('class="market-feed"')[1].split('class="market-side"')[0]
    mine, others, market = (feed(c.get(f"/news?show={k}")) for k in ("mine", "others", "market"))
    assert "DBS profit rises" in mine and "UOB opens" not in mine and "exports rise" not in mine
    assert "UOB opens a branch" in others and "DBS profit" not in others
    assert "exports rise" in market and "DBS profit" not in market
    weird = feed(c.get("/news?show=<script>"))                                        # an unknown tab: everything
    assert "DBS profit rises" in weird and "UOB opens a branch" in weird
    assert "UOB opens a branch" in feed(app.test_client().get("/news?show=mine"))   # logged out: no "mine" tab


def test_your_stocks_say_you_own_them_and_link_to_your_portfolio(app, db_path):
    c = signed_up(app)
    add(c)                                                                            # 100 DBS
    buy(c)                                                                            # and 100 in practice
    conn = db.get_connection(db_path)
    news.save(conn, [item("DBS profit rises", "https://www.businesstimes.com.sg/1"),
                     item("UOB opens a branch", "https://www.businesstimes.com.sg/2")])
    conn.close()
    r = c.get("/news")
    page, raw = text(r), r.get_data(as_text=True)
    assert "You own 100 shares" in page and "practice: 100 shares" in page and "You don't own this" in page
    assert '<a href="/portfolio#holdings-title">You own 100 shares' in raw
    assert 'class="chip mine" href="/portfolio#holdings-title"' in raw                # "yours" in Most in the news
    glance = page.split("Most in the news")[1].split("How many stories named each company")[0]
    assert "1 story" in glance and "headline" not in glance
    assert r.headers["Cache-Control"] == "no-store"                                  # personal: never cached


def test_nobody_sees_someone_elses_holdings_on_the_news(app, db_path):
    ann = signed_up(app)
    add(ann)
    conn = db.get_connection(db_path)
    news.save(conn, [item("DBS profit rises", "https://www.businesstimes.com.sg/1")])
    conn.close()
    bob = signed_up(app, "bob@example.com")
    page = text(bob.get("/news"))
    assert "You own 100 shares" not in page and "You don't own this" in page
    assert "You don't hold any stocks yet" in text(bob.get("/news?show=mine"))


def test_headline_html_never_runs(app, db_path):
    conn = db.get_connection(db_path)
    news.save(conn, [item('DBS <img src=x onerror=alert(1)> "rises"', "https://www.businesstimes.com.sg/1",
                          "<script>alert(2)</script>")])
    conn.close()
    page = app.test_client().get("/news").get_data(as_text=True)
    assert "<img src=x" not in page and "<script>alert(2)" not in page and "alert(2)" not in page


def test_each_row_shows_the_stocks_last_month_from_saved_prices(app, db_path):
    conn = db.get_connection(db_path)
    db.save_prices(conn, "D05.SI", [("2025-01-03", 31.0), ("2025-01-06", 33.0)])
    news.save(conn, [item("DBS profit rises", "https://www.businesstimes.com.sg/1")])
    conn.close()
    raw = app.test_client().get("/news").get_data(as_text=True)
    assert 'class="story-thumb thumb-up"' in raw and "1M +10.0%" in raw              # $30 -> $33
    assert "<img" not in raw.split('id="news-feed"')[1]                              # never a publisher's photo


def test_the_portfolio_has_no_news_section_any_more(app, db_path):
    c = signed_up(app)
    add(c)
    conn = db.get_connection(db_path)
    news.save(conn, [item("DBS profit rises", "https://www.businesstimes.com.sg/1")])
    conn.close()
    for path in ("/portfolio", "/demo", "/practice"):
        page = c.get(path).get_data(as_text=True)
        assert 'id="news-title"' not in page and "DBS profit rises" not in page.split('class="stock-data"')[0]


def test_empty_news_says_why(app):
    page = text(app.test_client().get("/news"))
    assert "No company has been named in a story yet" in page
    assert "No stories since " in page and " yet. They arrive with the next check." in page
    assert "No market or economy stories" in text(app.test_client().get("/news?show=market"))


def test_ago_reads_like_a_news_app():
    n = datetime(2026, 11, 17, 16, 0, tzinfo=SGT)
    assert [stories.ago(x, n) for x in ("2026-11-17T15:47", "2026-11-17T08:33", "2026-11-16T09:00",
                                        "2026-11-14T09:00", "nonsense")] == ["13m ago", "7h ago", "Yesterday", "14 Nov", ""]


# ---------- Summaries the feeds leave out: the article page's own link-preview text ----------

def test_missing_summaries_come_from_the_article_page_once(db_path):
    conn = db.get_connection(db_path)
    news.save(conn, [item("DBS profit rises", "https://www.businesstimes.com.sg/1"),
                     item("UOB opens a branch", "https://www.businesstimes.com.sg/2")])
    pages = {"https://www.businesstimes.com.sg/1":
             '<head><meta property="og:description" content="[SINGAPORE] Profit rose 9% on fees. Read more at The Business Times."></head>',
             "https://www.businesstimes.com.sg/2": "<head><title>No description here</title></head>"}
    calls = []
    fetch = lambda url: calls.append(url) or pages[url]
    assert news.fill_summaries(conn, fetch) == 1
    got = {r["title"]: r["summary"] for r in news.recent(conn)}
    assert got == {"DBS profit rises": "Profit rose 9% on fees.", "UOB opens a branch": ""}
    news.fill_summaries(conn, fetch)
    assert len(calls) == 2                                                            # tried once each, never again
    conn.close()


def test_only_publisher_article_links_are_ever_fetched(db_path):
    assert news.fetch_page("https://evil.example/a") is None
    assert news.fetch_page("http://www.straitstimes.com/a") is None                 # https only
    assert news.fetch_page("https://straitstimes.com.evil.example/a") is None
    conn = db.get_connection(db_path)
    conn.execute("INSERT INTO news (url, title, source, published) VALUES ('https://evil.example/x', 'Singapore x', 'CNA', ?)",
                 (now(),))
    conn.commit()
    calls = []
    news.fill_summaries(conn, lambda url: calls.append(url) or "")
    assert calls == []
    conn.close()


def test_page_code_never_shows_in_a_summary():
    assert news.tidy_summary("Seatrium won it. (function(d, s, id) { var js, fjs = d.getElementsByTagName(s)") == "Seatrium won it."
    assert news.tidy_summary("&lt;p&gt;Hello&lt;/p&gt;&lt;script&gt;var a=1;&lt;/script&gt; world") == "Hello world"
    assert news.tidy_summary("Rents rose; available space varied") == "Rents rose; available space varied"


def test_story_cards_carry_three_months_for_their_chart(app, db_path):
    conn = db.get_connection(db_path)
    db.save_prices(conn, "D05.SI", [("2025-01-03", 31.0), ("2025-01-06", 33.0)])
    news.save(conn, [item("DBS profit rises", "https://www.businesstimes.com.sg/1")])
    conn.close()
    raw = app.test_client().get("/news").get_data(as_text=True)
    assert "data-story-chart" in raw and "news-chart.js" in raw and '"story_day":' in raw
    assert '"prices": [["2025-01-02", 30.0], ["2025-01-03", 31.0], ["2025-01-06", 33.0]]' in raw
    assert "data-chart-motion" not in raw and "data-chart-close" in raw            # no switch; a close button
    assert 'popovertarget="story-' in raw and "How to read this" in raw              # and its own explanation


def test_market_today_has_no_topics_box_any_more(app, db_path):
    conn = db.get_connection(db_path)
    news.save(conn, [item("DBS declares a dividend", "https://www.businesstimes.com.sg/1")])
    conn.close()
    raw = app.test_client().get("/news").get_data(as_text=True)
    assert 'id="topics-title"' not in raw and "lesson 6, Dividends" in raw            # the card still links it


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

def test_each_holding_type_opens_its_meaning(app):
    c = signed_up(app)
    add(c)                                                                            # DBS: a company's shares
    add(c, ticker="ES3.SI", price="3.50")                                             # an ETF
    page = c.get("/portfolio").get_data(as_text=True)
    assert 'popovertarget="term-share"' in page and 'popovertarget="term-etf"' in page


def test_the_home_bar_says_learn_once():
    import re
    from pathlib import Path
    home = Path(__file__).resolve().parent.parent / "templates" / "home.html"
    assert len(re.findall(r">Learn</a>", home.read_text(encoding="utf-8"))) == 0      # the page jump is "Before you invest"


def test_headlines_that_differ_only_in_numbers_are_different_stories(db_path):
    conn = db.get_connection(db_path)
    news.save(conn, [item("Singapore shares rise; STI up 0.6%", "https://www.businesstimes.com.sg/a", hours_ago=20),
                     item("Singapore shares rise; STI up 1.1%", "https://www.businesstimes.com.sg/b", hours_ago=2)])
    assert len(news.recent(conn)) == 2
    conn.close()


def test_the_feed_comes_10_to_a_page(app, db_path):
    conn = db.get_connection(db_path)
    news.save(conn, [item(f"Singapore exports report {i}", f"https://www.straitstimes.com/{i}", hours_ago=i + 1)
                     for i in range(14)])
    conn.close()
    page = app.test_client().get("/news").get_data(as_text=True)
    assert 'id="news-feed" data-per-page="10"' in page and "news-pages.js" in page
    assert page.count("Singapore exports report") == 14                              # all sent: the script pages them


def test_market_today_has_no_source_line_and_topics_link_to_the_paragraph(app, db_path):
    conn = db.get_connection(db_path)
    news.save(conn, [item("DBS declares a dividend", "https://www.businesstimes.com.sg/1")])
    conn.close()
    raw = app.test_client().get("/news").get_data(as_text=True)
    assert "checked every 3 hours" not in raw and "Singapore business news from CNA" not in raw
    assert 'href="/learn/dividends#at-qualify"' in raw


def test_every_topic_spot_names_a_real_paragraph():
    import re
    from pathlib import Path as P
    for (topic, slug), spot in news.TOPIC_SPOTS.items():
        assert slug in news.TOPICS[topic][2], (topic, slug)
        page = (P(__file__).resolve().parent.parent / "templates" / "learn" / f"{slug}.html").read_text(encoding="utf-8")
        assert re.search(rf'id="{spot}"', page), (slug, spot)

