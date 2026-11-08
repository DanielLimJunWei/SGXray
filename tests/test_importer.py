"""Tests for the CSV importer. Run with:  python -m pytest"""

from datetime import date

import db
from importer import import_trades_csv

TODAY = date(2026, 11, 6)   # fixed, so "in the future" doesn't change as time passes
HEADER = "ticker,date,side,quantity,price,fees\n"


def write_csv(tmp_path, body, header=HEADER):
    path = tmp_path / "trades.csv"
    path.write_text(header + body)
    return path


def test_good_file_is_imported(conn, user_id, tmp_path):
    path = write_csv(tmp_path, "D05.SI,2024-03-15,BUY,100,31.47,10.00\nD05.SI,2025-03-14,SELL,40,44.25,10.00\n")

    result = import_trades_csv(conn, user_id, path, today=TODAY)

    assert result.ok
    assert result.imported == 2
    assert [dict(h) for h in db.get_holdings(conn, user_id)] == [{"ticker": "D05.SI", "shares": 60}]


def test_every_bad_row_is_reported_and_nothing_saved(conn, user_id, tmp_path):
    path = write_csv(
        tmp_path,
        "D05.SI,2024-03-15,BUY,100,31.47,10\n"     # fine
        "XYZ.SI,2024-03-15,BUY,100,1.00,0\n"       # unknown ticker
        "D05.SI,2024-08-25,BUY,100,30.00,0\n"      # a Sunday
        "D05.SI,2024-02-30,BUY,100,30.00,0\n"      # no such date
        "D05.SI,15/03/2024,BUY,100,30.00,0\n"      # wrong date format
        "D05.SI,2024-03-15,HOLD,100,30.00,0\n"     # bad side
        "D05.SI,2024-03-15,BUY,-5,30.00,0\n"       # negative quantity
        "D05.SI,2024-03-15,BUY,100,PRICE,0\n"      # word as price
        "D05.SI,2027-01-04,BUY,100,30.00,0\n",     # future
    )

    result = import_trades_csv(conn, user_id, path, today=TODAY)

    assert not result.ok
    assert len(result.errors) == 8
    assert result.errors[0].startswith("Row 3: unknown ticker")
    assert db.get_trades(conn, user_id) == []


def test_selling_more_than_held_is_rejected(conn, user_id, tmp_path):
    path = write_csv(tmp_path, "D05.SI,2024-03-15,BUY,100,31.47,0\nD05.SI,2024-04-15,SELL,150,33.00,0\n")

    result = import_trades_csv(conn, user_id, path, today=TODAY)

    assert result.errors == ["Row 3: sells 150 D05.SI on 2024-04-15, but only 100 are held then"]
    assert db.get_trades(conn, user_id) == []


def test_sell_before_its_buy_is_rejected(conn, user_id, tmp_path):
    # Rows out of order: the SELL date is before the BUY date.
    path = write_csv(tmp_path, "D05.SI,2024-04-15,BUY,100,31.47,0\nD05.SI,2024-03-15,SELL,100,33.00,0\n")

    result = import_trades_csv(conn, user_id, path, today=TODAY)

    assert not result.ok


def test_importing_the_same_file_twice_saves_once(conn, user_id, tmp_path):
    path = write_csv(tmp_path, "D05.SI,2024-03-15,BUY,100,31.47,10\n")

    import_trades_csv(conn, user_id, path, today=TODAY)
    second = import_trades_csv(conn, user_id, path, today=TODAY)

    assert second.ok
    assert (second.imported, second.skipped) == (0, 1)
    assert len(db.get_trades(conn, user_id)) == 1


def test_missing_column_is_reported(conn, user_id, tmp_path):
    path = write_csv(tmp_path, "D05.SI,2024-03-15,BUY,100\n", header="ticker,date,side,quantity\n")

    result = import_trades_csv(conn, user_id, path, today=TODAY)

    assert result.errors[0].startswith("Missing column(s): price")


def test_fees_column_is_optional_and_case_is_ignored(conn, user_id, tmp_path):
    path = write_csv(tmp_path, "d05.si,2024-03-15,buy,100,31.47\n", header="Ticker,Date,Side,Quantity,Price\n")

    result = import_trades_csv(conn, user_id, path, today=TODAY)

    assert result.ok
    trade = db.get_trades(conn, user_id)[0]
    assert (trade["ticker"], trade["side"], trade["fees"]) == ("D05.SI", "BUY", 0.0)
