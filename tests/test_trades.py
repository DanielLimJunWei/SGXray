"""Adding, changing and deleting trades on the website (w308).

The happy paths, the mistakes a beginner makes, and what an attacker would try: someone else's
trade id, a form without its token, impossible numbers, and selling shares you don't have.
"""

import html
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db  # noqa: E402
from app import create_app  # noqa: E402
from instruments import seed_instruments  # noqa: E402

GOOD = "correct horse battery staple"
MONDAY = "2025-03-03"
LATER = "2025-06-02"                 # also a Monday


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "trades.db"
    conn = db.get_connection(path)
    db.init_db(conn)
    seed_instruments(conn)
    for tk in ("D05.SI", "ES3.SI"):     # prices from before the test dates, so no download is needed
        db.save_prices(conn, tk, [("2025-01-02", 30.0)])
    conn.close()
    return path


@pytest.fixture
def downloads():
    return []


@pytest.fixture
def app(db_path, downloads, monkeypatch):
    monkeypatch.setenv("SGXRAY_SECRET_KEY", "test-only-secret")
    a = create_app(db_path)
    a.config["MARKET_DOWNLOAD"] = lambda conn, tickers: downloads.append(tickers) or True   # never the internet
    return a


def token(client, path="/trades"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def signed_up(app, email="ann@example.com"):
    c = app.test_client()
    c.post("/signup", data={"csrf": token(c, "/signup"), "email": email, "password": GOOD, "password2": GOOD})
    return c


def add(client, **fields):
    data = {"ticker": "D05.SI", "date": MONDAY, "side": "BUY", "quantity": "100", "price": "35.20", "fees": "",
            **fields}
    return client.post("/trades", data={"csrf": token(client), **data})


def saved(db_path, email="ann@example.com"):
    conn = db.get_connection(db_path)
    uid = db.get_user_by_email(conn, email)["id"]
    rows = [dict(t) for t in db.get_trades(conn, uid)]
    conn.close()
    return rows


# ---------- Happy paths ----------

def test_a_trade_can_be_added_and_is_listed(app, db_path):
    c = signed_up(app)
    r = add(c, fees="10.50")
    assert r.status_code == 302
    [t] = saved(db_path)
    assert (t["ticker"], t["trade_date"], t["side"], t["quantity"], t["price"], t["fees"]) == \
        ("D05.SI", MONDAY, "BUY", 100, 35.2, 10.5)
    page = c.get(r.headers["Location"]).get_data(as_text=True)
    assert "Trade saved" in page and "DBS Group Holdings" in page and "3,530.50" in page


def test_broker_style_numbers_are_accepted(app, db_path):
    c = signed_up(app)
    add(c, quantity="1,000", price="S$35.20")
    assert saved(db_path)[0]["quantity"] == 1000


def test_a_trade_can_be_changed(app, db_path):
    c = signed_up(app)
    add(c)
    tid = saved(db_path)[0]["id"]
    form = c.get(f"/trades/{tid}/edit").get_data(as_text=True)
    assert 'value="35.2"' in form                                      # the form is filled in
    r = c.post(f"/trades/{tid}/edit", data={"csrf": token(c), "ticker": "D05.SI", "date": MONDAY, "side": "BUY",
                                           "quantity": "200", "price": "35.20", "fees": ""})
    assert r.status_code == 302
    assert saved(db_path)[0]["quantity"] == 200


def test_delete_asks_first_then_deletes(app, db_path):
    c = signed_up(app)
    add(c)
    tid = saved(db_path)[0]["id"]
    page = c.get(f"/trades/{tid}/delete").get_data(as_text=True)
    assert "Delete this trade?" in page and saved(db_path)            # asking doesn't delete
    r = c.post(f"/trades/{tid}/delete", data={"csrf": token(c)})
    assert r.status_code == 302 and saved(db_path) == []


def test_portfolio_links_to_the_trades_page(app):
    c = signed_up(app)
    assert "/trades" in c.get("/portfolio").get_data(as_text=True)


# ---------- Mistakes: nothing is saved, and the reason is shown ----------

@pytest.mark.parametrize("fields, words", [
    ({"ticker": "AAPL"}, "unknown ticker"),
    ({"ticker": "D05"}, "did you mean D05.SI"),
    ({"date": "2099-01-05"}, "in the future"),
    ({"date": "2025-03-01"}, "Saturday"),
    ({"date": "2025-02-30"}, "doesn't exist"),
    ({"side": "HOLD"}, "BUY or SELL"),
    ({"quantity": "0"}, "whole number above 0"),
    ({"quantity": "-5"}, "whole number above 0"),
    ({"quantity": "1.5"}, "whole number above 0"),
    ({"price": "0"}, "above 0"),
    ({"price": "nan"}, "above 0"),
    ({"price": "1e999"}, "above 0"),
    ({"fees": "-1"}, "0 or more"),
    ({"quantity": "1000000000"}, "extra zero"),
    ({"price": "3520"}, None),                     # dear, but possible: saved
    ({"price": "352000"}, "extra zero"),
    ({"fees": "1000000"}, "extra zero"),
])
def test_bad_values_are_refused_with_a_reason(app, db_path, fields, words):
    c = signed_up(app)
    r = add(c, **fields)
    if words is None:
        assert r.status_code == 302 and len(saved(db_path)) == 1
        return
    assert r.status_code == 422
    assert words.lower() in html.unescape(r.get_data(as_text=True)).lower()
    assert saved(db_path) == []


def test_the_form_keeps_what_you_typed_after_a_mistake(app):
    c = signed_up(app)
    page = add(c, quantity="0", price="35.20").get_data(as_text=True)
    assert 'value="35.20"' in page


def test_you_cant_sell_shares_you_dont_hold(app, db_path):
    c = signed_up(app)
    add(c, quantity="100")
    r = add(c, side="SELL", quantity="150", date=LATER)
    assert r.status_code == 422 and "only 100 are held" in r.get_data(as_text=True)
    assert len(saved(db_path)) == 1


def test_a_change_that_breaks_a_later_sale_is_refused(app, db_path):
    c = signed_up(app)
    add(c, quantity="100")
    add(c, side="SELL", quantity="100", date=LATER)
    buy = saved(db_path)[0]["id"]
    r = c.post(f"/trades/{buy}/edit", data={"csrf": token(c), "ticker": "D05.SI", "date": MONDAY, "side": "BUY",
                                           "quantity": "50", "price": "35.20", "fees": ""})
    assert r.status_code == 422 and "too few D05.SI shares" in r.get_data(as_text=True)
    assert saved(db_path)[0]["quantity"] == 100


def test_deleting_a_buy_a_later_sale_needs_is_refused(app, db_path):
    c = signed_up(app)
    add(c, quantity="100")
    add(c, side="SELL", quantity="100", date=LATER)
    buy = saved(db_path)[0]["id"]
    page = c.get(f"/trades/{buy}/delete").get_data(as_text=True)
    assert "too few D05.SI shares" in page and "Delete trade</button>" not in page
    r = c.post(f"/trades/{buy}/delete", data={"csrf": token(c)})
    assert r.status_code == 422 and len(saved(db_path)) == 2


# ---------- Attacks ----------

def test_you_must_be_logged_in(app):
    c = app.test_client()
    for path in ("/trades", "/trades/1/edit", "/trades/1/delete"):
        r = c.get(path)
        assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_someone_elses_trade_is_invisible_and_untouchable(app, db_path):
    """IDOR: Bob changes the number in the address to Ann's trade. He gets 'not found', nothing changes."""
    ann = signed_up(app, "ann@example.com")
    add(ann)
    tid = saved(db_path, "ann@example.com")[0]["id"]
    bob = signed_up(app, "bob@example.com")
    assert bob.get(f"/trades/{tid}/edit").status_code == 404
    assert bob.get(f"/trades/{tid}/delete").status_code == 404
    assert bob.post(f"/trades/{tid}/edit", data={"csrf": token(bob), "ticker": "D05.SI", "date": MONDAY,
                                                 "side": "BUY", "quantity": "1", "price": "1"}).status_code == 404
    assert bob.post(f"/trades/{tid}/delete", data={"csrf": token(bob)}).status_code == 404
    assert "35.200" not in bob.get("/trades").get_data(as_text=True)         # not in Bob's list either
    assert saved(db_path, "ann@example.com")[0]["quantity"] == 100


def test_forms_without_the_token_are_refused(app, db_path):
    """CSRF: another website can't make your browser add or delete trades."""
    c = signed_up(app)
    add(c)
    tid = saved(db_path)[0]["id"]
    assert c.post("/trades", data={"ticker": "D05.SI", "date": MONDAY, "side": "BUY",
                                   "quantity": "1", "price": "1"}).status_code == 400
    assert c.post(f"/trades/{tid}/delete", data={}).status_code == 400
    assert len(saved(db_path)) == 1


def test_html_in_a_field_is_shown_as_text_never_run(app):
    c = signed_up(app)
    page = add(c, quantity="<script>alert(1)</script>").get_data(as_text=True)
    assert "<script>alert(1)" not in page and "&lt;script&gt;" in page


def test_very_long_values_are_cut_before_checking(app, db_path):
    """100,000 nines: cut to 32 characters, then refused as far too big (not saved as 10^32)."""
    c = signed_up(app)
    r = add(c, price="9" * 100_000)
    assert r.status_code == 422 and len(r.get_data(as_text=True)) < 200_000
    assert saved(db_path) == []


def test_trade_changes_are_written_to_the_security_log(app, db_path):
    c = signed_up(app)
    add(c)
    tid = saved(db_path)[0]["id"]
    c.post(f"/trades/{tid}/delete", data={"csrf": token(c)})
    conn = db.get_connection(db_path)
    events = [r["event"] for r in conn.execute("SELECT event FROM security_log ORDER BY id")]
    conn.close()
    assert "trade_added" in events and "trade_deleted" in events


def test_trade_pages_are_not_cached(app):
    c = signed_up(app)
    assert c.get("/trades").headers["Cache-Control"] == "no-store"


# ---------- Prices for a stock nobody has traded yet ----------

def test_a_new_stock_downloads_its_prices_first(app, downloads):
    c = signed_up(app)
    add(c, ticker="O39.SI", price="14.00")
    assert downloads == [["O39.SI"]]               # OCBC had no prices; the STI ETF already went back far enough


def test_a_known_stock_on_a_covered_date_downloads_nothing(app, downloads):
    c = signed_up(app)
    add(c)
    assert downloads == []


def test_if_the_download_fails_the_trade_is_still_saved(app, db_path):
    app.config["MARKET_DOWNLOAD"] = lambda conn, tickers: False
    c = signed_up(app)
    r = add(c, ticker="O39.SI", price="14.00")
    assert len(saved(db_path)) == 1
    assert "next price update" in c.get(r.headers["Location"]).get_data(as_text=True)
