"""The watchlist (s14): stocks you're researching. Your own list only, every value a number or a reason in words,
and the facts right: the move since you added it allows for splits, and a watched stock always has a year of
prices. No internet: downloads are faked."""

import re
from datetime import date, datetime

import pytest

import db
import market
import updater
import watchlist
from test_trades import app, db_path, downloads, signed_up, token  # noqa: F401  (fixtures)

SGT = market.SGT


def uid_of(db_path, email="ann@example.com"):
    conn = db.get_connection(db_path)
    uid = db.get_user_by_email(conn, email)["id"]
    conn.close()
    return uid


def watch(client, ticker="D05.SI", note=""):
    return client.post("/watchlist", data={"csrf": token(client, "/watchlist"), "ticker": ticker, "note": note})


# ---------- Adding, removing, notes ----------

def test_adding_a_stock_saves_it_with_todays_date_and_fetches_its_prices(app, db_path, downloads):
    c = signed_up(app)
    r = watch(c, "D05.SI", "Steady   dividends\n")
    assert r.status_code == 302 and "watched=D05.SI" in r.headers["Location"]
    conn = db.get_connection(db_path)
    [w] = db.get_watchlist(conn, uid_of(db_path))
    assert (w["ticker"], w["note"]) == ("D05.SI", "Steady dividends")          # tidied to one line
    assert date.fromisoformat(w["added_on"]) <= date.today()
    assert downloads == [["D05.SI"]]                                          # its year of prices, straight away
    conn.close()


def test_adding_it_twice_keeps_the_first_date(app, db_path):
    c = signed_up(app)
    watch(c)
    r = watch(c)
    assert "already=D05.SI" in r.headers["Location"]
    assert "was already on your watchlist" in c.get(r.headers["Location"]).get_data(as_text=True)


def test_only_stocks_in_sgxrays_list_can_be_added(app):
    c = signed_up(app)
    r = watch(c, "EVIL.SI")
    assert r.status_code == 422 and "Choose a stock" in r.get_data(as_text=True)


def test_a_long_note_is_refused_not_cut(app):
    c = signed_up(app)
    r = watch(c, "D05.SI", "x" * 281)
    assert r.status_code == 422 and "longer than 280" in r.get_data(as_text=True)


def test_the_list_holds_at_most_50(app, db_path):
    c = signed_up(app)
    conn = db.get_connection(db_path)
    uid = uid_of(db_path)
    for i in range(db.WATCH_MAX):
        t = f"T{i:02d}.SI"
        db.save_instrument(conn, t, f"Test {i}", "stock", None)
        db.watch(conn, uid, t, "2026-11-02")
    conn.close()
    r = watch(c, "D05.SI")
    assert r.status_code == 422 and "the most it holds" in r.get_data(as_text=True)


def test_removing_and_editing_the_note(app, db_path):
    c = signed_up(app)
    watch(c)
    r = c.post("/watchlist/D05.SI/note", data={"csrf": token(c, "/watchlist"), "note": "Read the annual report"})
    assert "note=saved" in r.headers["Location"]
    conn = db.get_connection(db_path)
    assert db.get_watchlist(conn, uid_of(db_path))[0]["note"] == "Read the annual report"
    r = c.post("/watchlist/D05.SI/remove", data={"csrf": token(c, "/watchlist")})
    assert "removed=D05.SI" in r.headers["Location"] and db.get_watchlist(conn, uid_of(db_path)) == []
    conn.close()


# ---------- Only yours ----------

def test_nobody_else_can_see_or_change_your_watchlist(app, db_path):
    ann = signed_up(app)
    watch(ann, "D05.SI", "Ann's private reason")
    bob = signed_up(app, "bob@example.com")
    assert "Ann's private reason" not in bob.get("/watchlist").get_data(as_text=True)
    # Bob removing or re-noting "D05.SI" touches only his own (empty) list: 404, and Ann's row is untouched.
    assert bob.post("/watchlist/D05.SI/remove", data={"csrf": token(bob, "/watchlist")}).status_code == 404
    assert bob.post("/watchlist/D05.SI/note", data={"csrf": token(bob, "/watchlist"), "note": "hi"}).status_code == 404
    conn = db.get_connection(db_path)
    assert db.get_watchlist(conn, uid_of(db_path))[0]["note"] == "Ann's private reason"
    conn.close()


def test_logged_out_and_forged_requests_change_nothing(app, db_path):
    assert app.test_client().get("/watchlist").status_code == 302                   # to the login page
    c = signed_up(app)
    assert c.post("/watchlist", data={"ticker": "D05.SI"}).status_code == 400      # no form token
    conn = db.get_connection(db_path)
    assert db.get_watchlist(conn, uid_of(db_path)) == []
    conn.close()


def test_your_watchlist_is_in_your_data_download_and_goes_when_you_delete(app, db_path):
    c = signed_up(app)
    watch(c, "D05.SI", "why")
    data = c.get("/account/data").get_json()
    assert [(w["ticker"], w["note"]) for w in data["watchlist"]] == [("D05.SI", "why")]
    conn = db.get_connection(db_path)
    uid = uid_of(db_path)
    assert db.delete_user(conn, uid)
    assert conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0] == 0
    conn.close()


# ---------- The numbers ----------

@pytest.fixture
def ann(conn):
    uid = db.create_user(conn, "w@example.com", "x")
    return uid


def test_the_move_since_you_added_it_allows_for_a_bonus_issue(conn, ann):
    db.save_prices(conn, "D05.SI", [("2026-09-01", 40.0), ("2026-11-05", 38.0)])
    db.save_actions(conn, "D05.SI", [("2026-10-01", 1.1)])         # 1-for-10 bonus: 1 share became 1.1
    db.watch(conn, ann, "D05.SI", "2026-09-01")
    [r] = watchlist.rows(conn, ann)
    # Without the bonus: 38/40 = -5%. Really: 1.1 x 38 = 41.80 for the share you'd have had = +4.5%.
    assert r["since"] == pytest.approx(41.8 / 40 - 1) and r["since_from"] == "2026-09-01"


def test_every_value_is_a_number_or_a_reason(conn, ann):
    db.save_instrument(conn, "NEW.SI", "New Listing", "stock", None)
    db.watch(conn, ann, "NEW.SI", "2026-11-05")                        # no price saved at all
    db.save_prices(conn, "D05.SI", [("2026-11-05", 70.0)])
    db.watch(conn, ann, "D05.SI", "2026-11-05")                        # the latest close is the day it was added
    rows = {r["ticker"]: r for r in watchlist.rows(conn, ann)}
    assert (rows["NEW.SI"]["since_reason"], rows["NEW.SI"]["range_reason"]) == ("no-price", "no-price")
    assert (rows["D05.SI"]["since_reason"], rows["D05.SI"]["range_reason"]) == ("no-move-yet", "too-soon")
    assert rows["D05.SI"]["since"] is None


def test_the_page_never_shows_a_blank_or_n_a(app, db_path):
    c = signed_up(app)
    conn = db.get_connection(db_path)
    db.save_instrument(conn, "NEW.SI", "New Listing", "stock", None)
    db.watch(conn, uid_of(db_path), "NEW.SI", "2026-11-05")
    db.watch(conn, uid_of(db_path), "D05.SI", "2025-01-02")
    conn.close()
    html = c.get("/watchlist").get_data(as_text=True)
    table = html[html.index("<tbody>"):html.index("</tbody>")]
    assert ">No price yet</button>" in table
    assert not re.search(r"<td[^>]*>\s*</td>", table)                                  # no empty cell
    assert not re.search(r">\s*(n/a|nan|NaN|None)\s*<", table)


def test_a_watched_stock_always_gets_a_year_of_prices(conn, ann):
    end = date(2026, 11, 6)
    db.add_trade(conn, ann, "Z74.SI", "2026-11-02", "BUY", 100, 4.0)   # someone traded it only last week
    assert market._history_start(conn, "Z74.SI", end) == date(2026, 11, 2)
    db.watch(conn, ann, "Z74.SI", "2026-11-05")
    assert market._history_start(conn, "Z74.SI", end) == date(2025, 11, 6)


def test_the_daily_update_includes_watched_stocks(conn, ann, monkeypatch):
    db.watch(conn, ann, "C38U.SI", "2026-11-05")
    seen = {}
    monkeypatch.setattr(market, "update_actions", lambda c, t: seen.setdefault("tickers", t) and [])
    monkeypatch.setattr(market, "update_prices", lambda c, t: [])
    monkeypatch.setattr(market, "update_dividends", lambda c, t: [])
    monkeypatch.setattr(market, "update_announced", lambda c, t: [])
    updater.download_all(conn)
    assert "C38U.SI" in seen["tickers"]
