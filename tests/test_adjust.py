"""Tests for splits and bonus issues (adjust.py) and how prices, holdings and imports use them."""

from datetime import date, datetime

import pytest

import db
from adjust import add_manual_action, price_factor, shares_after
from importer import import_trades_csv
from market import SGT, update_dividends, update_prices
from portfolio import positions

BONUS_DAY = "2024-04-22"     # DBS 1-for-10 bonus issue: 1.1 shares after for every 1 before


def dbs_bonus(conn):
    db.save_actions(conn, "D05.SI", [(BONUS_DAY, 1.1)])


def test_fractions_of_a_share_are_dropped():
    assert shares_after(100, 1.1) == 110
    assert shares_after(105, 1.1) == 115          # 115.5 -> 115
    assert shares_after(1000, 0.1) == 100         # a 10-to-1 consolidation


def test_price_factor_counts_only_later_actions():
    actions = [{"ex_date": "2024-04-22", "factor": 1.1}, {"ex_date": "2025-01-10", "factor": 2.0}]
    assert price_factor(actions, "2024-03-15") == pytest.approx(2.2)
    assert price_factor(actions, "2024-04-22") == pytest.approx(2.0)   # the ex-date is already "after"
    assert price_factor(actions, "2025-06-01") == 1.0


def test_bonus_shares_are_added_and_cost_is_spread(conn, user_id):
    dbs_bonus(conn)
    db.add_trade(conn, user_id, "D05.SI", "2024-03-15", "BUY", 100, 34.62, 10)
    db.add_trade(conn, user_id, "D05.SI", "2025-03-14", "BUY", 100, 44.25, 10)

    row = positions(conn, user_id).iloc[0]

    # 100 -> 110 on the bonus, + 100 = 210 shares; cost 3,472 + 4,435 = 7,907 (the bonus is free)
    assert row["shares"] == 210
    assert row["cost"] == pytest.approx(7907)
    assert row["avg_cost"] == pytest.approx(7907 / 210)


def test_shares_bought_on_the_ex_date_miss_the_bonus(conn, user_id):
    dbs_bonus(conn)
    db.add_trade(conn, user_id, "D05.SI", BONUS_DAY, "BUY", 100, 34.0, 0)

    assert positions(conn, user_id).iloc[0]["shares"] == 100


def test_selling_the_bonus_shares_is_allowed(conn, user_id, tmp_path):
    dbs_bonus(conn)
    csv = tmp_path / "t.csv"
    csv.write_text("ticker,date,side,quantity,price,fees\n"
                   "D05.SI,2024-03-15,BUY,100,34.62,0\n"
                   "D05.SI,2024-05-02,SELL,110,35.00,0\n")

    result = import_trades_csv(conn, user_id, csv, today=date(2026, 11, 6))

    assert result.ok
    assert positions(conn, user_id).iloc[0]["shares"] == 0


def test_prices_before_a_yahoo_bonus_are_saved_as_really_traded(conn, user_id):
    dbs_bonus(conn)
    db.add_trade(conn, user_id, "D05.SI", "2024-04-19", "BUY", 100, 36.4, 0)

    def yahoo(ticker, start, end):        # Yahoo's adjusted numbers
        return [("2024-04-19", 33.1), ("2024-04-22", 34.07)]

    update_prices(conn, ["D05.SI"], now=datetime(2024, 4, 22, 18, 0, tzinfo=SGT), download=yahoo, pause=0)

    assert db.get_close(conn, "D05.SI", "2024-04-19") == pytest.approx(36.41)   # 33.1 x 1.1
    assert db.get_close(conn, "D05.SI", "2024-04-22") == pytest.approx(34.07)   # on/after: unchanged


def test_dividends_before_a_yahoo_bonus_are_saved_as_really_paid(conn, user_id):
    dbs_bonus(conn)
    db.add_trade(conn, user_id, "D05.SI", "2024-03-15", "BUY", 100, 34.62, 0)

    update_dividends(conn, ["D05.SI"], now=datetime(2026, 11, 6, 18, 0, tzinfo=SGT),
                     download=lambda t: [("2024-04-05", 0.490909)], pause=0)

    assert db.get_dividends(conn, "D05.SI")[0]["amount"] == pytest.approx(0.54)


def test_manual_actions_change_holdings_but_not_yahoo_prices(conn, user_id):
    assert add_manual_action(conn, "D05.SI", BONUS_DAY, "1.1", today=date(2026, 11, 6)) == []
    db.add_trade(conn, user_id, "D05.SI", "2024-04-19", "BUY", 100, 36.4, 0)

    update_prices(conn, ["D05.SI"], now=datetime(2024, 4, 22, 18, 0, tzinfo=SGT),
                  download=lambda t, s, e: [("2024-04-19", 36.4)], pause=0)

    assert db.get_close(conn, "D05.SI", "2024-04-19") == 36.4    # Yahoo didn't know: price is real
    assert positions(conn, user_id).iloc[0]["shares"] == 110


def test_yahoo_cannot_overwrite_a_manual_action(conn):
    add_manual_action(conn, "D05.SI", BONUS_DAY, "1.1", today=date(2026, 11, 6))

    assert db.save_actions(conn, "D05.SI", [(BONUS_DAY, 2.0)]) == 0
    assert db.get_actions(conn, "D05.SI")[0]["factor"] == 1.1


def test_bad_manual_actions_are_rejected(conn):
    today = date(2026, 11, 6)
    assert len(add_manual_action(conn, "XYZ.SI", "22/04/2024", "one", today=today)) == 3
    assert add_manual_action(conn, "D05.SI", BONUS_DAY, "1", today=today) != []
    dbs_bonus(conn)
    assert add_manual_action(conn, "D05.SI", BONUS_DAY, "1.1", today=today) == [
        f"D05.SI already has an action on {BONUS_DAY}"
    ]
