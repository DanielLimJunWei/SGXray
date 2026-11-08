"""Tests for dividend downloads (market.py) and manual entry (dividends.py). No internet needed."""

from datetime import date, datetime

import db
from dividends import add_manual_dividend
from market import SGT, update_dividends

NOW = datetime(2026, 11, 6, 18, 0, tzinfo=SGT)
TODAY = date(2026, 11, 6)


def fake_download(ticker):
    return [
        ("2023-11-10", 0.50),       # before the first trade: not needed
        ("2024-04-10", 0.54),
        ("2024-08-12", 0.54),
        ("2026-12-01", 0.60),       # in the future: ignored
    ]


def buy_dbs(conn, user_id):
    db.add_trade(conn, user_id, "D05.SI", "2024-03-15", "BUY", 100, 31.47)


def test_dividends_from_first_trade_to_today_are_saved(conn, user_id):
    buy_dbs(conn, user_id)

    [result] = update_dividends(conn, ["D05.SI"], now=NOW, download=fake_download, pause=0)

    assert (result.saved, result.total, result.error) == (2, 2, None)
    assert [r["ex_date"] for r in db.get_dividends(conn, "D05.SI")] == ["2024-04-10", "2024-08-12"]


def test_running_again_changes_nothing(conn, user_id):
    buy_dbs(conn, user_id)
    update_dividends(conn, ["D05.SI"], now=NOW, download=fake_download, pause=0)

    [result] = update_dividends(conn, ["D05.SI"], now=NOW, download=fake_download, pause=0)

    assert (result.saved, result.total) == (0, 2)


def test_yahoo_corrections_are_saved_but_manual_entries_win(conn, user_id):
    buy_dbs(conn, user_id)
    update_dividends(conn, ["D05.SI"], now=NOW, download=fake_download, pause=0)
    add_manual_dividend(conn, "D05.SI", "2024-04-10", "0.60", today=TODAY)

    def corrected(ticker):
        return [("2024-04-10", 0.99), ("2024-08-12", 0.55)]

    update_dividends(conn, ["D05.SI"], now=NOW, download=corrected, pause=0)

    saved = {r["ex_date"]: (r["amount"], r["source"]) for r in db.get_dividends(conn, "D05.SI")}
    assert saved["2024-04-10"] == (0.60, "manual")      # the manual entry stayed
    assert saved["2024-08-12"] == (0.55, "yfinance")    # Yahoo's correction was saved


def test_download_failure_is_reported(conn, user_id):
    buy_dbs(conn, user_id)

    def broken(ticker):
        raise ConnectionError("no internet")

    [result] = update_dividends(conn, ["D05.SI"], now=NOW, download=broken, pause=0)

    assert "download failed" in result.error


def test_manual_dividend_can_be_corrected_by_hand(conn):
    add_manual_dividend(conn, "D05.SI", "2024-04-10", "0.54", today=TODAY)
    add_manual_dividend(conn, "d05.si", "2024-04-10", "0.60", today=TODAY)

    [row] = db.get_dividends(conn, "D05.SI")
    assert (row["amount"], row["source"]) == (0.60, "manual")


def test_bad_manual_dividend_is_rejected(conn):
    errors = add_manual_dividend(conn, "XYZ.SI", "10/04/2024", "free", today=TODAY)

    assert len(errors) == 3
    assert db.get_dividends(conn, "XYZ.SI") == []


def test_future_manual_dividend_is_rejected(conn):
    errors = add_manual_dividend(conn, "D05.SI", "2027-01-05", "0.60", today=TODAY)

    assert errors == ["ex-date 2027-01-05 is in the future"]
