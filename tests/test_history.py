"""Tests for value over time (history.py)."""

import math

import pandas as pd
import pytest

import db
from history import value_history
from performance import benchmark
from portfolio import positions, summary


def day(text):
    return pd.Timestamp(text)


@pytest.fixture
def week(conn, user_id):
    """Mon 5 Feb to Fri 16 Feb 2024, with no trading on Mon 12 Feb (Chinese New Year)."""
    days = ["2024-02-05", "2024-02-06", "2024-02-07", "2024-02-08", "2024-02-09",
            "2024-02-13", "2024-02-14", "2024-02-15", "2024-02-16"]
    db.save_prices(conn, "ES3.SI", [(d, 3.0) for d in days])
    db.save_prices(conn, "D05.SI", [(d, 30.0 + i) for i, d in enumerate(days)])   # 30, 31, ... 38
    return user_id


def test_value_is_shares_times_price_each_day(conn, week):
    db.add_trade(conn, week, "D05.SI", "2024-02-06", "BUY", 100, 31.0, 0)
    db.add_trade(conn, week, "D05.SI", "2024-02-14", "SELL", 40, 36.0, 0)

    h = value_history(conn, week)

    assert h.index[0] == day("2024-02-06")                 # starts at the first trade
    assert h.loc[day("2024-02-06"), "value"] == 3100       # 100 x 31
    assert h.loc[day("2024-02-13"), "value"] == 3500       # 100 x 35 (12 Feb is skipped: holiday)
    assert h.loc[day("2024-02-14"), "value"] == 2160       # 60 x 36, after the sale
    assert day("2024-02-12") not in h.index


def test_money_in_and_profit_add_up(conn, week):
    db.add_trade(conn, week, "D05.SI", "2024-02-06", "BUY", 100, 31.0, 10)   # $3,110 in
    db.add_trade(conn, week, "D05.SI", "2024-02-14", "SELL", 40, 36.0, 10)   # $1,430 out

    h = value_history(conn, week)

    assert h.loc[day("2024-02-06"), "net_invested"] == 3110
    assert h.loc[day("2024-02-14"), "net_invested"] == 1680               # 3,110 - 1,430
    # last day: 60 x 38 = 2,280 held; profit = 2,280 - 1,680 = 600
    assert h["profit"].iloc[-1] == pytest.approx(600)


def test_last_day_matches_the_portfolio_totals(conn, week):
    db.add_trade(conn, week, "D05.SI", "2024-02-06", "BUY", 100, 31.0, 10)
    db.add_trade(conn, week, "D05.SI", "2024-02-14", "SELL", 40, 36.0, 10)
    db.save_dividends(conn, "D05.SI", [("2024-02-08", 0.5)])

    h = value_history(conn, week)
    s = summary(positions(conn, week))

    assert h["value"].iloc[-1] == pytest.approx(s["value"])
    assert h["profit"].iloc[-1] == pytest.approx(s["total_profit"])
    assert h["dividends"].iloc[-1] == pytest.approx(50)                   # 100 x $0.50
    assert h.loc[day("2024-02-07"), "dividends"] == 0                     # not before the ex-date


def test_sti_line_matches_the_benchmark(conn, week):
    db.add_trade(conn, week, "D05.SI", "2024-02-06", "BUY", 100, 31.0, 10)

    h = value_history(conn, week)
    b = benchmark(conn, week)

    assert h["sti_value"].iloc[-1] == pytest.approx(b.value)
    assert h["sti_profit"].iloc[-1] == pytest.approx(sum(a for _, a in b.flows))


def test_bonus_shares_count_from_the_ex_date(conn, week):
    db.add_trade(conn, week, "D05.SI", "2024-02-06", "BUY", 100, 31.0, 0)
    db.save_actions(conn, "D05.SI", [("2024-02-14", 1.1)])

    h = value_history(conn, week)

    assert h.loc[day("2024-02-13"), "value"] == 100 * 35
    assert h.loc[day("2024-02-14"), "value"] == 110 * 36


def test_a_held_stock_without_a_price_makes_the_day_unknown(conn, week):
    db.add_trade(conn, week, "D05.SI", "2024-02-06", "BUY", 100, 31.0, 0)
    db.add_trade(conn, week, "O39.SI", "2024-02-07", "BUY", 100, 14.0, 0)    # OCBC has no prices

    h = value_history(conn, week)

    assert h.loc[day("2024-02-06"), "value"] == 3100       # before OCBC was bought: fine
    assert math.isnan(h.loc[day("2024-02-07"), "value"])


def test_a_dividend_on_a_day_without_a_saved_price_still_counts(conn, user_id):
    db.add_trade(conn, user_id, "D05.SI", "2024-01-15", "BUY", 100, 30.0, 0)
    db.save_prices(conn, "D05.SI", [("2024-01-15", 30.0), ("2024-02-29", 29.0)])
    db.save_prices(conn, "ES3.SI", [("2024-01-15", 3.0), ("2024-02-29", 3.0)])
    db.save_dividends(conn, "D05.SI", [("2024-02-08", 0.50)])           # no price saved that day

    h = value_history(conn, user_id)

    assert h["dividends"].iloc[-1] == 50


def test_no_trades_gives_an_empty_table(conn, user_id):
    assert value_history(conn, user_id).empty
