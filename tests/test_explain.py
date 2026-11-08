"""Tests for the plain-English explanations (explain.py). The sentences must match the numbers."""

import db
from explain import _reason, explain_month


def setup_two_months(conn, user_id):
    """Bought 100 DBS at $30 (+$10 fee) on 15 Jan 2024. ES3 is flat at $3.00.
    Close: $31 at the end of January, $29 at the end of February; a $0.50 dividend in February."""
    db.add_trade(conn, user_id, "D05.SI", "2024-01-15", "BUY", 100, 30.0, 10)
    db.save_prices(conn, "D05.SI", [("2024-01-15", 30.0), ("2024-01-31", 31.0), ("2024-02-29", 29.0)])
    db.save_prices(conn, "ES3.SI", [("2024-01-15", 3.0), ("2024-01-31", 3.0), ("2024-02-29", 3.0)])
    db.save_dividends(conn, "D05.SI", [("2024-02-08", 0.50)])


def test_first_month_tells_the_story(conn, user_id):
    setup_two_months(conn, user_id)

    text = " ".join(explain_month(conn, user_id, "2024-01"))

    assert "On 15 January 2024 you bought 100 D05.SI for $3,010.00 (including $10.00 in fees)." in text
    assert "your shares were worth $3,100.00" in text
    assert "$3,100.00 worth - $3,010.00 put in = $90.00 up." in text
    # STI version: $3,000 of ES3 (after the same $10 fee), still $3,000 -> $10.00 down
    assert "would have been $10.00 down. So you were $100.00 ahead of the market." in text


def test_change_since_last_month_is_explained(conn, user_id):
    setup_two_months(conn, user_id)

    text = " ".join(explain_month(conn, user_id, "2024-02"))

    assert "You earned dividends this month: $50.00 from D05.SI (100 shares x $0.5)." in text
    # profit: Jan $90 -> Feb 2,900 - 3,010 + 50 = -$60, so it shrank by $150 = prices -$200, dividends +$50
    assert "your profit shrank by $150.00: prices fell by $200.00, partly made up for by $50.00 of dividends." in text
    assert "Buying or selling" not in text          # nothing was traded in February


def test_reasons_read_naturally():
    assert _reason(288, 0) == "prices rose by $288.00"
    assert _reason(-100, 150) == "prices fell by $100.00, but $150.00 of dividends more than made up for it"
    assert _reason(0, 40) == "you received $40.00 in dividends (prices ended about where they were)"


def test_month_without_a_snapshot(conn, user_id):
    setup_two_months(conn, user_id)

    assert "There's no snapshot for 2030-01" in explain_month(conn, user_id, "2030-01")[0]
