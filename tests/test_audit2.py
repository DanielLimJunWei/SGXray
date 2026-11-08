"""Edge cases found in the second audit (9 Nov 2026). Each was a real bug or gap before its fix."""

import math
from datetime import date

import pytest

import db
from history import time_weighted
from income import forecast, portfolio_yield, yields
from performance import compare, xirr
from portfolio import positions


# ---------- XIRR ----------

def test_xirr_survives_very_long_spans():
    # Used to crash with a divide-by-zero: (1 - 0.9999) ** 100 years underflows to 0.
    r = xirr([(date(2024, 1, 1), -1000), (date(2124, 1, 1), 5000)])
    assert r == pytest.approx(5 ** (1 / 100.07) - 1, abs=1e-4)      # about +1.6% a year


def test_losing_everything_is_minus_100_percent():
    assert xirr([(date(2024, 1, 1), -1000), (date(2025, 1, 1), 0)]) == -1.0


# ---------- Comparison over the same dates ----------

def test_stti_side_is_valued_on_your_end_date_and_flagged_when_stale(conn, user_id):
    db.add_trade(conn, user_id, "D05.SI", "2024-01-02", "BUY", 10, 100.0, 0)
    db.save_prices(conn, "D05.SI", [("2024-01-02", 100.0), ("2025-01-02", 110.0)])
    db.save_prices(conn, "ES3.SI", [("2024-01-02", 3.0), ("2024-07-01", 3.3)])   # ES3 stopped updating

    c = compare(conn, user_id)

    # Both sides now cover 2 Jan 2024 to 2 Jan 2025 (+10% each), instead of the STI side
    # ending in July and showing +21% a year.
    assert c["benchmark"] == pytest.approx(c["you"], abs=1e-6)
    assert c["stale_benchmark"]


def test_under_30_days_has_no_yearly_rate(conn, user_id):
    db.add_trade(conn, user_id, "D05.SI", "2024-01-02", "BUY", 10, 100.0, 0)
    db.save_prices(conn, "D05.SI", [("2024-01-02", 100.0), ("2024-01-09", 110.0)])
    db.save_prices(conn, "ES3.SI", [("2024-01-02", 3.0), ("2024-01-09", 3.0)])

    c = compare(conn, user_id)

    assert c["too_short"] and math.isnan(c["you"])
    assert c["your_profit"] == pytest.approx(100)         # the dollar result is still shown


# ---------- Yields and forecast after a split ----------

def test_split_within_the_last_year_is_restated_per_current_share(conn, user_id):
    db.add_trade(conn, user_id, "O39.SI", "2025-01-02", "BUY", 100, 20.0, 0)
    db.save_prices(conn, "O39.SI", [("2025-01-02", 20.0), ("2026-11-06", 10.0)])
    db.save_dividends(conn, "O39.SI", [("2026-03-02", 1.00)])       # $1 per old share
    db.save_actions(conn, "O39.SI", [("2026-06-01", 2.0)])           # 2-for-1: now 200 shares at ~$10

    y = yields(conn, user_id).iloc[0]
    f = forecast(conn, user_id)

    assert y["per_share_12m"] == pytest.approx(0.50)   # was 1.00, which doubled everything
    assert y["div_yield"] == pytest.approx(0.05)        # was 10%
    assert f["total"].sum() == pytest.approx(100)       # was $200; the real yearly income is $100


def test_portfolio_yield_is_unknown_with_a_missing_price(conn, user_id):
    db.add_trade(conn, user_id, "D05.SI", "2024-01-02", "BUY", 10, 100.0, 0)
    db.add_trade(conn, user_id, "O39.SI", "2024-01-02", "BUY", 10, 10.0, 0)
    db.save_prices(conn, "D05.SI", [("2024-01-02", 100.0), ("2025-01-02", 100.0)])
    db.save_dividends(conn, "D05.SI", [("2024-08-01", 5.0)])

    assert math.isnan(portfolio_yield(yields(conn, user_id), positions(conn, user_id)))


# ---------- Time-weighted return ----------

def test_twr_equals_the_simple_return_without_extra_money(conn, user_id):
    db.add_trade(conn, user_id, "D05.SI", "2024-01-02", "BUY", 10, 100.0, 0)
    db.save_prices(conn, "D05.SI", [("2024-01-02", 100.0), ("2024-07-01", 90.0), ("2025-01-02", 120.0)])
    db.save_prices(conn, "ES3.SI", [("2024-01-02", 3.0), ("2024-07-01", 3.0), ("2025-01-02", 3.3)])

    t = time_weighted(conn, user_id)

    assert t["you_total"] == pytest.approx(0.20)      # 100 -> 120
    assert t["sti_total"] == pytest.approx(0.10)      # 3.0 -> 3.3


def test_twr_ignores_when_money_was_added(conn, user_id):
    # Price: 100 -> 50 -> 100. Bought $1,000 at the start and $1,000 more at the bottom.
    db.add_trade(conn, user_id, "D05.SI", "2024-01-02", "BUY", 10, 100.0, 0)
    db.add_trade(conn, user_id, "D05.SI", "2024-07-01", "BUY", 20, 50.0, 0)
    db.save_prices(conn, "D05.SI", [("2024-01-02", 100.0), ("2024-07-01", 50.0), ("2025-01-02", 100.0)])
    db.save_prices(conn, "ES3.SI", [("2024-01-02", 3.0), ("2024-07-01", 3.0), ("2025-01-02", 3.0)])

    t = time_weighted(conn, user_id)
    c = compare(conn, user_id)

    assert t["you_total"] == pytest.approx(0.0)       # the stock itself went nowhere: TWR = 0%
    assert c["you"] > 0.3                             # but buying at the bottom made YOU money: XIRR > 30%


def test_twr_counts_dividends(conn, user_id):
    db.add_trade(conn, user_id, "D05.SI", "2024-01-02", "BUY", 10, 100.0, 0)
    db.save_prices(conn, "D05.SI", [("2024-01-02", 100.0), ("2024-07-01", 100.0), ("2025-01-02", 100.0)])
    db.save_prices(conn, "ES3.SI", [("2024-01-02", 3.0), ("2024-07-01", 3.0), ("2025-01-02", 3.0)])
    db.save_dividends(conn, "D05.SI", [("2024-07-01", 5.0)])

    assert time_weighted(conn, user_id)["you_total"] == pytest.approx(0.05)
