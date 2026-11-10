"""Per-stock price charts: the price line, your trades and the average-cost steps."""

import db
from explain import explain_stock_chart
from stocks import last_avg, stock_history


def setup(conn, user_id):
    """Buy 100 at $30 (+$10), a 1-for-10 bonus issue, then buy 100 more at $40 (+$10)."""
    db.add_trade(conn, user_id, "D05.SI", "2024-01-15", "BUY", 100, 30.0, 10)
    db.add_trade(conn, user_id, "D05.SI", "2024-06-03", "BUY", 100, 40.0, 10)
    db.save_prices(conn, "D05.SI", [("2024-01-15", 30.0), ("2024-04-22", 28.0), ("2024-06-03", 40.0), ("2024-06-28", 42.0)])
    db.add_manual_action(conn, "D05.SI", "2024-04-22", 1.1)
    db.save_dividends(conn, "D05.SI", [("2024-05-10", 0.50)])


def test_average_cost_steps_at_trades_and_bonus(conn, user_id):
    setup(conn, user_id)
    h = stock_history(conn, user_id, "D05.SI")
    steps = [(s["date"], s["avg"], s["shares"]) for s in h["avg_steps"]]
    # $3,010 / 100 = $30.10; bonus: $3,010 / 110 = $27.3636; then ($3,010 + $4,010) / 210 = $33.4286
    assert steps == [("2024-01-15", 30.1, 100), ("2024-04-22", 27.3636, 110), ("2024-06-03", 33.4286, 210)]
    assert last_avg(h) == 33.4286
    assert h["dividends"] == [{"date": "2024-05-10", "amount": 0.5, "shares": 110, "total": 55.0}]
    assert [p[0] for p in h["prices"]][-1] == "2024-06-28"


def test_explanation_mentions_the_bonus_and_the_gap(conn, user_id):
    setup(conn, user_id)
    ex = explain_stock_chart(conn, user_id, "D05.SI")
    assert "It's $33.43 now; the price on 28 June 2024 was $42.00, 25.6% above it." in ex.text
    assert any("bonus issue" in w for w in ex.watch_out)


def test_no_chart_for_a_stock_you_never_traded(conn, user_id):
    setup(conn, user_id)
    assert stock_history(conn, user_id, "C38U.SI") is None
