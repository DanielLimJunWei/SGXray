"""Regular savings plans (w314): each month's buy recorded like a bank's plan does it."""

import re
from datetime import date

import pytest

import db
import plans
from test_trades import app, db_path, downloads, saved, signed_up, token  # noqa: F401  (fixtures)


def prices(db_path, closes):
    conn = db.get_connection(db_path)
    db.save_prices(conn, "ES3.SI", closes)
    conn.close()


def add_plan(c, **fields):
    data = {"csrf": token(c, "/trades"), "ticker": "ES3.SI", "amount": "100", "day": "15", "start": "2025-01",
            "fee_rate": "0.82", "fee_min": "0", **fields}
    return c.post("/plans", data=data)


# ---------- The maths, worked by hand ----------

def test_the_fee_is_the_rate_with_a_minimum():
    assert plans.fee(100, 0.0082, 0) == 0.82                 # POSB-style 0.82%
    assert plans.fee(100, 0.003, 5) == 5.0                   # OCBC-style 0.3% or $5, whichever is higher
    assert plans.fee(5000, 0.003, 5) == 15.0


def test_whole_shares_only_after_the_fee():
    # $100, 0.82% fee = $0.82; $99.18 left at $3.50 a share = 28.34 -> 28 shares ($98.00); $1.18 not invested
    assert plans.buy(100, 3.50, 0.0082, 0) == (28, 0.82)
    assert plans.buy(100, 99.18, 0.0082, 0) == (1, 0.82)     # exactly enough for one share
    assert plans.buy(100, 99.19, 0.0082, 0) == (0, 0.82)     # a cent too dear: nothing that month


# ---------- Recording the months ----------

def test_each_month_is_bought_on_the_day_or_the_next_trading_day(app, db_path):
    # 15 Feb 2025 is a Saturday: that month's buy is Monday 17 Feb.
    prices(db_path, [("2025-01-15", 3.50), ("2025-02-14", 3.60), ("2025-02-17", 3.40), ("2025-03-14", 3.55),
                     ("2025-03-17", 3.58)])
    c = signed_up(app)
    r = add_plan(c)
    assert r.status_code == 302 and "plan_added=3" in r.headers["Location"]
    t = [(x["trade_date"], x["quantity"], x["price"], x["fees"]) for x in saved(db_path)]
    assert t == [("2025-01-15", 28, 3.50, 0.82), ("2025-02-17", 29, 3.40, 0.82), ("2025-03-17", 27, 3.58, 0.82)]
    # Feb: $99.18 / $3.40 = 29.17 -> 29. Mar: 15 Mar is a Saturday too -> Monday 17 Mar at $3.58: 27.70 -> 27.


def test_a_month_whose_buy_day_has_no_close_yet_waits(app, db_path):
    prices(db_path, [("2025-01-15", 3.50), ("2025-02-10", 3.60)])        # nothing on or after 15 Feb yet
    c = signed_up(app)
    add_plan(c)
    assert [x["trade_date"] for x in saved(db_path)] == ["2025-01-15"]
    prices(db_path, [("2025-02-17", 3.40)])                              # the close arrives
    conn = db.get_connection(db_path)
    assert plans.catch_up_all(conn) == 1
    assert plans.catch_up_all(conn) == 0                                 # never recorded twice
    conn.close()
    assert [x["trade_date"] for x in saved(db_path)] == ["2025-01-15", "2025-02-17"]


def test_the_trades_show_where_they_came_from(app, db_path):
    prices(db_path, [("2025-01-15", 3.50)])
    c = signed_up(app)
    add_plan(c, fee_rate="0.3", fee_min="5")
    [t] = saved(db_path)
    assert t["note"] == "Monthly plan: $100 on the 15th" and t["fees"] == 5.0 and t["quantity"] == 27
    page = c.get("/trades").get_data(as_text=True)
    assert "$100.00 on the 15th of each month since Jan 2025" in page
    assert "1 month bought: 27 shares for $99.50, fees included" in page          # 27 x 3.50 + 5


def test_stopping_keeps_the_past_and_records_nothing_new(app, db_path):
    prices(db_path, [("2025-01-15", 3.50)])
    c = signed_up(app)
    add_plan(c)
    pid = re.search(r'/plans/(\d+)/stop', c.get("/trades").get_data(as_text=True)).group(1)
    c.post(f"/plans/{pid}/stop", data={"csrf": token(c, "/trades")})
    prices(db_path, [("2025-02-17", 3.40), ("2025-03-17", 3.58)])
    conn = db.get_connection(db_path)
    assert plans.catch_up_all(conn) == 0
    conn.close()
    assert len(saved(db_path)) == 1 and "stopped" in c.get("/trades").get_data(as_text=True)


def test_deleting_a_plan_asks_first_then_removes_its_buys(app, db_path):
    prices(db_path, [("2025-01-15", 3.50), ("2025-02-17", 3.40)])
    c = signed_up(app)
    add_plan(c)
    pid = re.search(r'/plans/(\d+)/delete', c.get("/trades").get_data(as_text=True)).group(1)
    assert "Delete this plan and its buys?" in c.get(f"/plans/{pid}/delete").get_data(as_text=True)
    assert len(saved(db_path)) == 2
    c.post(f"/plans/{pid}/delete", data={"csrf": token(c, f"/plans/{pid}/delete")})
    assert saved(db_path) == []


def test_one_plan_buy_cant_be_deleted_alone_but_can_be_changed(app, db_path):
    prices(db_path, [("2025-01-15", 3.50)])
    c = signed_up(app)
    add_plan(c)
    tid = saved(db_path)[0]["id"]
    r = c.post(f"/trades/{tid}/delete", data={"csrf": token(c, f"/trades/{tid}/delete")})
    assert r.status_code == 422 and "recorded by your monthly plan" in r.get_data(as_text=True)
    r = c.post(f"/trades/{tid}/edit", data={"csrf": token(c, f"/trades/{tid}/edit"), "ticker": "ES3.SI",
                                           "date": "2025-01-15", "side": "BUY", "quantity": "28", "price": "3.51",
                                           "fees": "0.82"})
    assert r.status_code == 302 and saved(db_path)[0]["price"] == 3.51        # matched to the bank's statement
    conn = db.get_connection(db_path)
    assert plans.catch_up_all(conn) == 0                                       # the edited month isn't redone
    conn.close()


def test_someone_elses_plan_is_untouchable(app, db_path):
    prices(db_path, [("2025-01-15", 3.50)])
    ann = signed_up(app)
    add_plan(ann)
    pid = re.search(r'/plans/(\d+)/stop', ann.get("/trades").get_data(as_text=True)).group(1)
    bob = signed_up(app, "bob@example.com")
    assert bob.post(f"/plans/{pid}/stop", data={"csrf": token(bob, "/trades")}).status_code == 404
    assert bob.get(f"/plans/{pid}/delete").status_code == 404
    assert bob.post(f"/plans/{pid}/delete", data={"csrf": token(bob, "/trades")}).status_code == 404
    assert "Monthly plan: $100" not in bob.get("/trades").get_data(as_text=True)


@pytest.mark.parametrize("fields", [{"ticker": "NOPE.SI"}, {"amount": "0"}, {"amount": "abc"}, {"day": "29"},
                                    {"day": "0"}, {"fee_rate": "6"}, {"fee_min": "101"}, {"start": "2099-01"},
                                    {"start": "nonsense"}])
def test_impossible_plans_are_refused_with_a_reason(app, db_path, fields):
    c = signed_up(app)
    r = add_plan(c, **fields)
    assert r.status_code == 422 and 'class="form-error"' in r.get_data(as_text=True)
    conn = db.get_connection(db_path)
    assert conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 0
    conn.close()


def test_the_daily_update_records_new_plan_months(db_path, monkeypatch):
    import market
    import updater
    for name in ("update_actions", "update_prices", "update_dividends"):
        monkeypatch.setattr(market, name, lambda conn, tickers: [])
    called = []
    monkeypatch.setattr(plans, "catch_up_all", lambda conn: called.append(1) or 0)
    conn = db.get_connection(db_path)
    updater.download_all(conn)
    conn.close()
    assert called == [1]
