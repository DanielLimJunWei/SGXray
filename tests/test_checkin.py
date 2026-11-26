"""The monthly check-in (s11). Expected numbers are worked out by hand in the comments."""

import re

import pytest

import checkin
import db
from test_trades import app, db_path, downloads, signed_up, token  # noqa: F401  (fixtures)

DAYS = ["2026-09-15", "2026-09-30", "2026-10-15", "2026-10-30"]


@pytest.fixture
def october(conn, user_id):
    db.save_prices(conn, "D05.SI", list(zip(DAYS, [30.0, 32.0, 33.0, 35.0])))
    db.save_prices(conn, "ES3.SI", [(d, 3.0) for d in DAYS])            # a flat STI ETF: 0% whatever you do
    db.add_trade(conn, user_id, "D05.SI", "2026-09-15", "BUY", 100, 30.0, 0)
    db.add_trade(conn, user_id, "D05.SI", "2026-10-15", "BUY", 50, 33.0, 0)
    db.save_dividends(conn, "D05.SI", [("2026-10-15", 0.50)])           # ex-date = the buy day: only the first 100
    return user_id


def test_a_month_by_hand(conn, october):
    r = checkin.summary(conn, october, "2026-10")
    assert (r["from_day"], r["to_day"]) == ("2026-09-30", "2026-10-30")
    assert r["worth_start"] == 3200 and r["worth_end"] == 5250         # 100 x $32, then 150 x $35
    assert r["added"] == 1650 and r["dividends"] == 50                 # 50 x $33; 100 x $0.50
    assert r["market"] == 400                                          # 5,250 - 3,200 - 1,650
    # Time-weighted: 15 Oct (4,950 - 1,650 + 50) / 3,200 = 1.046875; 30 Oct 5,250 / 4,950.
    assert r["you"] == pytest.approx(1.046875 * 5250 / 4950 - 1) and r["sti"] == pytest.approx(0.0)
    assert (r["buys"], r["sells"]) == (1, 0)
    assert r["paid"] == [{"ticker": "D05.SI", "ex_date": "2026-10-15", "total": 50.0}]
    assert r["mover"] == ("D05.SI", pytest.approx(35 / 32 - 1))
    assert not r["so_far"] and not r["missing_price"]


def test_the_first_month_starts_from_nothing(conn, october):
    r = checkin.summary(conn, october, "2026-09")
    assert r["from_day"] is None and r["worth_start"] == 0 and r["added"] == 3000 and r["worth_end"] == 3200


def test_which_months_and_the_default(conn, october):
    assert checkin.months(conn, october) == ["2026-10", "2026-09"]
    assert checkin.default_month(["2026-10", "2026-09"], "2026-10-30") == "2026-09"     # October isn't over
    assert checkin.default_month(["2026-10", "2026-09"], "2026-11-02") == "2026-10"
    assert checkin.default_month(["2026-10"], "2026-10-30") == "2026-10"                # only one month so far
    assert checkin.summary(conn, october, "2025-01") is None


# ---------- The page ----------

def test_the_page_for_you_only(app):
    assert app.test_client().get("/check-in").status_code == 302                         # logged out: to log in
    c = signed_up(app)
    assert "add your first trade" in c.get("/check-in").get_data(as_text=True)
    c.post("/trades", data={"csrf": token(c), "ticker": "D05.SI", "date": "2025-01-02", "side": "BUY",
                            "quantity": "10", "price": "30", "fees": ""})
    r = c.get("/check-in?month=../../etc")                                             # nonsense: the default month
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Money you added" in html
    assert not re.search(r">\s*(n/a|nan|NaN|None)\s*<", html)
