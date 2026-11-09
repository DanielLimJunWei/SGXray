"""Audit 3 (9 Nov 2026): invariants on random portfolios, plus the real-world cases it found.

The random tests build portfolios with random trades, prices, dividends, splits and bonus
issues, then check that every calculation agrees with every other. Any disagreement is a bug.
"""

import random
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

import db
from adjust import shares_after
from fmt import money, pct
from history import time_weighted, value_history
from income import forecast, yields
from market import SGT, update_prices
from performance import compare, per_stock, portfolio_flows, xirr, _npv
from portfolio import dividends_received, positions, summary

TICKERS = ["D05.SI", "O39.SI", "C38U.SI", "ES3.SI"]


def random_portfolio(conn, user_id, seed):
    rng = random.Random(seed)
    start = date(2023, 1, 2)
    days = [start + timedelta(days=i) for i in range(700) if (start + timedelta(days=i)).weekday() < 5]
    days = [d for d in days if rng.random() > 0.03]                      # random holidays
    actions = {}
    for t in TICKERS:
        price, rows = rng.uniform(1, 60), []
        for d in days:
            price = max(0.05, price * (1 + rng.gauss(0, 0.015)))
            rows.append((d.isoformat(), round(price, 4)))
        if rng.random() < 0.3:
            ex, f = rng.choice(days[100:-100]).isoformat(), rng.choice([1.1, 2.0, 0.5])
            actions[t] = (ex, f)
            db.save_actions(conn, t, [(ex, f)])
        db.save_prices(conn, t, rows)
        db.save_dividends(conn, t, [(d.isoformat(), round(rng.uniform(0.01, 1.0), 4)) for d in days[::90]])
    used = sorted(set(rng.sample(TICKERS, rng.randint(1, 4))))
    trades = []
    for d in sorted(rng.sample(days[:-5], rng.randint(2, 20))):
        t = rng.choice(used)
        held = shares_held(trades, actions, t, d.isoformat())
        side = "SELL" if held and rng.random() < 0.35 else "BUY"
        q = rng.randint(1, held) if side == "SELL" else rng.choice([1, 10, 100, 1000])
        close = db.get_close(conn, t, d.isoformat())
        trades.append({"ticker": t, "trade_date": d.isoformat(), "side": side, "quantity": q,
                       "price": round(close * rng.uniform(0.98, 1.02), 3), "fees": rng.choice([0, 5, 25.9])})
    db.add_trades(conn, user_id, trades)
    return trades, actions


def shares_held(trades, actions, ticker, upto):
    """An independent share count, written separately from the app's own code."""
    events = [(t["trade_date"], 1, t) for t in trades if t["ticker"] == ticker and t["trade_date"] <= upto]
    if ticker in actions and actions[ticker][0] <= upto:
        events.append((actions[ticker][0], 0, None))
    shares = 0
    for _, kind, t in sorted(events, key=lambda e: (e[0], e[1])):
        if kind == 0:
            shares = shares_after(shares, actions[ticker][1])
        else:
            shares += t["quantity"] if t["side"] == "BUY" else -t["quantity"]
    return shares


@pytest.mark.parametrize("seed", range(12))
def test_every_number_agrees_on_random_portfolios(conn, user_id, seed):
    trades, actions = random_portfolio(conn, user_id, seed)
    pos = positions(conn, user_id)
    s = summary(pos)
    last_day = db.get_trading_days(conn)[-1]

    for r in pos.itertuples():                                              # shares
        assert r.shares == shares_held(trades, actions, r.ticker, last_day)

    money_in = sum(t["quantity"] * t["price"] + t["fees"] for t in trades if t["side"] == "BUY")
    money_out = sum(t["quantity"] * t["price"] - t["fees"] for t in trades if t["side"] == "SELL")
    paid = dividends_received(conn, user_id)["total"].sum()
    assert s["total_profit"] == pytest.approx(money_out + s["value"] + paid - money_in)   # money adds up

    h = value_history(conn, user_id)                                        # history = snapshot
    assert h["profit"].iloc[-1] == pytest.approx(s["total_profit"])
    assert h["net_invested"].iloc[-1] == pytest.approx(money_in - money_out)

    c = compare(conn, user_id)                                              # comparisons agree
    assert h["sti_profit"].iloc[-1] == pytest.approx(c["benchmark_profit"], abs=1e-6)
    flows, end, value = portfolio_flows(conn, user_id)
    if c["you"] == c["you"] and c["you"] > -0.999:
        assert abs(_npv(c["you"], sorted(flows + [(end, value)]))) < 1e-3
    ps = per_stock(conn, user_id)
    if not c["shortfall"] and not ps["shortfall"].any():
        assert ps["difference"].sum() == pytest.approx(c["your_profit"] - c["benchmark_profit"], abs=1e-4)

    assert forecast(conn, user_id)["total"].sum() == pytest.approx(yields(conn, user_id)["income_12m"].sum())
    assert time_weighted(conn, user_id)["you_total"] == time_weighted(conn, user_id)["you_total"]   # not NaN


# ---------- Real-world cases found by audit 3 ----------

def fake_yahoo(ticker, start, end):
    rows, d = [], start
    while d <= end:
        if d.weekday() < 5:
            rows.append((d.isoformat(), 10.0))
        d += timedelta(days=1)
    return rows


def test_older_trades_added_later_get_their_prices(conn, user_id):
    now = datetime(2025, 6, 2, 18, 0, tzinfo=SGT)
    db.add_trade(conn, user_id, "D05.SI", "2025-01-02", "BUY", 100, 10.0, 0)
    update_prices(conn, ["D05.SI", "ES3.SI"], now=now, download=fake_yahoo, pause=0)
    db.add_trade(conn, user_id, "D05.SI", "2024-06-03", "BUY", 100, 10.0, 0)    # back-dated
    update_prices(conn, ["D05.SI", "ES3.SI"], now=now, download=fake_yahoo, pause=0)

    assert db.get_earliest_price_date(conn, "D05.SI") == "2024-06-03"
    assert db.get_earliest_price_date(conn, "ES3.SI") == "2024-06-03"
    assert compare(conn, user_id)["you"] == pytest.approx(0, abs=1e-9)        # used to crash


def test_missing_price_on_a_trade_day_is_filled_by_the_trade_price(conn, user_id):
    db.add_trade(conn, user_id, "D05.SI", "2024-06-03", "BUY", 100, 10.0, 0)
    db.save_prices(conn, "D05.SI", [("2024-06-04", 10.0), ("2025-06-02", 11.0)])   # Yahoo missed 3 June
    db.save_prices(conn, "ES3.SI", [("2024-06-03", 3.0), ("2025-06-02", 3.3)])

    assert value_history(conn, user_id)["value"].iloc[0] == 1000
    assert time_weighted(conn, user_id)["you_total"] == pytest.approx(0.10)    # was NaN


def test_benchmark_missing_its_first_price_uses_the_next_one(conn, user_id):
    db.add_trade(conn, user_id, "D05.SI", "2024-06-03", "BUY", 100, 10.0, 0)
    db.save_prices(conn, "D05.SI", [("2024-06-03", 10.0), ("2025-06-02", 11.0)])
    db.save_prices(conn, "ES3.SI", [("2024-06-04", 3.0), ("2025-06-02", 3.3)])

    assert compare(conn, user_id)["benchmark"] == pytest.approx(0.10, abs=0.01)  # used to crash


def test_sold_out_portfolio_is_compared_up_to_today(conn, user_id):
    db.add_trade(conn, user_id, "D05.SI", "2024-01-02", "BUY", 100, 30.0, 0)
    db.add_trade(conn, user_id, "D05.SI", "2024-06-03", "SELL", 100, 35.0, 0)
    db.save_prices(conn, "D05.SI", [("2024-01-02", 30.0), ("2024-06-03", 35.0), ("2025-01-02", 40.0)])
    db.save_prices(conn, "ES3.SI", [("2024-01-02", 3.0), ("2024-06-03", 3.1), ("2025-01-02", 3.3)])

    c = compare(conn, user_id)
    h = value_history(conn, user_id)

    assert c["end"] == date(2025, 1, 2) and h.index[-1] == pd.Timestamp("2025-01-02")
    assert h["sti_profit"].iloc[-1] == pytest.approx(c["benchmark_profit"])


def test_numbers_are_shown_the_same_way_everywhere():
    assert money(-200) == "-$200.00"
    assert money(1234.5) == "$1,234.50"
    assert money(5, signed=True) == "+$5.00"
    assert money(float("nan")) == "n/a"
    assert pct(0.1234) == "+12.34%"
    assert pct(float("nan")) == "n/a"
    assert xirr([]) != xirr([])          # NaN in, NaN out; fmt turns it into "n/a"
