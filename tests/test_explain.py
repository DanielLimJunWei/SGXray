"""Tests for the plain-English explanations (explain.py). The sentences must match the numbers."""

import db
from explain import (_reason, explain_forecast, explain_holdings, explain_month,
                     explain_performance, explain_value_chart, explain_yields)


def setup_two_months(conn, user_id):
    """Bought 100 DBS at $30 (+$10 fee) on 15 Jan 2024. ES3 is flat at $3.00.
    Close: $31 at the end of January, $29 at the end of February; a $0.50 dividend in February."""
    db.add_trade(conn, user_id, "D05.SI", "2024-01-15", "BUY", 100, 30.0, 10)
    db.save_prices(conn, "D05.SI", [("2024-01-15", 30.0), ("2024-01-31", 31.0), ("2024-02-29", 29.0)])
    db.save_prices(conn, "ES3.SI", [("2024-01-15", 3.0), ("2024-01-31", 3.0), ("2024-02-29", 3.0)])
    db.save_dividends(conn, "D05.SI", [("2024-02-08", 0.50)])


def test_first_month_tells_the_story(conn, user_id):
    setup_two_months(conn, user_id)

    text = explain_month(conn, user_id, "2024-01").text

    assert "On 15 January 2024 you bought 100 D05.SI for $3,010.00 (including $10.00 in fees)." in text
    assert "your shares were worth $3,100.00" in text
    assert "$3,100.00 worth - $3,010.00 put in = $90.00 up." in text
    # STI version: $3,000 of ES3 (after the same $10 fee), still $3,000 -> $10.00 down
    assert "would have been $10.00 down. So you were $100.00 ahead of the market." in text


def test_change_since_last_month_is_explained(conn, user_id):
    setup_two_months(conn, user_id)

    text = explain_month(conn, user_id, "2024-02").text

    assert "You earned dividends this month: $50.00 from D05.SI (100 shares x $0.5)." in text
    # profit: Jan $90 -> Feb 2,900 - 3,010 + 50 = -$60, so it shrank by $150 = prices -$200, dividends +$50
    assert "your profit shrank by $150.00: prices fell by $200.00, partly made up for by $50.00 of dividends." in text
    assert "Buying or selling" not in text          # nothing was traded in February


def test_reasons_read_naturally():
    assert _reason(288, 0) == "prices rose by $288.00"
    assert _reason(-100, 150) == "prices fell by $100.00, but $150.00 of dividends more than made up for it"
    assert _reason(0, 40) == "you received $40.00 in dividends (prices ended about where they were)"


def dbs_bought_cheap(conn, user_id):
    """200 DBS at $40; now $70. Paid $0.75 + $0.81 x 3 = $3.18 a share in the last year."""
    db.add_trade(conn, user_id, "D05.SI", "2025-01-02", "BUY", 200, 40.0, 0)
    db.save_prices(conn, "D05.SI", [("2025-01-02", 40.0), ("2026-11-06", 70.0)])
    db.save_dividends(conn, "D05.SI", [("2025-11-13", 0.75), ("2026-04-08", 0.81),
                                       ("2026-05-11", 0.81), ("2026-08-14", 0.81)])


def test_yields_are_explained_with_the_stocks_own_numbers(conn, user_id):
    dbs_bought_cheap(conn, user_id)

    text = explain_yields(conn, user_id).text

    assert "Yield: $3.18 divided by today's price $70.00 = 4.54%" in text
    assert "On cost: $3.18 divided by your average cost $40.00 = 7.95%" in text
    assert "because you bought for less than they cost now" in text
    assert "D05.SI (7.95% on cost, 4.54% for a new buyer)" in text
    assert "$636.00, divided by what it's all worth today = 4.54% a year" in text


def test_forecast_is_explained_with_an_example_and_its_limits(conn, user_id):
    dbs_bought_cheap(conn, user_id)

    text = explain_forecast(conn, user_id).text

    assert "around 13 November 2026 you can expect about 200 x $0.75 = $150.00" in text
    assert "In total, about $636.00 over 4 months with payouts" in text
    assert "It's only an estimate" in text


def test_watch_out_on_cost_trap_and_one_stock_income(conn, user_id):
    dbs_bought_cheap(conn, user_id)

    yields_watch = " ".join(explain_yields(conn, user_id).watch_out)
    forecast_watch = " ".join(explain_forecast(conn, user_id).watch_out)

    assert "Compare stocks using 'Yield', not 'On cost'" in yields_watch
    assert "yield trap" not in yields_watch                    # 4.54% isn't unusually high
    assert "the price usually drops by about the dividend" in forecast_watch
    assert "come from one stock" not in forecast_watch         # only one stock: nothing to compare


def test_watch_out_high_yield_and_concentration(conn, user_id):
    dbs_bought_cheap(conn, user_id)
    db.add_trade(conn, user_id, "C38U.SI", "2025-01-02", "BUY", 100, 1.0, 0)
    db.save_prices(conn, "C38U.SI", [("2025-01-02", 1.0), ("2026-11-06", 1.0)])
    db.save_dividends(conn, "C38U.SI", [("2026-02-13", 0.10)])     # 10% yield

    assert "yield trap" in " ".join(explain_yields(conn, user_id).watch_out)
    assert "come from one stock, D05.SI" in " ".join(explain_forecast(conn, user_id).watch_out)
    assert "of your portfolio's value is in one stock, D05.SI" in " ".join(explain_holdings(conn, user_id).watch_out)


def test_holdings_explained_with_bonus_and_unrealised_warnings(conn, user_id):
    dbs_bought_cheap(conn, user_id)
    db.save_actions(conn, "D05.SI", [("2026-09-01", 1.1)])

    e = explain_holdings(conn, user_id)

    assert "you own 220 shares. They cost you $8,000.00 in total" in e.text
    watch = " ".join(e.watch_out)
    assert "Bonus shares aren't free money" in watch
    assert "isn't money in your bank until you sell" in watch


def test_vs_sti_explained_with_skill_or_luck(conn, user_id):
    db.add_trade(conn, user_id, "D05.SI", "2024-01-02", "BUY", 10, 100.0, 0)
    db.add_trade(conn, user_id, "O39.SI", "2024-01-02", "BUY", 100, 10.0, 0)
    db.save_prices(conn, "ES3.SI", [("2024-01-02", 2.00), ("2025-01-01", 2.20)])
    db.save_prices(conn, "D05.SI", [("2025-01-01", 200.0)])
    db.save_prices(conn, "O39.SI", [("2025-01-01", 8.0)])

    e = explain_performance(conn, user_id)

    assert "D05.SI helped you" in e.text
    assert "O39.SI held you back" in e.text
    assert "Skill or luck? Most of your lead comes from one stock, D05.SI" in " ".join(e.watch_out)


def test_two_returns_section_reads_the_users_own_gap():
    from explain import _two_returns_section

    close = " ".join(_two_returns_section(0.3208, 0.3417))
    helped = " ".join(_two_returns_section(0.40, 0.00))
    hurt = " ".join(_two_returns_section(-0.10, 0.05))

    assert "Why SGXray shows two returns" in close
    assert "are close, so your timing didn't help or hurt much" in close
    assert "so your timing helped" in helped
    assert "so your timing cost you" in hurt


def test_bad_timing_gets_a_watch_out(conn, user_id):
    # Price 100 -> 150 -> 75. A small buy at the start, a big buy at the top: picks fell 25%,
    # but most of the money went in at the top, so you lost much more.
    db.add_trade(conn, user_id, "D05.SI", "2024-01-02", "BUY", 10, 100.0, 0)
    db.add_trade(conn, user_id, "D05.SI", "2024-07-01", "BUY", 100, 150.0, 0)
    db.save_prices(conn, "D05.SI", [("2024-01-02", 100.0), ("2024-07-01", 150.0), ("2025-01-02", 75.0)])
    db.save_prices(conn, "ES3.SI", [("2024-01-02", 3.0), ("2024-07-01", 3.0), ("2025-01-02", 3.0)])

    from explain import explain_two_returns
    e = explain_two_returns(conn, user_id)          # timing is explained once, under "You vs the STI a year"

    assert "so your timing cost you" in e.text
    assert "Adding money bit by bit on a schedule" in " ".join(e.watch_out)
    assert "why SGXray shows two returns, see" in explain_performance(conn, user_id).text   # the stock table just points there


def test_short_history_warns_about_extreme_yearly_rates(conn, user_id):
    db.add_trade(conn, user_id, "D05.SI", "2024-01-02", "BUY", 10, 100.0, 0)
    db.save_prices(conn, "ES3.SI", [("2024-01-02", 2.00), ("2024-03-01", 2.20)])
    db.save_prices(conn, "D05.SI", [("2024-03-01", 110.0)])

    assert "about +77% a year" in " ".join(explain_performance(conn, user_id).watch_out)


def test_nothing_held_is_explained_too(conn, user_id):
    assert "don't hold any stocks" in explain_yields(conn, user_id).lines[0]
    assert "No dividends are expected" in explain_forecast(conn, user_id).lines[0]


def test_month_without_a_snapshot(conn, user_id):
    setup_two_months(conn, user_id)

    assert "There's no snapshot for 2030-01" in explain_month(conn, user_id, "2030-01").lines[0]


def test_xray_chart_explains_its_layers(conn, user_id):
    setup_two_months(conn, user_id)
    ex = explain_value_chart(conn, user_id)
    text = ex.text
    # End of February: $3,010 put in; worth 100 x $29 = $2,900 (-$110 from prices); $50 of dividends.
    assert "Your own money (the plain dark-blue area at the bottom): $3,010.00" in text
    assert "light-blue line along the top is your TOTAL" in text and "top edge" not in text
    assert "Price gains (blue dots): $110.00 down" in text
    assert "Dividends (amber dots): $50.00" in text
    assert any("isn't all profit" in w for w in ex.watch_out)
    assert any("loss on paper" in w for w in ex.watch_out)        # prices are below what was paid
    assert any("Less than a year" in w for w in ex.watch_out)


def test_xray_chart_with_no_history(conn, user_id):
    assert "no history" in explain_value_chart(conn, user_id).text


def test_income_by_year_explains_part_years(conn, user_id):
    from explain import explain_income_by_year
    setup_two_months(conn, user_id)          # started 15 Jan 2024, newest price 29 Feb 2024
    ex = explain_income_by_year(conn, user_id)
    assert "isn't over yet: $50.00 so far, to 29 February 2024" in ex.text
    assert any("part-year" in w for w in ex.watch_out)


def test_two_returns_explains_both_numbers(conn, user_id):
    from explain import explain_two_returns
    setup_two_months(conn, user_id)
    db.save_prices(conn, "D05.SI", [("2024-03-28", 33.0)])          # long enough for a yearly rate
    db.save_prices(conn, "ES3.SI", [("2024-03-28", 3.1)])
    ex = explain_two_returns(conn, user_id)
    assert "money-weighted return (XIRR)" in ex.text and "time-weighted return (TWR)" in ex.text
    assert "Why SGXray shows two returns:" in ex.text
    assert any("Less than a year" in w for w in ex.watch_out)
