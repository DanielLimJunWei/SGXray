"""Tests for portfolio.py. Every expected number is worked out by hand in the comments."""

import math

import pytest

import db
from portfolio import positions, summary


def trade(conn, user_id, ticker, day, side, qty, price, fees=10.0):
    db.add_trade(conn, user_id, ticker, day, side, qty, price, fees)


@pytest.fixture
def demo(conn, user_id):
    """The same trades as data/demo_trades.csv, plus one close per ticker."""
    trade(conn, user_id, "D05.SI", "2024-03-15", "BUY", 100, 31.47)
    trade(conn, user_id, "C38U.SI", "2024-06-10", "BUY", 1000, 1.97)
    trade(conn, user_id, "C38U.SI", "2024-06-11", "BUY", 1000, 1.93)
    trade(conn, user_id, "ES3.SI", "2024-08-15", "BUY", 1000, 3.37)
    trade(conn, user_id, "D05.SI", "2025-03-14", "BUY", 100, 44.25)
    trade(conn, user_id, "C38U.SI", "2025-11-14", "SELL", 800, 2.32)
    db.save_prices(conn, "D05.SI", [("2026-11-06", 69.72)])
    db.save_prices(conn, "C38U.SI", [("2026-11-06", 2.34)])
    db.save_prices(conn, "ES3.SI", [("2026-11-06", 5.25)])
    return positions(conn, user_id).set_index("ticker")


def test_two_buys_average_out(demo):
    dbs = demo.loc["D05.SI"]
    # cost = (100 x 31.47 + 10) + (100 x 44.25 + 10) = 3,157 + 4,435 = 7,592
    assert dbs["shares"] == 200
    assert dbs["cost"] == pytest.approx(7592)
    assert dbs["avg_cost"] == pytest.approx(37.96)        # 7,592 / 200
    # value = 200 x 69.72 = 13,944; unrealised = 13,944 - 7,592 = 6,352
    assert dbs["unrealised"] == pytest.approx(6352)
    assert dbs["realised"] == 0


def test_a_sale_realises_profit_at_average_cost(demo):
    reit = demo.loc["C38U.SI"]
    # bought: (1,000 x 1.97 + 10) + (1,000 x 1.93 + 10) = 3,920 for 2,000 units, average 1.96
    # sold 800 at 2.32: 1,856 - 10 fees - 800 x 1.96 (= 1,568) = 278 realised
    assert reit["realised"] == pytest.approx(278)
    # left: 1,200 units costing 3,920 - 1,568 = 2,352, still 1.96 each
    assert reit["shares"] == 1200
    assert reit["cost"] == pytest.approx(2352)
    assert reit["avg_cost"] == pytest.approx(1.96)
    # value = 1,200 x 2.34 = 2,808; unrealised = 456, which is 456 / 2,352 = 19.4%
    assert reit["unrealised"] == pytest.approx(456)
    assert reit["unrealised_pct"] == pytest.approx(0.19388, abs=1e-4)
    # fees: 3 trades x $10
    assert reit["fees"] == 30


def test_portfolio_totals(demo):
    s = summary(demo.reset_index())
    # cost 7,592 + 2,352 + 3,380 = 13,324; value 13,944 + 2,808 + 5,250 = 22,002
    assert s["cost"] == pytest.approx(13324)
    assert s["value"] == pytest.approx(22002)
    assert s["unrealised"] == pytest.approx(8678)
    assert s["realised"] == pytest.approx(278)
    assert s["fees"] == 60


def test_selling_everything_leaves_no_cost(conn, user_id):
    trade(conn, user_id, "D05.SI", "2024-03-15", "BUY", 300, 30.00, fees=0)
    trade(conn, user_id, "D05.SI", "2024-04-15", "SELL", 300, 33.33, fees=0)

    row = positions(conn, user_id).iloc[0]

    assert (row["shares"], row["cost"]) == (0, 0)
    assert math.isnan(row["avg_cost"])
    assert row["realised"] == pytest.approx(999)          # 300 x (33.33 - 30.00)


def test_as_of_date_ignores_later_trades_and_prices(conn, user_id):
    trade(conn, user_id, "D05.SI", "2024-03-15", "BUY", 100, 30.00, fees=0)
    trade(conn, user_id, "D05.SI", "2025-03-14", "BUY", 100, 40.00, fees=0)
    db.save_prices(conn, "D05.SI", [("2024-12-31", 35.00), ("2026-11-06", 70.00)])

    row = positions(conn, user_id, as_of="2024-12-31").iloc[0]

    assert row["shares"] == 100
    assert row["price"] == 35.00
    assert row["unrealised"] == pytest.approx(500)


def test_no_price_yet_means_no_value(conn, user_id):
    trade(conn, user_id, "D05.SI", "2024-03-15", "BUY", 100, 30.00)

    row = positions(conn, user_id).iloc[0]

    assert math.isnan(row["value"]) and math.isnan(row["unrealised"])


def test_no_trades_gives_an_empty_table(conn, user_id):
    assert positions(conn, user_id).empty
