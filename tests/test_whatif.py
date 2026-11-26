"""The "what if" calculator (s12). Every expected number is worked out by hand in the comments, with the same rules
as SGXray's monthly plans: the 1st (or the next trading day within a week), fee first, whole shares only, splits
before that day's buy, dividends on shares held before the ex-date. No internet: downloads are faked."""

import re

import pytest

import db
import market
import updater
import whatif
from test_trades import app, db_path, downloads  # noqa: F401  (fixtures)


@pytest.fixture
def plan(conn):
    """D05.SI made-up prices, $100 a month, fee 1% with a $1 minimum (so $1.00 every month)."""
    db.save_prices(conn, "D05.SI", [
        ("2025-01-02", 9.90),     # Jan: (100 - 1) / 9.90 = 10 shares, cost 99.00 + 1 = 100.00
        ("2025-02-03", 11.00),    # Feb: 99 / 11 = 9 shares, cost 100.00
        ("2025-03-12", 12.00),    # Mar: first close 11 days after the 1st: no trading that week, no buy
        ("2025-04-01", 120.00),   # Apr: one share costs more than $99: no buy
        ("2025-05-02", 12.50),    # May: 99 / 12.5 = 7.92 -> 7 shares, cost 87.50 + 1 = 88.50
    ])
    db.save_actions(conn, "D05.SI", [("2025-04-10", 1.1)])         # 1-for-10 bonus: 19 shares -> 20
    db.save_dividends(conn, "D05.SI", [("2025-02-03", 0.50),       # ex-date = Feb's buy day: only Jan's 10 count
                                       ("2025-03-05", 0.50)])      # 19 shares held
    return whatif.simulate(conn, "D05.SI", 100, "2024-11", 0.01, 1.0)


def test_the_monthly_plan_replays_by_hand(plan):
    r = plan
    assert [(b["date"], b["shares"], b["cost"]) for b in r.buys] == [
        ("2025-01-02", 10, 100.00), ("2025-02-03", 9, 100.00), ("2025-05-02", 7, 88.50)]
    assert r.skipped == [("2024-11", "no-price"), ("2024-12", "no-price"),       # before the first saved close
                         ("2025-03", "no-trading"), ("2025-04", "too-dear")]
    assert [(d["ex_date"], d["shares"], d["total"]) for d in r.dividends] == [("2025-02-03", 10, 5.00),
                                                                             ("2025-03-05", 19, 9.50)]
    assert r.shares == 27                                   # 10 + 9 = 19, bonus -> 20, + 7
    assert (r.money_in, r.fees, r.dividends_total) == (288.50, 3.00, 14.50)
    assert r.worth == 337.50                                # 27 x 12.50
    assert r.profit == 63.50                                # 337.50 + 14.50 - 288.50
    assert r.days == 120 and r.total_return == pytest.approx(63.50 / 288.50)


def test_no_gain_is_a_zero_yearly_rate(conn):
    # 13 months at a flat $2.00 and no fee: 50 shares a month for $100, worth exactly what went in.
    days = [f"{y}-{m:02d}-02" for y, m in [(2024, m) for m in range(1, 13)] + [(2025, 1)]]
    db.save_prices(conn, "ES3.SI", [(d, 2.0) for d in days])
    r = whatif.simulate(conn, "ES3.SI", 100, "2024-01", 0.0, 0.0)
    assert (len(r.buys), r.shares, r.money_in, r.worth, r.profit) == (13, 650, 1300.0, 1300.0, 0.0)
    assert r.days >= 365 and r.yearly == pytest.approx(0.0, abs=1e-9)


def test_rounding_half_a_cent_up_like_everywhere_else(conn):
    # 75 shares at $2.573 + a $5 fee = $197.975: SGXray rounds half a cent up (fmt.cents), so $197.98.
    db.save_prices(conn, "ES3.SI", [("2020-05-04", 2.573)])
    r = whatif.simulate(conn, "ES3.SI", 200, "2020-05", 0.003, 5.0)
    assert r.buys[0]["shares"] == 75 and r.buys[0]["cost"] == 197.98


def test_the_chart_draws_money_in_as_steps_and_ends_at_the_latest_value(plan):
    c = whatif.chart(plan)
    assert c["money"].startswith("M") and "H" in c["money"] and "V" in c["money"]
    assert len(plan.path) == 5 and plan.path[-1] == ("2025-05-02", 288.50, 337.50 + 14.50)
    assert [label for _, label in c["grid"]][0] == "$0"


def test_the_form_refuses_what_it_cant_use(conn):
    bad = {"ticker": "EVIL.SI", "amount": "five", "start": "2009-12", "fee_rate": "9", "fee_min": "-1"}
    values, problems = whatif.from_args(conn, bad)
    assert len(problems) == 5
    assert whatif.from_args(conn, {"amount": "nan"})[1] == ["The monthly amount must be between 10 and 100,000."]
    assert whatif.from_args(conn, {"start": "2999-01"})[1]                     # the future
    values, problems = whatif.from_args(conn, {})                              # nothing typed: the defaults
    assert problems == [] and values == {**whatif.DEFAULT}


# ---------- The page ----------

def test_anyone_can_use_it_and_older_prices_are_fetched_once(app, downloads):
    c = app.test_client()                                                      # not logged in
    r = c.get("/what-if")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Money in" in html
    assert downloads == [["ES3.SI"]]               # saved prices start in 2025, the default plan in 2015
    c.get("/what-if")
    assert downloads == [["ES3.SI"]]               # asked for once: the daily update keeps it from then on


def test_the_download_limit_hands_over_to_the_daily_update(app, db_path, downloads, monkeypatch):
    monkeypatch.setattr(whatif, "DOWNLOADS_PER_HOUR", 1)
    c = app.test_client()
    c.get("/what-if")
    html = c.get("/what-if?ticker=D05.SI").get_data(as_text=True)
    assert downloads == [["ES3.SI"]] and "next daily update" in html
    conn = db.get_connection(db_path)
    assert db.history_since(conn, "D05.SI") == "2015-01-01"                   # still asked for, so it comes later
    conn.close()


def test_a_bad_form_says_why(app):
    r = app.test_client().get("/what-if?ticker=EVIL.SI&amount=1")
    html = r.get_data(as_text=True)
    assert r.status_code == 422 and "Choose a stock" in html and "between 10 and 100,000" in html


def test_the_page_never_shows_a_blank_or_n_a(app, db_path):
    conn = db.get_connection(db_path)
    db.save_prices(conn, "ES3.SI", [(f"2025-{m:02d}-02", 3.0 + m / 10) for m in range(2, 13)])
    conn.close()
    html = app.test_client().get("/what-if?start=2025-01").get_data(as_text=True)
    main = html[html.index('<div class="page wrap whatif">'):html.index("</main>") if "</main>" in html else None]
    assert not re.search(r">\s*(n/a|nan|NaN|None)\s*<", main)
    assert not re.search(r"<td[^>]*>\s*</td>", main)


# ---------- Keeping the longer history ----------

def test_a_wanted_history_reaches_back_and_stays_in_the_daily_update(conn, monkeypatch):
    from datetime import date
    end = date(2026, 11, 6)
    assert market._history_start(conn, "C38U.SI", end) == date(2025, 11, 6)     # nobody trades it: a year
    assert db.want_history(conn, "C38U.SI", "2015-01-01")
    assert not db.want_history(conn, "C38U.SI", "2016-01-01")                  # already reaches further back
    assert market._history_start(conn, "C38U.SI", end) == date(2015, 1, 1)
    seen = {}
    monkeypatch.setattr(market, "update_actions", lambda c, t: seen.setdefault("tickers", t) and [])
    monkeypatch.setattr(market, "update_prices", lambda c, t: [])
    monkeypatch.setattr(market, "update_dividends", lambda c, t: [])
    monkeypatch.setattr(market, "update_announced", lambda c, t: [])
    updater.download_all(conn)
    assert "C38U.SI" in seen["tickers"]
