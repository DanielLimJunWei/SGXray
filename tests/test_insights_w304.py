"""Insights (w304): fees as a share of what you bought, and the yield-trap pattern."""

from datetime import date, timedelta

import db
from explain import FEE_ONE_BUY, FEES_HIGH, explain_total_return, explain_trades, explain_yields, fee_summary
from test_trades import add, app, db_path, downloads, saved, signed_up  # noqa: F401  (fixtures)


def rows(*trades):
    return [{"side": s, "quantity": q, "price": p, "fees": f, "ticker": "D05.SI", "trade_date": d}
            for s, q, p, f, d in trades]


def test_fees_are_added_up_against_what_the_buys_cost():
    f = fee_summary(rows(("BUY", 100, 30.0, 10.0, "2025-01-02"), ("BUY", 100, 20.0, 10.0, "2025-02-03"),
                         ("SELL", 50, 35.0, 10.0, "2025-03-03")))
    assert f["bought"] == 5000 and f["fees"] == 30 and f["pct"] == 30 / 5000     # the sale's fee counts too
    assert f["worst"] is None                                                    # $10 on $2,000 is only 0.5%


def test_a_small_buy_that_loses_over_1_percent_to_fees_is_named():
    f = fee_summary(rows(("BUY", 10, 30.0, 10.0, "2025-01-02"), ("BUY", 1000, 30.0, 10.0, "2025-02-03")))
    assert f["worst"]["amount"] == 300 and round(f["worst"]["pct"], 4) == round(10 / 300, 4)
    e = explain_trades(rows(("BUY", 10, 30.0, 10.0, "2025-01-02"), ("BUY", 1000, 30.0, 10.0, "2025-02-03")))
    assert any("2 Jan 2025 paid $10.00 in fees on $300.00: 3.3% gone" in w for w in e.watch_out)


def test_fees_over_half_a_percent_get_a_watch_out_and_under_dont():
    high = fee_summary(rows(("BUY", 100, 10.0, 10.0, "2025-01-02")))           # 1% overall
    assert high["pct"] > FEES_HIGH
    e = explain_trades(rows(("BUY", 100, 10.0, 10.0, "2025-01-02")))
    assert any("Fees are 1.00% of everything you've bought" in w for w in e.watch_out)
    low = explain_trades(rows(("BUY", 1000, 30.0, 10.0, "2025-01-02")))       # 0.03%
    assert not any(w.startswith("Fees are") for w in low.watch_out)
    assert any("Fees so far: $10.00 on $30,000.00 of buys, 0.03%" in line for line in low.lines)


def test_the_total_profit_box_shows_the_fee_share(app, db_path):
    c = signed_up(app)
    add(c, fees="10.00")                                                         # $3,520 of DBS with $10 fees
    conn = db.get_connection(db_path)
    uid = db.get_user_by_email(conn, "ann@example.com")["id"]
    e = explain_total_return(conn, uid)
    conn.close()
    assert any(line.startswith("Fees so far: $10.00 on $3,520.00 of buys, 0.28%") for line in e.lines)


def _falling_stock_with_a_big_dividend(conn, uid):
    """DBS bought at $40, its price sliding to $28 over the year (30% below the high), paying $2.00 a share:
    a 7.1% yield that's high mostly because the price fell."""
    start = date(2025, 1, 6)
    closes = [(str(start + timedelta(days=7 * i)), round(40 - 12 * i / 51, 2)) for i in range(52)]
    db.save_prices(conn, "D05.SI", closes)
    db.save_prices(conn, "ES3.SI", [(d, 3.5) for d, _ in closes])
    db.add_trade(conn, uid, "D05.SI", "2025-01-06", "BUY", 100, 40.0, 10.0)
    db.save_dividends(conn, "D05.SI", [("2025-06-02", 2.0)])
    return closes[-1][0]


def test_a_high_yield_from_a_falling_price_gets_the_yield_trap_warning(db_path):
    conn = db.get_connection(db_path)
    uid = db.create_user(conn, "zed@example.com", "x")
    last = _falling_stock_with_a_big_dividend(conn, uid)
    e = explain_yields(conn, uid, last)
    conn.close()
    trap = [w for w in e.watch_out if "classic yield-trap pattern" in w]
    assert trap and "30% below its 52-week high ($40.00)" in trap[0]


def test_a_high_yield_on_a_steady_price_gets_only_the_gentle_warning(db_path):
    conn = db.get_connection(db_path)
    uid = db.create_user(conn, "zed@example.com", "x")
    start = date(2025, 1, 6)
    closes = [(str(start + timedelta(days=7 * i)), 25.0) for i in range(52)]     # flat at $25
    db.save_prices(conn, "D05.SI", closes)
    db.add_trade(conn, uid, "D05.SI", "2025-01-06", "BUY", 100, 25.0, 10.0)
    db.save_dividends(conn, "D05.SI", [("2025-06-02", 2.0)])                     # 8% yield, price not falling
    e = explain_yields(conn, uid, closes[-1][0])
    conn.close()
    assert not any("classic yield-trap pattern" in w for w in e.watch_out)
    assert any("unusually high" in w for w in e.watch_out)
    assert FEE_ONE_BUY == 0.01
