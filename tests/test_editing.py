"""Edit notes in place, undo a practice trade until the next close, the holdings "Change" options, "Add a stock
I already own", and the "check this price" warning (17 Nov 2026).

Written as the abuse cases: someone else's trade id, a note that's too long or full of HTML, a "back" address
from the form, undoing a trade after the next close (hindsight), a share count that isn't a number, a month in
the future or at a weekend.
"""

import re
from datetime import date

import pytest

import db
import practice
import trades
from test_practice import buy, text, twin_trades
from test_trades import MONDAY, add, app, db_path, downloads, saved, signed_up, token  # noqa: F401  (fixtures)


def note(c, trade_id, value, back="trades", practice_=False):
    path = f"/practice/trades/{trade_id}/note" if practice_ else f"/trades/{trade_id}/note"
    page = "/practice/trades" if practice_ else "/trades"
    return c.post(path, data={"csrf": token(c, page), "note": value, "back": back})


# ---------- Edit note in place ----------

def test_a_note_can_be_added_changed_and_removed_without_touching_the_trade(app, db_path):
    c = signed_up(app)
    add(c)
    [t] = saved(db_path)
    r = note(c, t["id"], "  A bank I understand;\n holding 5+ years ")
    assert r.status_code == 302 and r.headers["Location"].endswith("/trades?note=saved")
    [after] = saved(db_path)
    assert after["note"] == "A bank I understand; holding 5+ years"              # tidied to one line
    assert {k: after[k] for k in ("ticker", "trade_date", "quantity", "price", "fees")} == \
           {k: t[k] for k in ("ticker", "trade_date", "quantity", "price", "fees")}
    assert "Note saved." in text(c.get("/trades?note=saved"))
    note(c, t["id"], "   ")
    assert saved(db_path)[0]["note"] is None                                      # emptied: removed


def test_the_note_form_is_on_the_trades_list_and_in_the_why_box(app, db_path):
    c = signed_up(app)
    add(c, note="Steady profits")
    [t] = saved(db_path)
    assert f'action="/trades/{t["id"]}/note"' in c.get("/trades").get_data(as_text=True)
    page = c.get("/portfolio").get_data(as_text=True)
    assert f'action="/trades/{t["id"]}/note"' in page and 'name="back" value="portfolio"' in page
    assert note(c, t["id"], "New reason", back="portfolio").headers["Location"].endswith("/portfolio?note=saved")


def test_a_note_over_280_characters_is_refused_and_says_why(app, db_path):
    c = signed_up(app)
    add(c, note="Short")
    [t] = saved(db_path)
    r = note(c, t["id"], "x" * 281)
    assert r.headers["Location"].endswith("?note=long") and saved(db_path)[0]["note"] == "Short"
    assert "longer than 280 characters" in text(c.get("/trades?note=long"))


def test_someone_elses_note_cant_be_edited(app, db_path):
    ann = signed_up(app)
    add(ann, note="Ann's reason")
    [t] = saved(db_path)
    bob = signed_up(app, "bob@example.com")
    assert note(bob, t["id"], "hacked").status_code == 404
    assert note(bob, t["id"], "hacked", practice_=True).status_code == 404           # nor through practice
    assert saved(db_path)[0]["note"] == "Ann's reason"


def test_a_note_needs_the_form_token_and_a_login(app, db_path):
    c = signed_up(app)
    add(c)
    [t] = saved(db_path)
    assert c.post(f"/trades/{t['id']}/note", data={"note": "x"}).status_code == 400
    assert app.test_client().post(f"/trades/{t['id']}/note", data={"note": "x"}).status_code in (302, 400)
    assert saved(db_path)[0]["note"] is None


def test_back_only_goes_to_one_of_two_pages_and_html_stays_text(app, db_path):
    c = signed_up(app)
    add(c)
    [t] = saved(db_path)
    r = c.post(f"/trades/{t['id']}/note", data={"csrf": token(c), "note": "<script>alert(1)</script>",
                                                 "back": "https://evil.example/"})
    assert r.headers["Location"].startswith("/trades?")
    page = c.get("/trades").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page


def test_practice_notes_can_be_edited_too(app, db_path):
    c = signed_up(app)
    buy(c, note="Practising")
    [t] = twin_trades(db_path)
    r = note(c, t["id"], "Changed my mind about why", practice_=True)
    assert r.headers["Location"].endswith("/practice/trades?note=saved")
    assert twin_trades(db_path)[0]["note"] == "Changed my mind about why"
    assert note(c, t["id"], "x", practice_=False).status_code == 404               # a practice trade isn't a real one


# ---------- Practice: undo until the next close ----------

def test_a_practice_trade_can_be_undone_until_the_next_close(app, db_path):
    c = signed_up(app)
    buy(c)
    [t] = twin_trades(db_path)
    page = text(c.get("/practice/trades"))
    assert "Undo" in page and "until the next close" in page
    r = c.post(f"/practice/trades/{t['id']}/undo", data={"csrf": token(c, "/practice/trades")})
    assert r.status_code == 302 and twin_trades(db_path) == []
    assert "$10,000.00" in text(c.get("/practice/trades?undone=1"))                   # the cash is back


def test_after_the_next_close_a_practice_trade_is_locked(app, db_path):
    c = signed_up(app)
    buy(c)
    [t] = twin_trades(db_path)
    conn = db.get_connection(db_path)
    db.save_prices(conn, "D05.SI", [("2025-01-03", 25.0)])                          # the next close: it fell
    conn.close()
    assert "locked" in text(c.get("/practice/trades"))
    r = c.post(f"/practice/trades/{t['id']}/undo", data={"csrf": token(c, "/practice/trades")})
    assert r.status_code == 422 and "hindsight" in text(r)
    assert len(twin_trades(db_path)) == 1


def test_undoing_a_buy_that_a_later_sale_needs_is_refused(app, db_path):
    c = signed_up(app)
    buy(c)
    buy(c, side="SELL", quantity="50")
    first = twin_trades(db_path)[0]
    r = c.post(f"/practice/trades/{first['id']}/undo", data={"csrf": token(c, "/practice/trades")})
    assert r.status_code == 422 and "Undo the later sale first" in text(r)


def test_nobody_can_undo_someone_elses_or_a_real_trade(app, db_path):
    ann = signed_up(app)
    buy(ann)
    add(ann)
    [p] = twin_trades(db_path)
    [real] = saved(db_path)
    bob = signed_up(app, "bob@example.com")
    assert bob.post(f"/practice/trades/{p['id']}/undo", data={"csrf": token(bob, "/practice/trades")}).status_code == 404
    assert ann.post(f"/practice/trades/{real['id']}/undo", data={"csrf": token(ann, "/practice/trades")}).status_code == 404
    assert len(twin_trades(db_path)) == 1 and len(saved(db_path)) == 1


def test_undoable_is_about_the_stocks_own_next_close(db_path):
    conn = db.get_connection(db_path)
    t = {"ticker": "D05.SI", "trade_date": "2025-01-02"}
    assert practice.undoable(conn, t)
    db.save_prices(conn, "ES3.SI", [("2025-01-03", 31.0)])                          # another stock's close: no
    assert practice.undoable(conn, t)
    db.save_prices(conn, "D05.SI", [("2025-01-03", 31.0)])
    assert not practice.undoable(conn, t)
    conn.close()


# ---------- Holdings "Change" ----------

def test_holdings_rows_offer_change_on_your_own_and_practice_but_not_the_demo(app):
    c = signed_up(app)
    add(c)
    page = c.get("/portfolio").get_data(as_text=True)
    assert 'popovertarget="change-D05-SI-change"' in page and "Correct the number of shares" in page
    assert "/trades?stock=D05.SI#list-title" in page
    buy(c)
    practice_page = c.get("/practice").get_data(as_text=True)
    assert 'popovertarget="change-D05-SI-change"' in practice_page
    assert "Correct the number of shares" not in practice_page                    # practice trades at the close only
    assert 'popovertarget="change-' not in c.get("/demo").get_data(as_text=True)


def test_see_this_stocks_trades_filters_the_list(app):
    c = signed_up(app)
    add(c)
    add(c, ticker="ES3.SI", price="3.50")
    page = text(c.get("/trades?stock=ES3.SI"))
    assert "1 trade in SPDR Straits Times Index ETF" in page and "Show every trade" in page
    assert "2 trades" in text(c.get("/trades?stock=NOT-A-STOCK"))                  # an unknown ticker: everything


@pytest.mark.parametrize("hold, side, qty", [("150", "BUY", "50"), ("60", "SELL", "40"), ("1,000", "BUY", "900")])
def test_correcting_the_share_count_prefills_the_difference(app, hold, side, qty):
    c = signed_up(app)
    add(c)                                                                          # 100 DBS
    page = c.get(f"/trades?stock=D05.SI&hold={hold}").get_data(as_text=True)
    assert f'value="{side}" checked' in page or f'value="{side}"  checked' in page
    assert re.search(rf'name="quantity"[^>]*value="{qty}"', page)
    assert "Correction: my broker shows" in page and "Add the date and price" in page


def test_a_matching_or_nonsense_count_changes_nothing(app):
    c = signed_up(app)
    add(c)
    assert "Nothing to correct" in text(c.get("/trades?stock=D05.SI&hold=100"))
    assert "Type how many shares your broker shows" in text(c.get("/trades?stock=D05.SI&hold=lots"))
    assert "Type how many shares" in text(c.get("/trades?stock=D05.SI&hold=-5"))


# ---------- Add a stock I already own ----------

def existing(c, **fields):
    data = {"ticker": "D05.SI", "quantity": "200", "avg_cost": "35.20", "month": "2025-03", **fields}
    return c.post("/trades/existing", data={"csrf": token(c), **data})


def test_a_stock_you_already_own_is_saved_as_one_approximate_buy(app, db_path):
    c = signed_up(app)
    r = existing(c)
    assert r.status_code == 302 and "existing=1" in r.headers["Location"]
    [t] = saved(db_path)
    assert (t["side"], t["quantity"], t["price"], t["fees"], t["trade_date"], t["approx"]) == \
           ("BUY", 200, 35.2, 0.0, "2025-03-14", 1)                                # 15 Mar 2025 was a Saturday
    assert "approximate" in text(c.get("/trades"))
    assert "added as a stock you already own" in text(c.get("/portfolio"))


@pytest.mark.parametrize("fields, problem", [
    ({"quantity": "0"}, "Shares must be a whole number"),
    ({"quantity": "lots"}, "Shares must be a whole number"),
    ({"avg_cost": "-3"}, "Average cost is the price"),
    ({"avg_cost": "free"}, "Average cost is the price"),
    ({"month": "2999-01"}, "happened yet"),
    ({"month": "1980-01"}, "from 1990 on"),
    ({"month": "2025-13"}, "a month and year"),
    ({"month": "<b>"}, "a month and year"),
    ({"ticker": "EVIL.SI"}, "list"),
])
def test_impossible_existing_stocks_are_refused(app, db_path, fields, problem):
    c = signed_up(app)
    r = existing(c, **fields)
    assert r.status_code == 422 and problem.lower() in text(r).lower()
    assert saved(db_path) == []


def test_this_month_uses_a_weekday_no_later_than_today():
    values, problems = trades.existing_values({"ticker": "D05.SI", "quantity": "10", "avg_cost": "30",
                                               "month": "2026-11"}, today=date(2026, 11, 9))   # a Monday
    assert not problems and values["date"] == "2026-11-09"
    values, _ = trades.existing_values({"ticker": "D05.SI", "quantity": "10", "avg_cost": "30", "month": "2026-11"},
                                       today=date(2026, 11, 8))                                 # a Sunday
    assert values["date"] == "2026-11-06"


# ---------- Check this price ----------

def test_a_price_far_from_that_days_close_is_flagged_but_still_saved(app, db_path):
    c = signed_up(app)
    conn = db.get_connection(db_path)
    db.save_prices(conn, "D05.SI", [(MONDAY, 70.0)])
    conn.close()
    add(c, price="35.00")                                                           # half the close: a typo?
    add(c, price="69.50")                                                           # close to it: fine
    page = text(c.get("/trades"))
    assert page.count("check this price") == 1 and "SGX closed at $70.00 that day" in page
    assert len(saved(db_path)) == 2


def test_no_price_check_without_that_days_close_or_for_an_approximate_buy(db_path):
    conn = db.get_connection(db_path)
    assert trades.price_check(conn, {"ticker": "D05.SI", "trade_date": MONDAY, "price": 1.0}) is None   # no close
    db.save_prices(conn, "D05.SI", [(MONDAY, 70.0)])
    assert trades.price_check(conn, {"ticker": "D05.SI", "trade_date": MONDAY, "price": 1.0, "approx": 1}) is None
    assert trades.price_check(conn, {"ticker": "D05.SI", "trade_date": MONDAY, "price": 1.0}) == 70.0
    conn.close()


def test_the_new_pages_follow_the_page_rule(app):
    from test_page_rules import check_page_rules
    c = signed_up(app)
    add(c, note="Steady")
    buy(c)
    for path in ("/trades", "/trades?stock=D05.SI&hold=150", "/practice/trades", "/portfolio", "/practice"):
        check_page_rules(c.get(path).get_data(as_text=True))
