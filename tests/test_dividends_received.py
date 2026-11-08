"""Tests for dividends received (portfolio.py), ignoring wrong dividends, and the migration."""

import sqlite3

import pytest

import db
from portfolio import dividends_received, positions, summary


@pytest.fixture
def dbs_year(conn, user_id):
    """A year of DBS: buy, bonus issue, a buy on an ex-date, sell out. Dividends are $0.54 each."""
    db.add_trade(conn, user_id, "D05.SI", "2024-03-15", "BUY", 100, 34.62, 0)
    db.save_actions(conn, "D05.SI", [("2024-04-22", 1.1)])                  # 100 -> 110
    db.add_trade(conn, user_id, "D05.SI", "2024-08-15", "BUY", 100, 38.00, 0)  # on an ex-date
    db.add_trade(conn, user_id, "D05.SI", "2024-10-01", "SELL", 210, 40.00, 0)
    db.save_dividends(conn, "D05.SI", [
        ("2023-11-10", 0.50),     # before the first buy: not ours
        ("2024-04-05", 0.54),     # 100 shares
        ("2024-05-09", 0.54),     # 110 shares, after the bonus
        ("2024-08-15", 0.54),     # still 110: the 100 bought that day were too late
        ("2024-11-14", 0.54),     # sold out by then: nothing
    ])
    return user_id


def test_each_dividend_counts_shares_held_before_its_ex_date(conn, dbs_year):
    df = dividends_received(conn, dbs_year)

    assert list(df["ex_date"]) == ["2024-04-05", "2024-05-09", "2024-08-15"]
    assert list(df["shares"]) == [100, 110, 110]
    assert df["total"].sum() == pytest.approx(54 + 59.4 + 59.4)     # 172.80


def test_dividends_appear_in_positions_and_total_profit(conn, dbs_year):
    df = positions(conn, dbs_year)
    s = summary(df)

    assert df.iloc[0]["dividends"] == pytest.approx(172.8)
    # sold 210 at 40 = 8,400; cost 3,462 + 3,800 = 7,262; realised 1,138; nothing held now
    assert s["realised"] == pytest.approx(1138)
    assert s["total_profit"] == pytest.approx(1138 + 172.8)


def test_an_ignored_dividend_is_not_counted_and_stays_ignored(conn, dbs_year):
    assert db.set_dividend_ignored(conn, "D05.SI", "2024-05-09")

    db.save_dividends(conn, "D05.SI", [("2024-05-09", 0.55)])     # Yahoo sends it again, changed

    assert dividends_received(conn, dbs_year)["total"].sum() == pytest.approx(54 + 59.4)
    row = [d for d in db.get_dividends(conn, "D05.SI") if d["ex_date"] == "2024-05-09"][0]
    assert row["ignored"] == 1


def test_unignore_and_manual_entry_count_it_again(conn, dbs_year):
    db.set_dividend_ignored(conn, "D05.SI", "2024-05-09")
    db.set_dividend_ignored(conn, "D05.SI", "2024-05-09", ignored=False)
    assert len(dividends_received(conn, dbs_year)) == 3

    db.set_dividend_ignored(conn, "D05.SI", "2024-08-15")
    db.set_manual_dividend(conn, "D05.SI", "2024-08-15", 0.54)     # typed in = real
    assert len(dividends_received(conn, dbs_year)) == 3


def test_ignoring_a_missing_dividend_says_so(conn):
    assert db.set_dividend_ignored(conn, "D05.SI", "2024-01-01") is False


def test_old_databases_get_the_new_column(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE dividends (ticker TEXT, ex_date TEXT, amount REAL, source TEXT, "
                "PRIMARY KEY (ticker, ex_date))")
    old.execute("INSERT INTO dividends VALUES ('D05.SI', '2024-04-05', 0.54, 'yfinance')")
    old.commit()
    old.close()

    conn = db.get_connection(path)
    db.init_db(conn)
    db.init_db(conn)                      # running it twice is safe

    assert conn.execute("SELECT ignored FROM dividends").fetchone()["ignored"] == 0
    conn.close()
