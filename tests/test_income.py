"""Tests for yields and the 12-month dividend forecast (income.py)."""

import pandas as pd
import pytest

import db
from income import forecast, portfolio_yield, trailing_dividends, yields
from portfolio import positions

AS_OF = "2026-11-06"


@pytest.fixture
def dbs(conn, user_id):
    """200 DBS bought at $40 (no fees). Price now $70. Paid $0.75 x 2 then $0.81 x 2 in the last year."""
    db.add_trade(conn, user_id, "D05.SI", "2025-01-02", "BUY", 200, 40.0, 0)
    db.save_prices(conn, "D05.SI", [("2025-01-02", 40.0), (AS_OF, 70.0)])
    db.save_dividends(conn, "D05.SI", [
        ("2025-08-14", 0.75),     # more than a year before AS_OF: not in the last 12 months
        ("2025-11-13", 0.75),
        ("2026-04-08", 0.81),
        ("2026-05-11", 0.81),
        ("2026-08-14", 0.81),
    ])
    return user_id


def test_trailing_dividends_cover_exactly_the_last_12_months(conn, dbs):
    dates = [d["ex_date"] for d in trailing_dividends(conn, "D05.SI", AS_OF)]

    assert dates == ["2025-11-13", "2026-04-08", "2026-05-11", "2026-08-14"]


def test_yield_and_yield_on_cost(conn, dbs):
    row = yields(conn, dbs, AS_OF).iloc[0]

    # 0.75 + 0.81 x 3 = 3.18 a share in the last year
    assert row["per_share_12m"] == pytest.approx(3.18)
    assert row["div_yield"] == pytest.approx(3.18 / 70)          # 4.54% on today's price
    assert row["yield_on_cost"] == pytest.approx(3.18 / 40)  # 7.95% on what you paid
    assert row["income_12m"] == pytest.approx(636)           # 200 x 3.18


def test_forecast_repeats_last_year_on_shares_held_now(conn, dbs):
    f = forecast(conn, dbs, AS_OF)

    assert list(f["expected"].dt.strftime("%Y-%m-%d")) == ["2026-11-13", "2027-04-08", "2027-05-11", "2027-08-14"]
    assert list(f["total"]) == pytest.approx([150, 162, 162, 162])
    assert f["total"].sum() == pytest.approx(636)


def test_ignored_dividends_are_not_forecast(conn, dbs):
    db.set_dividend_ignored(conn, "D05.SI", "2026-05-11")

    assert forecast(conn, dbs, AS_OF)["total"].sum() == pytest.approx(636 - 162)


def test_sold_out_stocks_are_not_forecast(conn, dbs):
    db.add_trade(conn, dbs, "D05.SI", "2026-09-01", "SELL", 200, 68.0, 0)

    assert forecast(conn, dbs, AS_OF).empty


def test_bonus_shares_are_in_the_forecast(conn, dbs):
    db.save_actions(conn, "D05.SI", [("2026-09-01", 1.1)])        # 200 -> 220

    f = forecast(conn, dbs, AS_OF)

    assert set(f["shares"]) == {220}


def test_leap_day_moves_to_the_28th(conn, user_id):
    db.add_trade(conn, user_id, "O39.SI", "2023-06-01", "BUY", 100, 13.0, 0)
    db.save_prices(conn, "O39.SI", [("2023-06-01", 13.0), ("2024-06-03", 14.0)])
    db.save_dividends(conn, "O39.SI", [("2024-02-29", 0.40)])

    f = forecast(conn, user_id, "2024-06-03")

    assert f.iloc[0]["expected"] == pd.Timestamp("2025-02-28")


def test_portfolio_yield(conn, dbs):
    y = yields(conn, dbs, AS_OF)

    assert portfolio_yield(y, positions(conn, dbs, AS_OF)) == pytest.approx(636 / 14000)   # 200 x $70


def test_empty_portfolio(conn, user_id):
    assert forecast(conn, user_id).empty
    assert yields(conn, user_id).empty
