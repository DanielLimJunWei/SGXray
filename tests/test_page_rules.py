"""The page rule, checked on whole portfolio pages so every future table and figure follows it too.

1. Every cell shows a value or a reason in words ("pending", "too soon", "in 4 months"...):
   never a blank cell, never "n/a" or "nan".
2. A table with nothing in it shows one row saying why, not an empty frame.
3. Every key figure and every table has a "What does this mean?" box.
4. Every reason word is a tap-a-term: tapping it says what it means (no hover-only tooltips,
   which phones can't show and most people never find).
5. No cell stretches over several columns (it leaves the ones under it looking empty), except the
   one-message row of an empty table. Total rows give every column its own value or reason.

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


# The reason words a cell or figure shows instead of a number (NOTES.md, "The page rule").
REASON = re.compile(r"\b(pending|no price yet|per stock|too soon|after today's close|waiting|not yet|a year|in \d+ (?:days?|months?|years?)"
                    r"|in 1 year(?: and \d+ months?)?)\b", re.I)
TERM_BUTTON = re.compile(r'<button class="term"[^>]*data-term="([a-z-]+)"[^>]*>(.*?)</button>', re.S)


def check_reason_words(page):
    """Rule 4: in table cells, big figures and period rows, every reason word sits inside a term button
    whose meaning box is on the page. Returns the reason words it found, so tests can check they ran."""
    seen = set()
    for key, word in TERM_BUTTON.findall(page):
        if REASON.search(_text(word)):
            assert f'id="term-{key}"' in page, f"'{_text(word)}' opens a meaning box that isn't on the page"
            seen.add(_text(word).lower())
    places = (re.findall(r"<td[^>]*>(.*?)</td>", page, re.S)
              + re.findall(r'<span class="value[^"]*"[^>]*>(.*?)</span>', page, re.S)
              + re.findall(r'<b class="muted">(.*?)</b>', page, re.S))
    for place in places:
        bare = _text(TERM_BUTTON.sub(" ", place))
        assert not REASON.search(bare), f"a reason word with no explanation to tap: '{bare}'"
    return seen


def check_page_rules(page):
    check_reason_words(page)
    page = re.sub(r"<script.*?</script>|<div class=\"pop\".*?</div>\s*</div>", " ", page, flags=re.S)
    visible = _text(page)
    assert "n/a" not in visible and " nan" not in visible.lower(), "a value shows n/a instead of a reason"

    for table in re.findall(r"<table class=\"data[^\"]*\">(.*?)</table>", page, re.S):
        for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", table, re.S):
            assert _text(cell), f"a blank cell in: {_text(table)[:120]}"
        # A cell stretched over several columns leaves the columns under it looking empty (the gaps found
        # in the demo's total rows, 11 Nov 2026). Only the one-message row of an empty table may stretch.
        for row in re.findall(r"<tr([^>]*)>(.*?)</tr>", table, re.S):
            if "empty-row" not in row[0]:
                assert "colspan" not in row[1], f"a cell spans several columns, leaving gaps: {_text(row[1])[:80]}"
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


def test_reason_words_are_tappable_on_the_day_you_buy(app):
    """Bought today: 'pending' and 'after today's close' both open their meaning."""
    c = _client(app)
    _add(c)
    _add(c, ticker="O39.SI", date="2025-06-24", price="14")
    seen = check_reason_words(c.get("/portfolio").get_data(as_text=True))
    assert {"pending", "after today's close"} <= seen


def test_waiting_is_tappable_when_your_only_stock_was_bought_today(app):
    c = _client(app)
    _add(c, ticker="O39.SI", date="2025-06-24", price="14")
    page = c.get("/portfolio").get_data(as_text=True)
    check_page_rules(page)
    assert "waiting" in check_reason_words(page)


def test_returns_say_in_n_months_tappably(app):
    """Five months of history: returns read 'in 5 months', and that opens the yearly-or-so-far meaning."""
    c = _client(app)
    _add(c)
    seen = check_reason_words(c.get("/portfolio").get_data(as_text=True))
    assert any(w.startswith("in ") and "month" in w for w in seen), seen


def test_too_soon_is_tappable(app):
    """A stock held under a month: 'too soon' in the figure, the period rows and the stock table."""
    c = _client(app)
    _add(c, date="2025-06-09")
    page = c.get("/portfolio").get_data(as_text=True)
    check_page_rules(page)
    assert "too soon" in check_reason_words(page)


def test_not_yet_is_tappable_without_sti_prices(app, monkeypatch):
    """No STI ETF prices saved: 'Not yet' opens a meaning box."""
    c = _client(app)
    _add(c)
    conn = db.get_connection(app.config["DB_PATH"])
    conn.execute("DELETE FROM prices WHERE ticker = 'ES3.SI'")
    conn.commit()
    conn.close()
    page = c.get("/portfolio").get_data(as_text=True)
    check_page_rules(page)
    assert "not yet" in check_reason_words(page)


def test_dividend_tables_and_their_totals_follow_the_rule(app):
    """A dividend inside the last 12 months, so the yields and forecast tables (and their total rows)
    show. Their totals used to stretch cells over columns, which looked like gaps on the demo."""
    from datetime import date, timedelta
    conn = db.get_connection(app.config["DB_PATH"])
    db.save_dividends(conn, "D05.SI", [((date.today() - timedelta(days=60)).isoformat(), 0.75)])
    conn.close()
    c = _client(app)
    _add(c)
    page = c.get("/portfolio").get_data(as_text=True)
    assert "Whole portfolio" in page and "Next 12 months" in page          # both total rows are on the page
    check_page_rules(page)
    assert "per stock" in check_reason_words(page)


def test_the_trades_page_follows_the_rule(app):
    c = _client(app)
    _add(c)
    _add(c, side="SELL", date="2025-03-03", quantity="40", price="31")
    check_page_rules(c.get("/trades").get_data(as_text=True))


def test_a_stretched_cell_fails_the_check():
    with pytest.raises(AssertionError):
        check_page_rules('<table class="data"><tbody><tr><td>x</td></tr></tbody>'
                         '<tfoot><tr><th colspan="3">Total</th><td>$1</td></tr></tfoot></table>')
    check_page_rules('<table class="data"><tbody><tr class="empty-row"><td colspan="5">No trades yet</td></tr></tbody></table>')


def test_a_bare_reason_word_fails_the_check():
    """The checker itself catches a reason word left as plain text, or hidden in a hover tooltip."""
    with pytest.raises(AssertionError):
        check_reason_words('<table class="data"><tbody><tr><td><span class="sub" title="x">too soon</span></td></tr></tbody></table>')
    with pytest.raises(AssertionError):
        check_reason_words('<span class="value">Waiting</span>')


def test_a_stock_with_no_saved_price_follows_the_rule(app, monkeypatch):
    """Bought today but checked after 5:30pm, before the price update has run (the n/a found on
    11 Nov 2026): every unknown number says "no price yet", tappable, never n/a."""
    monkeypatch.setattr(app_module, "_last_close_day", lambda: "2025-06-24")
    c = _client(app)
    _add(c)
    _add(c, ticker="O39.SI", date="2025-06-24", price="14")          # no OCBC prices saved at all
    page = c.get("/portfolio").get_data(as_text=True)
    check_page_rules(page)
    assert "no price yet" in check_reason_words(page)


def test_a_stock_with_no_saved_prices_explains_its_missing_chart(app, monkeypatch):
    """Clicking "Price chart" on a stock with no saved prices used to do nothing (found 11 Nov 2026).
    Now that link opens a box saying why there's no chart yet; stocks with prices keep their chart."""
    monkeypatch.setattr(app_module, "_last_close_day", lambda: "2025-06-24")
    c = _client(app)
    _add(c)
    _add(c, ticker="O39.SI", date="2025-06-24", price="14")          # no OCBC prices saved at all
    page = c.get("/portfolio").get_data(as_text=True)
    assert 'popovertarget="term-no-chart"' in page and 'id="term-no-chart"' in page
    assert 'data-chart="chart-O39-SI"' not in page                 # no link to a chart that isn't there
    assert 'data-chart="chart-D05-SI"' in page and 'id="chart-D05-SI"' in page
