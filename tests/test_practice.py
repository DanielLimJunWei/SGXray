"""The practice portfolio (w320): pretend money, real prices, real fees, and never mixed with real trades."""

import re

import pytest

import auth
import db
import practice
from test_trades import GOOD, add, app, db_path, downloads, saved, signed_up, token  # noqa: F401  (fixtures)

# test_trades' database: D05.SI and ES3.SI each have one saved close, $30.00 on 2 Jan 2025.


def buy(c, ticker="D05.SI", quantity="100", side="BUY", **extra):
    return c.post("/practice/trades", data={"csrf": token(c, "/practice/trades"), "ticker": ticker, "side": side,
                                            "quantity": quantity, **extra})


def twin_trades(db_path, email="ann@example.com"):
    conn = db.get_connection(db_path)
    owner = db.get_user_by_email(conn, email)["id"]
    rows = [dict(t) for t in db.get_trades(conn, db.practice_user(conn, owner)["id"])]
    conn.close()
    return rows


def text(r):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.get_data(as_text=True)))


def test_practice_needs_a_login(app):
    c = app.test_client()
    for path in ("/practice", "/practice/trades", "/practice/reset"):
        r = c.get(path)
        assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_a_practice_buy_uses_the_latest_close_and_a_real_fee(app, db_path):
    c = signed_up(app)
    r = buy(c, price="1", date="2020-01-01")                     # a price or date typed in is ignored
    assert r.status_code == 302
    [t] = twin_trades(db_path)
    assert (t["trade_date"], t["price"], t["quantity"]) == ("2025-01-02", 30.0, 100)
    # $3,000: commission max(0.1%, $10) = $10, SGX 0.04% = $1.20, GST 9% of $11.20 = $1.01 -> $12.21
    assert t["fees"] == pytest.approx(12.21)
    assert practice.fee(3000) == {"commission": 10.0, "sgx": 1.2, "gst": 1.01, "total": 12.21}
    assert "$6,987.79" in text(c.get("/practice"))               # $10,000 - $3,012.21


def test_you_cant_spend_more_pretend_cash_than_you_have(app, db_path):
    c = signed_up(app)
    r = buy(c, quantity="400")                                   # $12,000 > $10,000
    assert r.status_code == 422 and "of pretend cash" in text(r)
    assert twin_trades(db_path) == []


def test_selling_gives_cash_back_and_you_cant_sell_what_you_dont_hold(app, db_path):
    c = signed_up(app)
    assert buy(c, side="SELL").status_code == 422                # nothing held yet
    buy(c)
    assert buy(c, quantity="40", side="SELL").status_code == 302
    conn = db.get_connection(db_path)
    owner = db.get_user_by_email(conn, "ann@example.com")["id"]
    cash = practice.cash(conn, db.practice_user(conn, owner)["id"])
    conn.close()
    assert cash == pytest.approx(10_000 - 3012.21 + 1200 - practice.fee(1200)["total"])


def test_practice_and_real_trades_never_mix(app, db_path):
    c = signed_up(app)
    add(c)                                                       # a real trade
    buy(c, ticker="ES3.SI")                                      # a practice trade
    assert [t["ticker"] for t in saved(db_path)] == ["D05.SI"]
    assert [t["ticker"] for t in twin_trades(db_path)] == ["ES3.SI"]
    real = c.get("/portfolio").get_data(as_text=True)
    assert "ES3.SI" not in real.split('id="holdings-title"')[1].split("</table>")[0]


def test_someone_elses_practice_is_invisible(app):
    ann = signed_up(app)
    buy(ann, note="Ann's practice reason")
    bob = signed_up(app, "bob@example.com")
    for path in ("/practice", "/practice/trades"):
        page = bob.get(path).get_data(as_text=True)
        assert "Ann&#39;s practice reason" not in page and "Ann's practice reason" not in page
    assert "$10,000.00" in text(bob.get("/practice"))


def test_the_practice_twin_cant_log_in_reset_or_be_signed_up_for(app, db_path):
    c = signed_up(app)
    buy(c)
    conn = db.get_connection(db_path)
    owner = db.get_user_by_email(conn, "ann@example.com")["id"]
    twin = db.practice_user(conn, owner)
    assert db.practice_user(conn, owner)["id"] == twin["id"]     # made once, then reused
    assert auth.check_login(conn, twin["email"], db.PRACTICE_HASH) is None
    conn.close()
    assert auth.email_problem(twin["email"]) is not None          # .invalid can't be signed up with
    other = app.test_client()
    other.post("/forgot", data={"csrf": token(other, "/forgot"), "email": twin["email"]})
    conn = db.get_connection(db_path)
    assert conn.execute("SELECT COUNT(*) FROM password_resets").fetchone()[0] == 0
    conn.close()


def test_the_practice_portfolio_is_deleted_with_its_account(app, db_path):
    c = signed_up(app)
    buy(c)
    conn = db.get_connection(db_path)
    owner = db.get_user_by_email(conn, "ann@example.com")["id"]
    with conn:
        conn.execute("DELETE FROM users WHERE id = ?", (owner,))
    assert conn.execute("SELECT COUNT(*) FROM users WHERE practice_of IS NOT NULL").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0
    conn.close()


def test_your_own_broker_fee_is_saved_and_used(app, db_path):
    c = signed_up(app)
    r = c.post("/practice/fees", data={"csrf": token(c, "/practice/trades"), "rate": "0.08", "minimum": "5"})
    assert r.status_code == 302
    buy(c)
    [t] = twin_trades(db_path)
    assert t["fees"] == pytest.approx(practice.fee(3000, 0.0008, 5)["total"])      # $5 min + $1.20 + GST
    assert "your broker" in text(c.get("/practice/trades"))
    c.post("/practice/fees", data={"csrf": token(c, "/practice/trades"), "typical": "1"})
    assert "a typical broker" in text(c.get("/practice/trades"))


@pytest.mark.parametrize("rate, minimum", [("5", "10"), ("-1", "10"), ("0.1", "500"), ("abc", "10")])
def test_impossible_fees_are_refused(app, rate, minimum):
    c = signed_up(app)
    r = c.post("/practice/fees", data={"csrf": token(c, "/practice/trades"), "rate": rate, "minimum": minimum})
    assert r.status_code == 422


@pytest.mark.parametrize("fields", [{"ticker": "NOPE.SI"}, {"quantity": "0"}, {"quantity": "1.5"},
                                    {"quantity": "9999999"}, {"side": "HOLD"}, {"note": "x" * 281}])
def test_bad_practice_trades_are_refused(app, db_path, fields):
    c = signed_up(app)
    assert buy(c, **fields).status_code == 422
    assert twin_trades(db_path) == []


def test_every_listed_stock_can_be_chosen_and_prices_come_when_you_trade(app, db_path, downloads):
    """OCBC has no saved price: it's still listed, and buying it downloads its prices first."""
    c = signed_up(app)
    page = c.get("/practice/trades").get_data(as_text=True)
    assert 'value="O39.SI"' in page and "price fetched when you trade" in page

    def download(conn, tickers):
        downloads.append(tickers)
        db.save_prices(conn, "O39.SI", [("2025-01-02", 14.0)])
        return True
    app.config["MARKET_DOWNLOAD"] = download
    assert buy(c, ticker="O39.SI").status_code == 302
    assert downloads == [["O39.SI"]]                                   # the STI ETF already has prices
    [t] = twin_trades(db_path)
    assert (t["ticker"], t["price"], t["trade_date"]) == ("O39.SI", 14.0, "2025-01-02")


def test_if_prices_cant_be_downloaded_the_trade_says_why(app, db_path):
    c = signed_up(app)                                                 # the test downloader saves nothing
    r = buy(c, ticker="O39.SI")
    assert r.status_code == 422 and "no closing price saved yet" in text(r)
    assert twin_trades(db_path) == []


def test_cant_find_your_stock_works_from_practice_and_comes_back_here(app):
    c = signed_up(app)
    page = c.get("/practice/trades").get_data(as_text=True)
    assert 'name="then" value="practice"' in page
    r = c.post("/trades/lookup", data={"csrf": token(c, "/practice/trades"), "code": "O39", "then": "practice"})
    assert r.status_code == 302 and "/practice/trades?added=O39.SI" in r.headers["Location"]
    assert "is in the list now, and picked below" in c.get(r.headers["Location"]).get_data(as_text=True)
    r = c.post("/trades/lookup", data={"csrf": token(c, "/practice/trades"), "code": "not a code!", "then": "practice"})
    assert r.status_code == 422 and "Practice trades" in r.get_data(as_text=True)    # the error stays on practice


def test_the_lookup_only_ever_goes_back_to_one_of_two_pages(app):
    c = signed_up(app)
    r = c.post("/trades/lookup", data={"csrf": token(c, "/trades"), "code": "O39", "then": "https://evil.example"})
    assert r.status_code == 302 and r.headers["Location"].startswith("/trades?added=O39.SI")


def test_start_over_asks_first_then_clears_only_practice(app, db_path):
    c = signed_up(app)
    add(c)
    buy(c)
    assert "Start the practice portfolio over?" in c.get("/practice/reset").get_data(as_text=True)
    assert twin_trades(db_path) != []
    assert app.test_client().post("/practice/reset").status_code in (302, 400)   # no token / no login: nothing
    r = c.post("/practice/reset", data={"csrf": token(c, "/practice/reset")})
    assert r.status_code == 302 and twin_trades(db_path) == []
    assert len(saved(db_path)) == 1                                              # the real trade is untouched


def test_the_practice_pages_follow_the_page_rule_and_say_practice(app):
    from test_page_rules import check_page_rules, check_reason_words
    c = signed_up(app)
    empty = c.get("/practice").get_data(as_text=True)
    assert "No practice trades yet" in empty and "Practice portfolio" in empty
    buy(c, note="Practising")
    page = c.get("/practice").get_data(as_text=True)
    check_page_rules(page)
    check_reason_words(page)
    assert "Practice · pretend money, real SGX prices" in page and "Make a practice trade" in page
    assert c.get("/practice").headers["Cache-Control"] == "no-store"
    check_page_rules(c.get("/practice/trades").get_data(as_text=True))


def test_the_top_bar_links_to_practice_when_logged_in(app):
    assert 'href="/practice"' not in app.test_client().get("/").get_data(as_text=True)
    assert 'href="/practice"' in signed_up(app).get("/").get_data(as_text=True)
