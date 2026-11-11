"""The Learn page and its lessons (w313): open to everyone, numbers from the live demo, progress kept calmly."""

import re
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db  # noqa: E402
import glossary  # noqa: E402
import lessons  # noqa: E402
from app import create_app  # noqa: E402
from importer import DEMO_EMAIL  # noqa: E402
from instruments import seed_instruments  # noqa: E402

GOOD = "correct horse battery staple"


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "learn.db"
    conn = db.get_connection(path)
    db.init_db(conn)
    seed_instruments(conn)
    conn.close()
    return path


@pytest.fixture
def app(db_path, monkeypatch):
    monkeypatch.setenv("SGXRAY_SECRET_KEY", "test-only-secret")
    return create_app(db_path)


def load_demo(db_path):
    """A small demo: DBS and the STI ETF bought on 6 Jan, a 20% fall to 3 Mar, then back above by 2 Jun."""
    conn = db.get_connection(db_path)
    uid = db.create_user(conn, DEMO_EMAIL, "!demo-no-login")
    db.add_trade(conn, uid, "D05.SI", "2025-01-06", "BUY", 100, 40.00, 10.0)
    db.add_trade(conn, uid, "ES3.SI", "2025-01-06", "BUY", 1000, 3.50, 10.0)
    db.save_prices(conn, "D05.SI", [("2025-01-06", 40.0), ("2025-02-03", 42.0), ("2025-03-03", 32.0),
                                    ("2025-06-02", 45.0)])
    db.save_prices(conn, "ES3.SI", [("2025-01-06", 3.5), ("2025-02-03", 3.6), ("2025-03-03", 3.0),
                                    ("2025-06-02", 3.8)])
    conn.close()
    return uid


def token(c, path):
    return re.search(r'name="csrf" value="([^"]+)"', c.get(path).get_data(as_text=True)).group(1)


def signed_up(app, email="ann@example.com"):
    c = app.test_client()
    c.post("/signup", data={"csrf": token(c, "/signup"), "email": email, "password": GOOD, "password2": GOOD})
    return c


def done(c, slug):
    return c.post(f"/learn/{slug}/done", data={"csrf": token(c, f"/learn/{slug}")})


# ---------- Open to everyone ----------

def test_the_learn_page_lists_every_lesson_without_logging_in(app):
    page = app.test_client().get("/learn").get_data(as_text=True)
    for lesson in lessons.LESSONS:
        assert lesson.title.replace("'", "&#39;") in page
    assert f"0 of {len(lessons.LESSONS)} read" in re.sub(r"<[^>]+>", "", page)
    assert "Start with lesson 1" in page
    assert "9 short lessons" in page and "Spotting investment scams" in page


def test_written_lessons_open_and_unwritten_ones_dont(app):
    c = app.test_client()
    for lesson in lessons.LESSONS:
        status = c.get(f"/learn/{lesson.slug}").status_code
        assert status == (200 if lesson.ready else 404), lesson.slug
    assert c.get("/learn/not-a-lesson").status_code == 404


def test_every_lesson_has_its_parts(app):
    """The idea, a demo box, Watch out, a hidden-answer question, Next, sources and the not-advice line."""
    c = app.test_client()
    for lesson in (x for x in lessons.LESSONS if x.ready):
        page = c.get(f"/learn/{lesson.slug}").get_data(as_text=True)
        assert lesson.idea.replace("'", "&#39;") in page
        for part in ("In the demo", "Watch out", '<details class="lesson-check">', "Check yourself",
                     "Sources:", "not financial advice", 'data-lesson-done="' + lesson.slug + '"'):
            assert part in page, (lesson.slug, part)
        assert "n/a" not in page and not re.search(r"nan", page)


def test_every_tappable_word_in_a_lesson_has_a_meaning(app):
    c = app.test_client()
    for lesson in (x for x in lessons.LESSONS if x.ready):
        page = c.get(f"/learn/{lesson.slug}").get_data(as_text=True)
        keys = set(re.findall(r'popovertarget="term-([a-z0-9-]+)"', page))
        assert keys, lesson.slug
        for k in keys:
            assert k in glossary.TERMS and f'id="term-{k}"' in page


def test_the_home_page_and_top_bar_link_to_learn(app):
    page = app.test_client().get("/").get_data(as_text=True)
    assert 'class="btn btn-primary" href="/learn">Start learning' in page
    assert 'class="nav-link" href="/learn">Learn</a>' in page


# ---------- Real numbers from the demo ----------

def test_lesson_1_shows_the_demos_biggest_fall_with_no_trades_in_between(app, db_path):
    uid = load_demo(db_path)
    conn = db.get_connection(db_path)
    dip = lessons.biggest_dip(conn, uid)
    conn.close()
    # 3 Feb: 100 x 42 + 1000 x 3.6 = 7,800. 3 Mar: 100 x 32 + 1000 x 3.0 = 6,200. Back above by 2 Jun (8,300).
    assert (dip["peak_day"], dip["peak"], dip["low_day"], dip["low"]) == \
        (date(2025, 2, 3), 7800.0, date(2025, 3, 3), 6200.0)
    assert dip["fall"] == pytest.approx(1600.0) and dip["fall_pct"] == pytest.approx(-1600 / 7800)
    assert dip["back_day"] == date(2025, 6, 2)
    page = app.test_client().get("/learn/first-dollar").get_data(as_text=True)
    assert "$1,600.00" in page and "21% less" in page and "3 February 2025" in page and "2 June 2025" in page


def test_a_fall_caused_by_selling_doesnt_count(db_path):
    """Selling half on the low day lowers the value, but that's money taken out, not the market falling."""
    uid = load_demo(db_path)
    conn = db.get_connection(db_path)
    db.add_trade(conn, uid, "ES3.SI", "2025-06-02", "SELL", 900, 3.8, 10.0)
    dip = lessons.biggest_dip(conn, uid)
    conn.close()
    assert dip["low_day"] == date(2025, 3, 3)             # still the market's fall, not the sale


def test_lesson_2_shows_what_the_demo_holds(app, db_path):
    load_demo(db_path)
    page = app.test_client().get("/learn/what-you-own").get_data(as_text=True)
    assert "DBS Group Holdings" in page and "Shares in a company" in page and "An ETF" in page
    # Latest: DBS 4,500 and the ETF 3,800 of 8,300 -> 54% and 46%
    assert "54% of the portfolio" in page and "46% of the portfolio" in page
    assert "spread over 30 companies" in page


def test_lessons_still_work_before_the_demo_is_loaded(app):
    c = app.test_client()
    assert "isn't loaded yet" in c.get("/learn/first-dollar").get_data(as_text=True)
    assert "isn't loaded yet" in c.get("/learn/what-you-own").get_data(as_text=True)


# ---------- Progress ----------

def test_done_moves_to_the_next_lesson_and_saves_it_when_logged_in(app, db_path):
    c = signed_up(app)
    r = done(c, "first-dollar")
    assert r.status_code == 302 and r.headers["Location"].endswith("/learn/what-you-own")
    page = re.sub(r"<[^>]+>", "", c.get("/learn").get_data(as_text=True))
    assert f"1 of {len(lessons.LESSONS)} read" in page and "Carry on: What you actually own" in page
    done(c, "first-dollar")                                     # twice still counts once
    assert f"1 of {len(lessons.LESSONS)} read" in re.sub(r"<[^>]+>", "", c.get("/learn").get_data(as_text=True))


def test_the_last_lesson_leads_to_the_self_check(app):
    c = signed_up(app)
    last = lessons.LESSONS[-1].slug
    r = done(c, last)
    assert r.status_code == 302 and r.headers["Location"].endswith("/learn/ready")   # on to the self-check


def test_logged_out_progress_stays_in_the_browser_only(app, db_path):
    c = app.test_client()
    assert done(c, "first-dollar").status_code == 302           # works, but nothing saved on the server
    conn = db.get_connection(db_path)
    assert conn.execute("SELECT COUNT(*) FROM lesson_reads").fetchone()[0] == 0
    conn.close()
    assert "data-local-progress" in c.get("/learn").get_data(as_text=True)


def test_progress_is_yours_alone(app):
    ann = signed_up(app)
    done(ann, "first-dollar")
    bob = signed_up(app, "bob@example.com")
    assert f"0 of {len(lessons.LESSONS)} read" in re.sub(r"<[^>]+>", "", bob.get("/learn").get_data(as_text=True))


def test_done_needs_the_form_token(app):
    assert app.test_client().post("/learn/first-dollar/done").status_code == 400


def test_a_lesson_that_doesnt_exist_cant_be_marked_done(app):
    c = signed_up(app)
    assert c.post("/learn/not-a-lesson/done", data={"csrf": token(c, "/learn")}).status_code == 404


def test_no_page_sends_visitors_to_google_fonts(app):
    """Fonts are served by SGXray itself (static/fonts/), so no visitor's address goes to Google."""
    c = app.test_client()
    for path in ("/", "/learn", "/learn/first-dollar", "/login", "/signup", "/demo"):
        r = c.get(path)
        assert "googleapis" not in r.get_data(as_text=True) and "gstatic" not in r.get_data(as_text=True), path
        assert "font-src 'self'" in r.headers["Content-Security-Policy"]
    assert c.get("/static/fonts/inter.woff2").status_code == 200


# ---------- Lessons 3-9: real numbers from the demo ----------

def test_every_lesson_shows_real_demo_numbers_once_the_demo_is_loaded(app, db_path):
    load_demo(db_path)
    conn = db.get_connection(db_path)
    conn.execute("INSERT INTO dividends (ticker, ex_date, amount) VALUES ('D05.SI', '2025-04-07', 0.60)")
    conn.commit()
    conn.close()
    c = app.test_client()
    for lesson in lessons.LESSONS:
        page = c.get(f"/learn/{lesson.slug}").get_data(as_text=True)
        box = page[page.index('class="panel lesson-demo"'):page.index('class="lesson-watch"')]
        assert "loaded yet" not in box, lesson.slug                   # every lesson finds its numbers
        assert "n/a" not in box and not re.search(r"\bnan\b", box), lesson.slug
        assert "$" in box, lesson.slug


def test_the_fees_lesson_adds_up_the_demos_fees(app, db_path):
    load_demo(db_path)
    page = app.test_client().get("/learn/fees").get_data(as_text=True)
    # Two buys: $4,000 of DBS and $3,500 of the STI ETF, $10 fees each -> $20, 0.27% of $7,500
    assert "$20.00" in page and "$7,500.00" in page and "0.27%" in page
    assert "$3,500.00 of SPDR Straits Times Index ETF" in page             # the smallest buy


def test_the_scams_lesson_works_out_3_percent_a_month(app):
    page = app.test_client().get("/learn/scams").get_data(as_text=True)    # needs no demo at all
    assert "43% a year" in page and "$14,257.61" in page                   # 1.03^12 - 1 = 42.6%


def test_the_dividends_lesson_counts_the_demos_dividends(app, db_path):
    uid = load_demo(db_path)
    conn = db.get_connection(db_path)
    conn.execute("INSERT INTO dividends (ticker, ex_date, amount) VALUES ('D05.SI', '2025-04-07', 0.60)")
    conn.commit()
    sums = lessons.money_summary(conn, uid)
    conn.close()
    assert sums["dividends"] == pytest.approx(60.0)                         # 100 shares x $0.60
    page = app.test_client().get("/learn/dividends").get_data(as_text=True)
    assert "$60.00" in page and "tax-free" in page


def test_the_stocks_vs_market_lesson_judges_each_stock(app, db_path):
    load_demo(db_path)
    page = app.test_client().get("/learn/stocks-vs-market").get_data(as_text=True)
    assert "DBS Group Holdings" in page and "SPDR Straits Times Index ETF" in page
    assert "the STI ETF" in page and ("beat the market" in page or "trailed the market" in page)


def test_the_reading_sgxray_lesson_splits_the_demo_into_layers(app, db_path):
    uid = load_demo(db_path)
    conn = db.get_connection(db_path)
    layers = lessons.xray_layers(conn, uid)
    conn.close()
    # Latest day: 100 x 45 + 1000 x 3.8 = 8,300 worth; 7,520 went in (incl. fees) -> +780 of price gains
    assert layers["money"] == pytest.approx(7520.0) and layers["gains"] == pytest.approx(780.0)
    page = app.test_client().get("/learn/reading-sgxray").get_data(as_text=True)
    assert "$7,520.00" in page and "+$780.00" in page


def test_a_demo_with_no_dividends_yet_says_so_instead_of_not_loaded(app, db_path):
    load_demo(db_path)
    page = app.test_client().get("/learn/dividends").get_data(as_text=True)
    assert "hasn't been paid any dividends yet" in page and "isn't loaded yet" not in page
