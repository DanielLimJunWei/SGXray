"""Edge cases found in the 8 Nov 2026 audit. Each test was a real bug or gap before its fix."""

import math
from datetime import date

import pytest

import db
from checks import check_price_spikes
from importer import import_trades_csv
from portfolio import dividends_received, positions, summary

TODAY = date(2026, 11, 6)
HEADER = "ticker,date,side,quantity,price,fees\n"


def write(tmp_path, name, body, encoding="utf-8"):
    path = tmp_path / name
    path.write_bytes((HEADER + body).encode(encoding))
    return path


def test_identical_fills_in_separate_files_are_both_kept(conn, user_id, tmp_path):
    # A broker filled one order as two identical lots. File A has the first; file B has both.
    fill = "D05.SI,2024-03-15,BUY,100,34.62,10\n"
    import_trades_csv(conn, user_id, write(tmp_path, "a.csv", fill), today=TODAY)
    b = import_trades_csv(conn, user_id, write(tmp_path, "b.csv", fill * 2), today=TODAY)

    assert (b.imported, b.skipped) == (1, 1)
    assert positions(conn, user_id).iloc[0]["shares"] == 200
    again = import_trades_csv(conn, user_id, write(tmp_path, "b.csv", fill * 2), today=TODAY)
    assert again.imported == 0                       # re-importing B still adds nothing


def test_excel_style_numbers_are_accepted(conn, user_id, tmp_path):
    path = write(tmp_path, "t.csv", 'D05.SI,2024-03-15,BUY,"1,000",$34.62,S$10\n', encoding="utf-8-sig")

    result = import_trades_csv(conn, user_id, path, today=TODAY)

    assert result.ok
    trade = db.get_trades(conn, user_id)[0]
    assert (trade["quantity"], trade["price"], trade["fees"]) == (1000, 34.62, 10.0)


def test_digits_from_other_scripts_are_rejected(conn, user_id, tmp_path):
    result = import_trades_csv(conn, user_id, write(tmp_path, "t.csv", "D05.SI,2024-03-15,BUY,١٠٠,34,0\n"), today=TODAY)

    assert not result.ok


def test_missing_suffix_gets_a_hint(conn, user_id, tmp_path):
    result = import_trades_csv(conn, user_id, write(tmp_path, "t.csv", "D05,2024-03-15,BUY,100,34,0\n"), today=TODAY)

    assert result.errors == ["Row 2: unknown ticker 'D05' (did you mean D05.SI?)"]


def test_total_is_unknown_when_a_held_stock_has_no_price(conn, user_id):
    db.add_trade(conn, user_id, "D05.SI", "2024-03-15", "BUY", 100, 30, 0)
    db.add_trade(conn, user_id, "O39.SI", "2024-03-15", "BUY", 100, 14, 0)
    db.save_prices(conn, "D05.SI", [("2026-11-06", 60.0)])

    s = summary(positions(conn, user_id))

    assert s["missing_prices"] == ["O39.SI"]
    assert math.isnan(s["value"]) and math.isnan(s["total_profit"])


def test_stale_prices_are_flagged(conn, user_id):
    db.add_trade(conn, user_id, "D05.SI", "2024-03-15", "BUY", 100, 30, 0)
    db.add_trade(conn, user_id, "O39.SI", "2024-03-15", "BUY", 100, 14, 0)
    db.save_prices(conn, "D05.SI", [("2026-11-06", 60.0)])
    db.save_prices(conn, "O39.SI", [("2026-10-01", 16.0)])

    s = summary(positions(conn, user_id))

    assert s["stale_prices"] == ["O39.SI"]
    assert s["prices_as_of"] == "2026-11-06"


def test_empty_portfolio_is_worth_zero(conn, user_id):
    s = summary(positions(conn, user_id))

    assert (s["value"], s["total_profit"], s["missing_prices"]) == (0, 0, [])


def test_impossible_sale_gives_a_clear_error(conn, user_id):
    db.add_trade(conn, user_id, "D05.SI", "2024-03-15", "SELL", 100, 30, 0)   # skipping the importer

    with pytest.raises(ValueError, match="sells 100 on 2024-03-15 but only 0 are held"):
        positions(conn, user_id)


def test_bonus_on_the_same_ex_date_as_a_dividend_misses_it(conn, user_id):
    db.add_trade(conn, user_id, "D05.SI", "2024-03-15", "BUY", 100, 34, 0)
    db.save_actions(conn, "D05.SI", [("2024-04-22", 1.1)])
    db.save_dividends(conn, "D05.SI", [("2024-04-22", 0.50)])

    [row] = dividends_received(conn, user_id).to_dict("records")

    assert (row["shares"], row["total"]) == (100, 50.0)


def test_price_spikes_are_flagged_unless_a_split_explains_them(conn):
    db.save_prices(conn, "D05.SI", [("2024-01-02", 34.0), ("2024-01-03", 3.4), ("2024-01-04", 34.1)])
    db.save_prices(conn, "O39.SI", [("2024-04-19", 20.0), ("2024-04-22", 10.0)])
    db.save_actions(conn, "O39.SI", [("2024-04-22", 2.0)])

    warnings = check_price_spikes(conn, ["D05.SI", "O39.SI"])

    assert len(warnings) == 2                       # down 90%, then back up; O39's split is fine
    assert all(w.startswith("D05.SI") for w in warnings)
