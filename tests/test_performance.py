"""Tests for XIRR and the STI ETF comparison (performance.py)."""

import math
from datetime import date

import pytest

import db
from performance import benchmark, compare, xirr


def test_xirr_matches_microsofts_own_example():
    # The worked example in Microsoft's XIRR documentation; Excel's answer is 37.34%.
    flows = [
        (date(2008, 1, 1), -10000),
        (date(2008, 3, 1), 2750),
        (date(2008, 10, 30), 4250),
        (date(2009, 2, 15), 3250),
        (date(2009, 4, 1), 2750),
    ]
    assert xirr(flows) == pytest.approx(0.373362535, abs=1e-6)


def test_xirr_simple_cases():
    assert xirr([(date(2024, 1, 1), -1000), (date(2024, 12, 31), 1100)]) == pytest.approx(0.10)  # 365 days
    assert xirr([(date(2024, 1, 1), -1000), (date(2025, 12, 31), 1210)]) == pytest.approx(0.10)  # 730 days
    assert xirr([(date(2024, 1, 1), -1000), (date(2024, 12, 31), 500)]) == pytest.approx(-0.50)


def test_xirr_has_no_answer_without_money_both_ways():
    assert math.isnan(xirr([(date(2024, 1, 1), -1000), (date(2025, 1, 1), -500)]))
    assert math.isnan(xirr([(date(2024, 1, 1), -1000), (date(2024, 1, 1), 1100)]))   # same day
    assert math.isnan(xirr([]))


def test_buying_only_the_etf_ties_with_the_benchmark(conn, user_id):
    db.add_trade(conn, user_id, "ES3.SI", "2024-01-02", "BUY", 1000, 3.00, 10)
    db.add_trade(conn, user_id, "ES3.SI", "2024-07-01", "BUY", 500, 3.20, 10)
    db.save_prices(conn, "ES3.SI", [("2024-01-02", 3.00), ("2024-07-01", 3.20), ("2025-01-02", 3.50)])
    db.save_dividends(conn, "ES3.SI", [("2024-08-01", 0.09)])

    c = compare(conn, user_id)

    assert c["you"] == pytest.approx(c["benchmark"], abs=1e-6)


def test_benchmark_replays_the_same_dollars(conn, user_id):
    # $1,000 into DBS when ES3 was $2.00; ES3 later $2.20.
    db.add_trade(conn, user_id, "D05.SI", "2024-01-02", "BUY", 10, 99.0, 10)
    db.save_prices(conn, "ES3.SI", [("2024-01-02", 2.00), ("2025-01-02", 2.20)])

    b = benchmark(conn, user_id)

    # $990 of shares + $10 fee: the ETF version also pays $10, so $990 buys 495 units
    assert b.units == pytest.approx(495)
    assert b.value == pytest.approx(1089)
    assert b.flows[0] == (date(2024, 1, 2), -1000)


def test_benchmark_pays_out_its_own_dividends(conn, user_id):
    db.add_trade(conn, user_id, "D05.SI", "2024-01-02", "BUY", 10, 100.0, 0)
    db.save_prices(conn, "ES3.SI", [("2024-01-02", 2.00), ("2025-01-02", 2.00)])
    db.save_dividends(conn, "ES3.SI", [("2024-08-01", 0.10), ("2023-08-01", 0.10)])   # 2023: before we started

    b = benchmark(conn, user_id)

    assert b.dividends == pytest.approx(50)          # 500 units x $0.10, once


def test_a_sale_takes_the_same_dollars_out(conn, user_id):
    db.add_trade(conn, user_id, "D05.SI", "2024-01-02", "BUY", 10, 100.0, 0)    # $1,000 in
    db.add_trade(conn, user_id, "D05.SI", "2024-06-03", "SELL", 5, 80.0, 0)     # $400 out
    db.save_prices(conn, "ES3.SI", [("2024-01-02", 2.00), ("2024-06-03", 2.50), ("2025-01-02", 2.50)])

    b = benchmark(conn, user_id)

    # 500 units; the $400 out sells 160 units at $2.50, leaving 340 = $850
    assert b.units == pytest.approx(340)
    assert not b.shortfall


def test_shortfall_is_flagged(conn, user_id):
    db.add_trade(conn, user_id, "D05.SI", "2024-01-02", "BUY", 10, 100.0, 0)    # $1,000 in
    db.add_trade(conn, user_id, "D05.SI", "2024-06-03", "SELL", 10, 300.0, 0)   # $3,000 out
    db.save_prices(conn, "ES3.SI", [("2024-01-02", 2.00), ("2024-06-03", 2.00), ("2025-01-02", 2.00)])

    b = benchmark(conn, user_id)

    assert b.shortfall and b.units == pytest.approx(0)


def test_missing_benchmark_price_says_what_to_do(conn, user_id):
    db.add_trade(conn, user_id, "D05.SI", "2024-01-02", "BUY", 10, 100.0, 0)

    with pytest.raises(ValueError, match="Run python src/market.py"):
        benchmark(conn, user_id)
