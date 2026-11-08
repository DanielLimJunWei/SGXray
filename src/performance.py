"""Performance: your yearly return, and what the same money would have done in the STI ETF.

WHY NOT JUST "PROFIT / COST"? You put money in at different times. $1,000 that grew 10% in
one month is far better than $1,000 that grew 10% in five years, and a simple % can't tell
them apart. So SGXray uses the MONEY-WEIGHTED RETURN (XIRR, the same as Excel's XIRR):

    The single yearly growth rate that, applied to every amount you put in or took out
    on its own date, ends up exactly at what you have now.

THE FAIR COMPARISON: SGXray replays YOUR cash flows into the STI ETF (ES3). Every time you
bought something, the same dollars buy ES3 that day; every time you sold, the same dollars
come out of ES3. ES3's own dividends are paid out like yours were. Then both get the same
XIRR, so the only difference is what you picked.

    python src/performance.py
"""

import sys
from dataclasses import dataclass
from datetime import date

import db
from market import BENCHMARK
from portfolio import dividends_received, positions, summary, trades_frame

DAYS_PER_YEAR = 365.0      # Excel's XIRR uses 365-day years too


# ---------- XIRR ----------

def _npv(rate, flows):
    """Net present value: what all the flows are worth on the first date, at a yearly rate."""
    start = flows[0][0]
    return sum(amount / (1 + rate) ** ((day - start).days / DAYS_PER_YEAR) for day, amount in flows)


def xirr(flows, low=-0.9999, high=100.0, tolerance=1e-10):
    """The yearly rate that makes the NPV of (date, amount) flows zero. Money in is negative,
    money out (and what you hold at the end) is positive.

    Solved by BISECTION: NPV goes down as the rate goes up, so we keep halving the range that
    contains zero. Slower than Excel's method (Newton's) but it can't shoot off and fail.
    Returns NaN if there's no answer (e.g. money only ever went in, or only came out).
    """
    flows = sorted((d, a) for d, a in flows if a != 0)
    if not flows or all(a > 0 for _, a in flows) or all(a < 0 for _, a in flows):
        return float("nan")
    if (flows[-1][0] - flows[0][0]).days == 0:
        return float("nan")                     # everything on one day: no time for a yearly rate
    f_low, f_high = _npv(low, flows), _npv(high, flows)
    if f_low * f_high > 0:
        return float("nan")                     # no rate in the range makes it zero
    for _ in range(300):
        mid = (low + high) / 2
        f_mid = _npv(mid, flows)
        if abs(f_mid) < tolerance or high - low < tolerance:
            return mid
        if f_low * f_mid < 0:
            high = mid
        else:
            low, f_low = mid, f_mid
    return (low + high) / 2


# ---------- Your cash flows ----------

def portfolio_flows(conn, user_id, as_of=None):
    """Your money in and out as (date, amount) pairs, plus your holdings' value at the end.

    BUY = money in (negative), SELL = money out (positive), dividend = money out on its
    ex-date (the cash really arrives a few weeks later; close enough for a yearly rate).
    Returns (flows, end_date, end_value); end_value is NaN if a price is missing.
    """
    trades = trades_frame(conn, user_id, as_of)
    if trades.empty:
        return [], None, 0.0
    flows = []
    for t in trades.itertuples():
        day = date.fromisoformat(t.trade_date)
        if t.side == "BUY":
            flows.append((day, -(t.quantity * t.price + t.fees)))
        else:
            flows.append((day, t.quantity * t.price - t.fees))
    for d in dividends_received(conn, user_id, as_of).itertuples():
        flows.append((date.fromisoformat(d.ex_date), d.total))

    s = summary(positions(conn, user_id, as_of))
    end = date.fromisoformat(as_of or s["prices_as_of"] or max(t for t in trades["trade_date"]))
    return flows, end, s["value"]


# ---------- The same money in the STI ETF ----------

@dataclass
class BenchmarkResult:
    flows: list              # the benchmark's own (date, amount) flows, ending with its value
    units: float             # ES3 units held at the end
    value: float             # their value at the end
    dividends: float         # ES3 dividends paid out along the way
    shortfall: bool = False  # True if a sale took out more than the ES3 holding was worth


def benchmark(conn, user_id, as_of=None, ticker=BENCHMARK):
    """Replays your buys and sells, in dollars, into the benchmark ETF.

    Units can be fractions here: it's a what-if, and whole lots would make the comparison
    depend on rounding rather than on what you picked.
    """
    trades = trades_frame(conn, user_id, as_of)
    if trades.empty:
        return BenchmarkResult([], 0.0, 0.0, 0.0)

    # Every dated event, in order: our trades' dollars, plus the ETF's dividends and splits.
    events = []
    for t in trades.itertuples():
        events.append((t.trade_date, 1, t.side, (t.quantity * t.price, t.fees)))
    for a in db.get_actions(conn, ticker):
        events.append((a["ex_date"], 0, "ACTION", a["factor"]))
    for d in db.get_dividends(conn, ticker, include_ignored=False):
        events.append((d["ex_date"], 0, "DIVIDEND", d["amount"]))
    first = trades["trade_date"].min()
    events = sorted(e for e in events if e[0] >= first and (not as_of or e[0] <= as_of))

    units, paid, flows, shortfall = 0.0, 0.0, [], False
    for day, _, kind, x in events:
        when = date.fromisoformat(day)
        if kind == "ACTION":
            units *= x
        elif kind == "DIVIDEND":
            cash = units * x                      # held at the start of the ex-date
            if cash:
                paid += cash
                flows.append((when, cash))
        else:
            # The ETF version pays the same fees you did, so fees don't tilt the comparison.
            gross, fees = x
            price = _price_on(conn, ticker, day)
            if kind == "BUY":
                units += gross / price                 # same dollars into the market
                flows.append((when, -(gross + fees)))  # same dollars out of your pocket
            else:
                wanted = gross / price
                if wanted > units + 1e-9:
                    shortfall, wanted = True, units    # can't take out more than the ETF is worth
                units -= wanted
                flows.append((when, wanted * price - fees))

    end_price = _price_on(conn, ticker, as_of)
    value = units * end_price
    end_day = date.fromisoformat(as_of) if as_of else date.fromisoformat(db.get_latest_close(conn, ticker)[0])
    flows.append((end_day, value))
    return BenchmarkResult(flows, units, value, paid, shortfall)


def _price_on(conn, ticker, day):
    """The benchmark's close on a day, or the last close before it (for a holiday or missing day)."""
    latest = db.get_latest_close(conn, ticker, day)
    if latest is None:
        raise ValueError(f"No {ticker} price on or before {day}. Run python src/market.py first.")
    return latest[1]


# ---------- Both together ----------

def compare(conn, user_id, as_of=None):
    """Your XIRR and the benchmark's XIRR for the same cash flows."""
    flows, end, end_value = portfolio_flows(conn, user_id, as_of)
    mine = xirr(flows + [(end, end_value)]) if flows and end_value == end_value else float("nan")
    bench = benchmark(conn, user_id, as_of)
    return {
        "you": mine,
        "benchmark": xirr(bench.flows),
        "your_value": end_value,
        "benchmark_value": bench.value,
        "benchmark_dividends": bench.dividends,
        "shortfall": bench.shortfall,
        "end": end,
        "days": (end - min(d for d, _ in flows)).days if flows else 0,
    }


# ---------- Run directly ----------

def main():
    from importer import DEMO_EMAIL

    conn = db.get_connection()
    db.init_db(conn)
    user = db.get_user_by_email(conn, DEMO_EMAIL)
    if not user:
        print("No demo portfolio yet. Run: python src/importer.py data/demo_trades.csv")
        return 1
    c = compare(conn, user["id"])
    conn.close()

    print(f"Up to {c['end']}")
    if c["days"] < 365:
        print(f"  ! Only {c['days']} days of history: a yearly rate over a short time can look extreme.")
    print(f"  Your portfolio            {c['you']:+.2%} a year")
    print(f"  Same money in the STI ETF {c['benchmark']:+.2%} a year")
    diff = c["you"] - c["benchmark"]
    print(f"  You {'beat' if diff > 0 else 'trailed'} the market by {abs(diff):.2%} a year")
    print()
    print(f"  Your holdings now worth          ${c['your_value']:,.2f}")
    print(f"  The STI ETF version now worth    ${c['benchmark_value']:,.2f}"
          f"  (plus ${c['benchmark_dividends']:,.2f} of its dividends paid out)")
    if c["shortfall"]:
        print("  ! A sale took out more than the STI ETF version held, so the comparison is rough.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
