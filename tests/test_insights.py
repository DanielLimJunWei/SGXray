"""The six portfolio-page extras: day's change, simple return, weights, period returns,
sold-out stocks and the 52-week range. Each number is checked by hand."""

import pytest

import db
from explain import explain_periods, explain_sold, explain_total_return, explain_worth
from history import period_returns, value_history
from insights import day_change, money_put_in, simple_return, sold_out, week52, weights
from portfolio import positions


def setup(conn, user_id):
    """100 DBS at $30 (+$10 fee) on 2 Jan 2024; closes $30 -> $33 -> $32.
    1,000 C38U at $2 (+$10) sold at $2.20 (-$10): fully sold. ES3 flat at $3."""
    db.add_trade(conn, user_id, "D05.SI", "2024-01-02", "BUY", 100, 30.0, 10)
    db.add_trade(conn, user_id, "C38U.SI", "2024-01-02", "BUY", 1000, 2.0, 10)
    db.add_trade(conn, user_id, "C38U.SI", "2024-06-03", "SELL", 1000, 2.2, 10)
    db.save_prices(conn, "D05.SI", [("2024-01-02", 30.0), ("2024-06-03", 33.0), ("2024-06-04", 32.0)])
    db.save_prices(conn, "C38U.SI", [("2024-01-02", 2.0), ("2024-06-03", 2.2), ("2024-06-04", 2.25)])
    db.save_prices(conn, "ES3.SI", [("2024-01-02", 3.0), ("2024-06-03", 3.0), ("2024-06-04", 3.0)])


def test_day_change_is_the_last_close_move(conn, user_id):
    setup(conn, user_id)
    d = day_change(conn, user_id, value_history(conn, user_id))
    assert d["date"] == "2024-06-04" and d["previous"] == "2024-06-03"
    assert d["change"] == pytest.approx(-100.0)          # 100 DBS x ($32 - $33); C38U is sold, so it doesn't count
    assert d["pct"] == pytest.approx(-100 / 3300)
    assert [m["ticker"] for m in d["movers"]] == ["D05.SI"]


def test_simple_return_divides_by_all_money_put_in(conn, user_id):
    setup(conn, user_id)
    assert money_put_in(conn, user_id) == pytest.approx(3010 + 2010)
    r = simple_return(conn, user_id)
    # Profit: DBS $3,200 - $3,010 = +$190; C38U sold: $2,200 - $10 - $2,010 = +$180. Total +$370.
    assert r["profit"] == pytest.approx(370.0)
    assert r["pct"] == pytest.approx(370 / 5020)


def test_weights_add_up_to_one(conn, user_id):
    setup(conn, user_id)
    assert weights(positions(conn, user_id)) == {"D05.SI": pytest.approx(1.0)}


def test_sold_out_lists_closed_positions(conn, user_id):
    setup(conn, user_id)
    rows = sold_out(conn, user_id)
    assert len(rows) == 1
    r = rows[0]
    assert (r["ticker"], r["first_buy"], r["last_sale"]) == ("C38U.SI", "2024-01-02", "2024-06-03")
    assert (r["put_in"], r["got_back"]) == (pytest.approx(2010.0), pytest.approx(2190.0))
    assert r["realised"] == pytest.approx(180.0)
    assert "would I buy it again today?" in " ".join(explain_sold(rows).watch_out)


def test_period_returns_skip_stretches_longer_than_your_history(conn, user_id):
    setup(conn, user_id)
    rows = {r["key"]: r for r in period_returns(conn, user_id)}
    assert rows["1M"]["available"] and rows["3M"]["available"]
    assert not rows["1Y"]["available"]                     # only 5 months of history
    assert rows["All"]["you"] == pytest.approx(
        [r for r in period_returns(conn, user_id) if r["key"] == "All"][0]["you"])
    assert "1Y will appear once you have that much history." in " ".join(explain_periods(list(rows.values())).watch_out)


def test_week52_range_and_position(conn, user_id):
    setup(conn, user_id)
    db.save_prices(conn, "D05.SI", [(f"2024-02-{d:02d}", 30 + d / 10) for d in range(1, 29)])
    w = week52(conn, "D05.SI", "2024-06-04")
    assert w["high"] == 33.0 and w["low"] == 30.0 and w["now"] == 32.0
    assert w["position"] == pytest.approx(2 / 3)
    assert week52(conn, "ES3.SI", "2024-06-04") is None   # 3 prices isn't a year's range


def test_explanations_never_show_nan_without_prices(conn, user_id):
    db.add_trade(conn, user_id, "D05.SI", "2024-01-02", "BUY", 100, 30.0, 10)
    for text in (explain_worth(conn, user_id, None).text, explain_total_return(conn, user_id).text):
        assert "can't be added up yet" in text and "next price update" in text     # a reason, and when it fills in
        assert "nan" not in text.lower()
