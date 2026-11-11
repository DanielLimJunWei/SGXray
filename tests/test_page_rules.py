"""The page rule, checked on whole portfolio pages so every future table and figure follows it too.

1. Every cell shows a value or a reason in words ("pending", "too soon", "in 4 months"...):
   never a blank cell, never "n/a" or "nan".
2. A table with nothing in it shows one row saying why, not an empty frame.
3. Every key figure and every table has a "What does this mean?" box.

Checked in three states a real person hits: a normal portfolio with months of history, the day you
buy a stock (no closing price until ~5:30pm), and a portfolio bought after the latest prices.
"""

import html
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as app_module  # noqa: E402
import db  # noqa: E402
from app import create_app  # noqa: E402
from instruments import seed_instruments  # noqa: E402

GOOD = "correct horse battery staple"
WEEKDAYS = [f"2025-{m:02d}-{d:02d}" for m in range(1, 7) for d in (2, 9, 16, 23) ]   # a few prices a month


def _text(fragment):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()


@pytest.fixture
def app(tmp_path, monkeypatch):
    path = tmp_path / "rules.db"
    conn = db.get_connection(path)
    db.init_db(conn)
    seed_instruments(conn)
    for i, day in enumerate(WEEKDAYS):
        db.save_prices(conn, "D05.SI", [(day, 30.0 + i * 0.3)])
        db.save_prices(conn, "ES3.SI", [(day, 3.0 + i * 0.01)])
    db.save_dividends(conn, "D05.SI", [("2025-04-09", 0.60)])
    conn.close()
    monkeypatch.setenv("SGXRAY_SECRET_KEY", "test-only-secret")
    monkeypatch.setattr(app_module, "_last_close_day", lambda: "2025-06-23")
    a = create_app(path)
    a.config["MARKET_DOWNLOAD"] = lambda conn, tickers: True
    return a


def _client(app):
    c = app.test_client()
    page = c.get("/signup").get_data(as_text=True)
    tok = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    c.post("/signup", data={"csrf": tok, "email": "ann@example.com", "password": GOOD, "password2": GOOD})
    return c


def _add(c, **f):
    page = c.get("/trades").get_data(as_text=True)
    tok = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    data = {"ticker": "D05.SI", "date": "2025-01-02", "side": "BUY", "quantity": "100", "price": "30", **f}
    assert c.post("/trades", data={"csrf": tok, **data}).status_code == 302


def check_page_rules(page):
    page = re.sub(r"<script.*?</script>|<div class=\"pop\".*?</div>\s*</div>", " ", page, flags=re.S)
    visible = _text(page)
    assert "n/a" not in visible and " nan" not in visible.lower(), "a value shows n/a instead of a reason"

    for table in re.findall(r"<table class=\"data[^\"]*\">(.*?)</table>", page, re.S):
        for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", table, re.S):
            assert _text(cell), f"a blank cell in: {_text(table)[:120]}"
        assert re.search(r"<tbody>\s*<tr", table), "a table with no rows: it should say why"

    for figure in re.findall(r'<div class="figure">(.*?)</div>', page, re.S):
        assert "What does" in figure, f"a figure without an explanation: {_text(figure)[:60]}"
    for section in re.findall(r'<section class="block[^"]*"(.*?)</section>', page, re.S):
        if "<table" in section:
            assert "What does" in section, f"a table without an explanation: {_text(section)[:60]}"


def test_a_normal_portfolio_follows_the_rule(app):
    c = _client(app)
    _add(c)
    _add(c, ticker="D05.SI", date="2025-03-03", quantity="50", price="31")
    check_page_rules(c.get("/portfolio").get_data(as_text=True))


def test_the_day_you_buy_a_stock_follows_the_rule(app):
    c = _client(app)
    _add(c)
    _add(c, ticker="O39.SI", date="2025-06-24", price="14")          # bought "today": no close yet
    check_page_rules(c.get("/portfolio").get_data(as_text=True))


def test_stocks_bought_after_the_latest_prices_follow_the_rule(app):
    c = _client(app)
    _add(c, ticker="D05.SI", date="2025-06-24", price="37")          # after the latest close (23 Jun)
    page = c.get("/portfolio").get_data(as_text=True)
    check_page_rules(page)
    assert "appear after the next price update" in html.unescape(page)
