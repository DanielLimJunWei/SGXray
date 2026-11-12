"""Ups and downs (w305): biggest fall and how bumpy, from day-by-day growth with deposits taken out."""

import math
import statistics
from datetime import date, timedelta

import db
import risk
from explain import explain_risk
from test_trades import add, app, db_path, downloads, signed_up  # noqa: F401  (fixtures)


def weekdays(start, n):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def setup(db_path, closes, trades):
    """DBS closes on consecutive weekdays from 6 Jan 2025 (the STI ETF flat at $3.50), and the given trades."""
    conn = db.get_connection(db_path)
    days = weekdays(date(2025, 1, 6), len(closes))
    db.save_prices(conn, "D05.SI", [(d.isoformat(), c) for d, c in zip(days, closes)])
    db.save_prices(conn, "ES3.SI", [(d.isoformat(), 3.5) for d in days])
    uid = db.create_user(conn, "zed@example.com", "x")
    for day_index, side, qty in trades:
        db.add_trade(conn, uid, "D05.SI", days[day_index].isoformat(), side, qty, closes[day_index], 0.0)
    return conn, uid, days


def test_the_biggest_fall_is_measured_from_the_high_to_the_low_and_back(db_path):
    closes = [10, 11, 12, 9, 8, 10, 12, 13] + [13] * 60
    conn, uid, days = setup(db_path, closes, [(0, "BUY", 100)])
    r = risk.risk(conn, uid)
    conn.close()
    # By hand: high 12 (day 2), low 8 (day 4): 8 / 12 - 1 = -33.3%. Back to 12 on day 6.
    assert math.isclose(r["you"]["pct"], 8 / 12 - 1)
    assert (r["you"]["peak_day"], r["you"]["low_day"], r["you"]["back_day"]) == (days[2], days[4], days[6])
    assert r["you"]["now_pct"] == 0                                   # 13 is the high now


def test_adding_money_is_never_counted_as_a_rise_or_a_fall(db_path):
    """Flat price, but a big buy halfway: the value jumps, yet there's no gain, no fall and no bumpiness."""
    closes = [10.0] * 80
    conn, uid, _ = setup(db_path, closes, [(0, "BUY", 100), (40, "BUY", 1000)])
    r = risk.risk(conn, uid)
    conn.close()
    assert r["you"]["pct"] == 0 and r["you"]["peak_day"] is None
    assert r["you"]["vol"] == 0


def test_bumpiness_is_the_daily_standard_deviation_times_root_252(db_path):
    closes = [10 * (1.01 if i % 2 else 0.99) ** (i % 2) for i in range(70)]   # alternates 10.00 and 10.10
    closes = [round(c, 2) for c in closes]
    conn, uid, _ = setup(db_path, closes, [(0, "BUY", 100)])
    r = risk.risk(conn, uid)
    conn.close()
    returns = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]     # plain arithmetic
    assert math.isclose(r["you"]["vol"], statistics.stdev(returns) * math.sqrt(252), rel_tol=1e-9)
    assert r["sti"]["vol"] == 0                                                   # the flat STI ETF


def test_under_60_trading_days_bumpiness_is_too_soon(db_path, app):
    conn, uid, _ = setup(db_path, [10, 11, 10, 12] * 5, [(0, "BUY", 100)])
    r = risk.risk(conn, uid)
    conn.close()
    assert r["you"]["vol"] != r["you"]["vol"]                                     # NaN
    assert "too soon" in " ".join(explain_risk(r).lines)


def test_a_fall_that_hasnt_recovered_says_so(db_path):
    closes = [10, 12, 9] + [9.5] * 70
    conn, uid, _ = setup(db_path, closes, [(0, "BUY", 100)])
    r = risk.risk(conn, uid)
    conn.close()
    assert r["you"]["back_day"] is None and math.isclose(r["you"]["now_pct"], 9.5 / 12 - 1)
    assert "it hasn't climbed back yet" in explain_risk(r).text


def test_with_one_day_of_prices_the_section_says_too_soon(app):
    c = signed_up(app)
    add(c)                                       # the test database has a single DBS close
    page = c.get("/portfolio").get_data(as_text=True)
    assert 'id="risk-title">Ups and downs' in page and "Too soon" in page


def test_with_enough_prices_the_page_shows_three_figures_with_explanations(app, db_path):
    conn = db.get_connection(db_path)
    days = weekdays(date(2025, 1, 6), 70)
    db.save_prices(conn, "D05.SI", [(d.isoformat(), 30 + (i % 3)) for i, d in enumerate(days)])
    db.save_prices(conn, "ES3.SI", [(d.isoformat(), 3.5 + (i % 2) / 10) for i, d in enumerate(days)])
    conn.close()
    c = signed_up(app)
    add(c, date=days[0].isoformat(), price="30")
    page = c.get("/portfolio").get_data(as_text=True)
    for key in ("risk-fall", "risk-vol", "risk-high"):
        assert f'popovertarget="{key}-what"' in page, key
    assert "per year" in page and "STI ETF:" in page
    from test_page_rules import check_page_rules
    check_page_rules(page)
