"""Tests for the sanity checks in checks.py."""

import db
from checks import check_manual_dividends, check_trades


def save_week_of_prices(conn):
    """DBS closes for Mon 2024-02-05 to Fri 2024-02-16, with no trading on the Chinese New Year
    holiday (Mon 12 Feb 2024). ES3 trades the same days."""
    days = ["2024-02-05", "2024-02-06", "2024-02-07", "2024-02-08", "2024-02-09",
            "2024-02-13", "2024-02-14", "2024-02-15", "2024-02-16"]
    db.save_prices(conn, "D05.SI", [(d, 30.0) for d in days])
    db.save_prices(conn, "ES3.SI", [(d, 3.3) for d in days])


def test_no_prices_means_no_warnings(conn, user_id):
    db.add_trade(conn, user_id, "D05.SI", "2024-02-12", "BUY", 100, 99.0)

    assert check_trades(conn, user_id) == []


def test_good_trade_has_no_warnings(conn, user_id):
    save_week_of_prices(conn)
    db.add_trade(conn, user_id, "D05.SI", "2024-02-06", "BUY", 100, 30.5)   # 1.7% from the close

    assert check_trades(conn, user_id) == []


def test_trade_on_a_public_holiday_is_flagged(conn, user_id):
    save_week_of_prices(conn)
    db.add_trade(conn, user_id, "D05.SI", "2024-02-12", "BUY", 100, 30.0)

    [warning] = check_trades(conn, user_id)
    assert "didn't trade that day" in warning


def test_price_far_from_the_close_is_flagged(conn, user_id):
    save_week_of_prices(conn)
    db.add_trade(conn, user_id, "D05.SI", "2024-02-06", "BUY", 100, 44.25)  # 48% above the close

    [warning] = check_trades(conn, user_id)
    assert "closed at $30.00" in warning and "48% apart" in warning


def test_manual_dividend_on_a_holiday_is_flagged(conn):
    save_week_of_prices(conn)
    db.set_manual_dividend(conn, "D05.SI", "2024-02-12", 0.54)

    [warning] = check_manual_dividends(conn)
    assert "ex-dates are always trading days" in warning


def test_manual_dividend_at_the_usual_time_is_fine(conn):
    db.save_dividends(conn, "D05.SI", [("2024-04-05", 0.49), ("2024-08-15", 0.54), ("2025-04-07", 0.60)])
    db.set_manual_dividend(conn, "D05.SI", "2025-08-14", 0.75)   # a year after 2024-08-15

    assert check_manual_dividends(conn) == []


def test_manual_dividend_at_an_odd_time_is_flagged(conn):
    db.save_dividends(conn, "D05.SI", [("2024-04-05", 0.49), ("2024-08-15", 0.54), ("2025-04-07", 0.60)])
    db.set_manual_dividend(conn, "D05.SI", "2025-01-20", 0.75)   # DBS never pays in January

    [warning] = check_manual_dividends(conn)
    assert "doesn't usually pay around this time" in warning


def test_correcting_a_yahoo_dividend_is_not_flagged(conn):
    db.save_dividends(conn, "D05.SI", [("2024-04-05", 0.49), ("2024-08-15", 0.54), ("2025-04-07", 0.60)])
    db.set_manual_dividend(conn, "D05.SI", "2024-04-05", 0.54)   # replaces Yahoo's adjusted amount

    assert check_manual_dividends(conn) == []
