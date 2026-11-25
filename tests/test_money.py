"""Money in whole cents (w414): saved and shown the way a broker or a person would round it, half a cent up, and
every screen agreeing with every other."""

import json
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

import db
import fmt
import plans
import practice

ROOT = Path(__file__).resolve().parent.parent

# (number, what a person writes to the cent). Each of these trips up plain round() or "%.2f" on a float.
HALF_CENTS = [(2.675, 2.68), (1.005, 1.01), (-2.675, -2.68), (0.125, 0.13), (10503.775, 10503.78),
              (1234567.895, 1234567.9), (0.1 + 0.2, 0.3), (0.0049, 0.0), (0.005, 0.01), (-0.004, 0.0)]


@pytest.mark.parametrize("x, want", HALF_CENTS)
def test_half_a_cent_rounds_up_like_on_paper(x, want):
    assert fmt.cents(x) == want


def test_shown_money_never_says_minus_zero():
    assert fmt.money(2.675) == "$2.68"
    assert fmt.money(-0.004) == "$0.00" and fmt.money(-0.004, signed=True) == "$0.00"
    assert fmt.money(0.004, signed=True) == "$0.00"
    assert fmt.money(-10503.775) == "-$10,503.78" and fmt.money(1234.565, signed=True) == "+$1,234.57"


def test_fees_are_saved_in_whole_cents_on_every_path(conn):
    uid = db.create_user(conn, "cents@example.com", "x")
    one = db.add_trade(conn, uid, "D05.SI", "2024-03-15", "BUY", 100, 35.125, 10.675)
    db.add_trades(conn, uid, [{"ticker": "D05.SI", "trade_date": "2024-03-18", "side": "BUY", "quantity": 100,
                               "price": 35.2, "fees": 1.005}])
    rows = {r["trade_date"]: r for r in db.get_trades(conn, uid)}
    assert rows["2024-03-15"]["fees"] == 10.68 and rows["2024-03-18"]["fees"] == 1.01
    assert rows["2024-03-15"]["price"] == 35.125                     # prices keep their decimals (0.001 ticks)
    t = dict(db.get_trade(conn, uid, one))
    t["fees"] = 2.675
    assert db.update_trade(conn, uid, one, t)
    assert db.get_trade(conn, uid, one)["fees"] == 2.68


def test_practice_fee_parts_always_add_up_to_the_total():
    # Every whole-dollar trade from $1 to $20,000 at a few broker rates: the parts shown must sum to the total.
    for rate, minimum in ((0.0008, 10.0), (0.00127, 0.0), (0.0028, 25.0)):
        for amount in range(1, 20001, 7):
            f = practice.fee(amount, rate, minimum)
            assert fmt.cents(f["commission"] + f["sgx"] + f["gst"]) == f["total"], (amount, rate, f)
            for part in f.values():
                assert fmt.cents(part) == part


def test_a_monthly_plans_fee_and_amount_are_in_cents(conn):
    assert plans.fee(1234.5, 0.0025, 0) == 3.09                     # 3.08625 -> 3.09
    v, problems = plans.from_form(conn, {"ticker": "ES3.SI", "amount": "100.005", "day": "5", "fee_rate": "0.08",
                                         "fee_min": "1.255", "start": "2025-01"}, today=date(2026, 11, 26))
    assert problems == [] and v["amount"] == 100.01 and v["fee_min"] == 1.26


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js isn't installed")
def test_the_charts_round_money_the_same_way_as_the_server():
    script = ("globalThis.window = {}; globalThis.document = {}; require(%s);"
              "const C = window.SGXrayCompare; console.log(JSON.stringify(%s.map(([x]) => [C.money(x), C.signed(x)])));"
              % (json.dumps(str(ROOT / "static" / "js" / "compare.js")), json.dumps(HALF_CENTS)))
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == [[fmt.money(x), fmt.money(x, signed=True)] for x, _ in HALF_CENTS]
