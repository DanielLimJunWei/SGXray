"""Audit 4 (25 Nov 2026): every bug the full audit found, pinned down so it can't come back.

- Same-day trades are checked in the order the maths adds them up (an edit keeps its place).
- "Today" is Singapore's date, even on a server that runs on UTC.
- Trades before 1990 are refused (no prices exist for them).
- Emails are plain letters only (look-alike Unicode letters can't turn into someone else's address).
- Behind the hosting proxy, each visitor's own network address is used; a typed-in one is never trusted.
- Every page is kept out of the browser cache while logged in.
- News links: plain host names only, and redirects are checked before they're followed.
- Monthly plans skip a month with no trading within a week of the buy day.
"""

import re
from datetime import datetime

import pytest

import auth
import db
import news
import plans
import sgtime
from test_trades import GOOD, add, app, db_path, downloads, saved, signed_up, token  # noqa: F401  (fixtures)
from app import create_app


def _edit(c, tid, **fields):
    data = {"ticker": "D05.SI", "date": "2025-03-03", "side": "BUY", "quantity": "100", "price": "35.20", "fees": "",
            **fields}
    return c.post(f"/trades/{tid}/edit", data={"csrf": token(c, f"/trades/{tid}/edit"), **data})


# ---------- Same-day trades ----------

def test_editing_a_same_day_buy_that_covers_a_sale_is_allowed(app, db_path):
    c = signed_up(app)
    add(c, date="2025-03-03", quantity="100")
    add(c, date="2025-03-03", side="SELL", quantity="100", price="36")
    buy = saved(db_path)[0]
    r = _edit(c, buy["id"], price="35.10")                  # just fixing the price: it used to be refused
    assert r.status_code == 302
    assert saved(db_path)[0]["price"] == 35.10


def test_moving_a_sale_onto_a_day_before_its_buy_was_saved_is_refused_and_the_page_still_works(app, db_path):
    c = signed_up(app)
    add(c, date="2025-03-03", quantity="100")                   # id 1
    add(c, date="2025-03-05", side="SELL", quantity="50", price="36")   # id 2
    add(c, date="2025-03-07", quantity="100")                   # id 3
    sale = [t for t in saved(db_path) if t["side"] == "SELL"][0]
    # On 7 Mar the sale (saved before that day's buy) would come first, with only 50 held: refused.
    r = _edit(c, sale["id"], date="2025-03-07", side="SELL", quantity="150", price="36")
    assert r.status_code == 422
    assert c.get("/portfolio").status_code == 200              # before the fix: accepted, then a 500 here


# ---------- Singapore's date ----------

def test_a_trade_made_this_morning_in_singapore_is_not_in_the_future(app, db_path, monkeypatch):
    # 00:30 on 4 March in Singapore is still 3 March in UTC, the date a hosting server's clock would say.
    monkeypatch.setattr(sgtime, "now", lambda: datetime(2025, 3, 4, 0, 30, tzinfo=sgtime.SGT))
    c = signed_up(app)
    r = add(c, date="2025-03-04")
    assert r.status_code == 302, r.get_data(as_text=True)[:300]
    assert sgtime.today().isoformat() == "2025-03-04"


def test_a_trade_before_1990_is_refused(app):
    c = signed_up(app)
    r = add(c, date="1900-01-01")
    assert r.status_code == 422 and "before 1990" in r.get_data(as_text=True)


# ---------- Emails ----------

@pytest.mark.parametrize("email", ["Kate@example.com", "café@example.com", "ann@exаmple.com"])
def test_look_alike_letters_are_refused_in_emails(email):
    assert auth.email_problem(email) is not None


def test_plain_emails_still_work():
    assert auth.email_problem("ann.lee+sgx@example.com") is None


# ---------- The visitor's network address ----------

def _attempt_keys(db_path):
    conn = db.get_connection(db_path)
    keys = [r["key"] for r in conn.execute("SELECT key FROM login_attempts WHERE key LIKE 'ip:%'")]
    conn.close()
    return keys


def _wrong_login(client):
    client.post("/login", data={"csrf": token(client, "/login"), "email": "x@example.com", "password": "wrong guess"},
                headers={"X-Forwarded-For": "203.0.113.9, 198.51.100.7"}, environ_base={"REMOTE_ADDR": "10.0.0.1"})


def test_without_a_proxy_a_typed_in_address_is_ignored(db_path, monkeypatch):
    monkeypatch.setenv("SGXRAY_SECRET_KEY", "test-only-secret")
    monkeypatch.delenv("SGXRAY_PROXIES", raising=False)
    _wrong_login(create_app(db_path).test_client())
    assert _attempt_keys(db_path) == ["ip:10.0.0.1"]


def test_behind_one_proxy_only_the_address_it_saw_is_used(db_path, monkeypatch):
    monkeypatch.setenv("SGXRAY_SECRET_KEY", "test-only-secret")
    monkeypatch.setenv("SGXRAY_PROXIES", "1")
    _wrong_login(create_app(db_path).test_client())
    # The proxy appends the address it really saw (198.51.100.7); the earlier one was typed by the visitor.
    assert _attempt_keys(db_path) == ["ip:198.51.100.7"]


# ---------- Browser cache ----------

@pytest.mark.parametrize("path", ["/learn", "/learn/dividends", "/demo", "/news", "/", "/what-if"])
def test_logged_in_every_page_is_kept_out_of_the_browser_cache(app, path):
    c = signed_up(app)
    assert "no-store" in c.get(path).headers.get("Cache-Control", "")


# ---------- News links ----------

@pytest.mark.parametrize("url, ok", [
    ("https://www.straitstimes.com/business/a", True),
    ("https://evil.example\\.straitstimes.com/a", False),        # a browser would go to evil.example
    ("https://www.straitstimes.com@evil.example/a", False),
    ("http://www.straitstimes.com/a", False),
    ("https://notstraitstimes.com/a", False),
    ("https://www.straitstimes.com:8443/a", False),
])
def test_only_plain_https_links_on_a_publishers_own_site_count(url, ok):
    assert news._publisher_link(url) is ok


def test_a_redirect_off_the_publishers_site_is_not_followed():
    handler = news._SameSiteRedirects()
    assert handler.redirect_request(None, None, 302, "Found", {}, "http://169.254.169.254/latest/meta-data/") is None
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example/") is None


# ---------- Monthly plans ----------

def test_a_month_with_no_trading_near_the_buy_day_is_skipped(app, db_path):
    conn = db.get_connection(db_path)
    # Suspended from mid-January to April: February's and March's buys don't all land on 1 April.
    db.save_prices(conn, "ES3.SI", [("2025-01-15", 3.50), ("2025-04-01", 3.60), ("2025-04-15", 3.70)])
    conn.close()
    c = signed_up(app)
    c.post("/plans", data={"csrf": token(c, "/trades"), "ticker": "ES3.SI", "amount": "100", "day": "15",
                           "start": "2025-01", "fee_rate": "0", "fee_min": "0"})
    assert [t["trade_date"] for t in saved(db_path)] == ["2025-01-15", "2025-04-15"]


# ---------- The maths, against outside references ----------

def test_xirr_matches_excels_own_documented_example():
    from datetime import date
    import performance
    flows = [(date(2008, 1, 1), -10000), (date(2008, 3, 1), 2750), (date(2008, 10, 30), 4250),
             (date(2009, 2, 15), 3250), (date(2009, 4, 1), 2750)]
    assert abs(performance.xirr(flows) - 0.373362535) < 1e-8       # Microsoft's XIRR help page: 37.34%


# ---------- Audit 4b (25 Nov 2026): wording, read line by line ----------

def test_the_dividends_spotlight_says_price_moves_dont_change_yield_on_cost():
    import lessons
    text = lessons.SPOTS["dividends"]["text"]
    assert "price moves don't change it" in text and "grows as the price rises" not in text


def test_no_page_tells_a_visitor_to_run_a_command(app):
    c = signed_up(app)                      # a portfolio with no STI ETF prices: the "nothing to compare" message
    add(c)
    for path in ("/portfolio", "/demo"):
        page = c.get(path).get_data(as_text=True)
        assert "python src/" not in page and "Run the price update" not in page, path


def test_a_split_before_you_owned_the_stock_isnt_a_watch_out(db_path):
    import explain
    conn = db.get_connection(db_path)
    uid = db.create_user(conn, "split@example.com", "!x")
    db.save_actions(conn, "D05.SI", [("2024-04-22", 1.1)])
    db.save_prices(conn, "D05.SI", [("2025-03-03", 35.0)])
    db.add_trade(conn, uid, "D05.SI", "2025-03-03", "BUY", 100, 35.0, 0)      # bought after the bonus issue
    watch = " ".join(explain.explain_holdings(conn, uid).watch_out)
    assert "bonus issue" not in watch
    conn.close()


def test_the_tax_line_doesnt_promise_every_sgx_dividend_is_tax_free():
    import inspect
    import explain
    src = inspect.getsource(explain.explain_dividends_received)
    assert "Singapore REITs are tax-free" in src and "based abroad" in src


def test_moneysense_is_only_credited_with_what_it_says():
    import glossary
    import readiness
    assert "12 if" not in glossary.TERMS["emergency-fund"][1]
    assert "MoneySense suggests about 12" not in readiness.IRREGULAR_NO


# ---------- Audit 4b, ZAP: stricter headers ----------

def test_styles_come_only_from_sgxrays_own_files(app):
    from pathlib import Path
    r = app.test_client().get("/demo")
    csp = r.headers["Content-Security-Policy"]
    assert "style-src 'self';" in csp + ";" and "unsafe-inline" not in csp
    # ...so no page may carry an inline style="" or a <style> block (the browser would ignore it)
    root = Path(__file__).resolve().parent.parent
    for f in list((root / "templates").rglob("*.html")) + list((root / "static" / "js").glob("*.js")):
        text = f.read_text(encoding="utf-8")
        assert 'style="' not in text and "<style" not in text, f.name


def test_cross_origin_isolation_headers(app):
    r = app.test_client().get("/")
    assert r.headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert r.headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert r.headers["Cross-Origin-Embedder-Policy"] == "require-corp"


def test_the_price_chart_draws_in_its_own_svg_not_the_range_dot():
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "static" / "js" / "stock-chart.js").read_text(encoding="utf-8")
    assert 'section.querySelector("svg.stock-svg")' in js
