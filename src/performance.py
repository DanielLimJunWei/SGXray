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

import math
import sys
from dataclasses import dataclass
from datetime import date

import pandas as pd

import db
from market import BENCHMARK
from portfolio import dividends_received, positions, summary, trades_frame

DAYS_PER_YEAR = 365.0      # Excel's XIRR uses 365-day years too
MIN_DAYS = 30              # under this much history, no yearly rate is shown
STALE_DAYS = 5             # an STI ETF price this much older than your end date is flagged


# ---------- XIRR ----------

def _npv(rate, flows):
    """Net present value: what all the flows are worth on the first date, at a yearly rate.

    Written as exp(-years x log(1 + rate)) rather than amount / (1 + rate) ** years: same maths,
    but the power version underflows to 0 for long spans at very low rates and crashed with a
    divide-by-zero (found in the second audit). The exponent is capped so it can't overflow.
    """
    start = flows[0][0]
    log_growth = math.log1p(rate)
    return sum(
        amount * math.exp(max(-700.0, min(700.0, -((day - start).days / DAYS_PER_YEAR) * log_growth)))
        for day, amount in flows
    )


def xirr(flows, low=-0.9999, high=100.0, tolerance=1e-10):
    """The yearly rate that makes the NPV of (date, amount) flows zero. Money in is negative,
    money out (and what you hold at the end) is positive.

    Solved by BISECTION: NPV goes down as the rate goes up, so we keep halving the range that
    contains zero. Slower than Excel's method (Newton's) but it can't shoot off and fail.
    Returns NaN if there's no answer (e.g. money only ever went in, or only came out), and
    -1.0 (-100%) if money went in and nothing at all came back.
    """
    if flows and any(a < 0 for _, a in flows) and all(a <= 0 for _, a in flows) and any(a == 0 for _, a in flows):
        return -1.0                             # everything lost: the end value is exactly 0
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

@dataclass
class _Context:
    """Everything the calculations need, worked out once. Before the second audit, the
    per-stock comparison recalculated all of this for every stock (slow for big portfolios)."""
    trades: pd.DataFrame
    positions: pd.DataFrame
    dividends: pd.DataFrame
    end: date


def _context(conn, user_id, as_of=None):
    trades = trades_frame(conn, user_id, as_of)
    if trades.empty:
        return None
    pos = positions(conn, user_id, as_of)
    newest = summary(pos)["prices_as_of"]
    end = date.fromisoformat(as_of or newest or trades["trade_date"].max())
    return _Context(trades, pos, dividends_received(conn, user_id, as_of), end)


def portfolio_flows(conn, user_id, as_of=None, only=None, ctx=None):
    """Your money in and out as (date, amount) pairs, plus your holdings' value at the end.
    With only='D05.SI', just that one stock's money.

    BUY = money in (negative), SELL = money out (positive), dividend = money out on its
    ex-date (the cash really arrives a few weeks later; close enough for a yearly rate).
    Returns (flows, end_date, end_value); end_value is NaN if a price is missing.
    """
    ctx = ctx or _context(conn, user_id, as_of)
    if ctx is None:
        return [], None, 0.0
    trades, pos, paid = ctx.trades, ctx.positions, ctx.dividends
    if only:
        trades = trades[trades["ticker"] == only]
        pos = pos[pos["ticker"] == only]
        paid = paid[paid["ticker"] == only]
    flows = []
    for t in trades.itertuples():
        day = date.fromisoformat(t.trade_date)
        if t.side == "BUY":
            flows.append((day, -(t.quantity * t.price + t.fees)))
        else:
            flows.append((day, t.quantity * t.price - t.fees))
    for d in paid.itertuples():
        flows.append((date.fromisoformat(d.ex_date), d.total))
    return flows, ctx.end, summary(pos)["value"]


# ---------- The same money in the STI ETF ----------

@dataclass
class BenchmarkResult:
    flows: list              # the benchmark's own (date, amount) flows, ending with its value
    units: float             # ES3 units held at the end
    value: float             # their value at the end
    dividends: float         # ES3 dividends paid out along the way
    shortfall: bool = False  # True if a sale took out more than the ES3 holding was worth
    units_history: list = None   # (date, units held after that day's events), for charts
    dividend_history: list = None  # (date, ES3 dividend cash paid), for charts
    price_date: str = None   # the date of the ES3 price used for the end value
    stale: bool = False      # True if that price is more than STALE_DAYS older than the end date


def benchmark(conn, user_id, as_of=None, ticker=BENCHMARK, only=None, end=None, trades=None):
    """Replays your buys and sells, in dollars, into the benchmark ETF.
    With only='D05.SI', just the dollars that went into and out of that one stock.

    It's valued on `end`, the same date as your portfolio, so both sides cover exactly the
    same period. (Before the second audit it used ES3's own newest price date; if ES3's
    prices stopped updating, the two sides covered different periods.)

    Units can be fractions here: it's a what-if, and whole lots would make the comparison
    depend on rounding rather than on what you picked.
    """
    if trades is None:
        trades = trades_frame(conn, user_id, as_of)
    if only and not trades.empty:
        trades = trades[trades["ticker"] == only]
    if trades.empty:
        return BenchmarkResult([], 0.0, 0.0, 0.0)
    if end is None:
        end = date.fromisoformat(as_of or _close_on(conn, ticker, None)[0])
    last_day = end.isoformat()

    # Every dated event. On the same day: the dividend first (bonus shares don't get a
    # dividend with the same ex-date), then the split or bonus, then the trades in their own order.
    events = []
    for d in db.get_dividends(conn, ticker, include_ignored=False):
        events.append((d["ex_date"], 0, "DIVIDEND", d["amount"]))
    for a in db.get_actions(conn, ticker):
        events.append((a["ex_date"], 1, "ACTION", a["factor"]))
    for t in trades.itertuples():
        events.append((t.trade_date, 2, t.side, (t.quantity * t.price, t.fees)))
    first = trades["trade_date"].min()
    events = [e for e in events if first <= e[0] <= last_day]
    events.sort(key=lambda e: (e[0], e[1]))     # by date and kind only; stable, so trade order is kept

    units, paid, flows, shortfall = 0.0, 0.0, [], False
    units_history, dividend_history = [], []
    for day, _, kind, x in events:
        when = date.fromisoformat(day)
        if kind == "ACTION":
            units *= x
        elif kind == "DIVIDEND":
            cash = units * x                      # held at the start of the ex-date
            if cash:
                paid += cash
                flows.append((when, cash))
                dividend_history.append((when, cash))
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
        units_history.append((when, units))

    price_date, end_price = _close_on(conn, ticker, last_day)
    value = units * end_price
    flows.append((end, value))
    stale = (end - date.fromisoformat(price_date)).days > STALE_DAYS
    return BenchmarkResult(flows, units, value, paid, shortfall, units_history, dividend_history, price_date, stale)


def _close_on(conn, ticker, day):
    """(date, close) of the benchmark on a day, or the last close before it (holiday or missing day)."""
    latest = db.get_latest_close(conn, ticker, day)
    if latest is None:
        raise ValueError(f"No {ticker} price on or before {day}. Run python src/market.py first.")
    return latest


def _price_on(conn, ticker, day):
    return _close_on(conn, ticker, day)[1]


# ---------- Both together ----------

def compare(conn, user_id, as_of=None):
    """Your XIRR and the benchmark's XIRR for the same cash flows, over the same dates.

    Under MIN_DAYS of history there's no yearly rate (too_short): turning a week into a
    "per year" figure is meaningless (+10% in a week would show as +14,000% a year).
    """
    ctx = _context(conn, user_id, as_of)
    if ctx is None:
        return {"you": float("nan"), "benchmark": float("nan"), "your_value": 0.0, "benchmark_value": 0.0,
                "benchmark_dividends": 0.0, "shortfall": False, "end": None, "days": 0,
                "too_short": True, "stale_benchmark": False, "your_profit": 0.0, "benchmark_profit": 0.0}
    flows, end, end_value = portfolio_flows(conn, user_id, as_of, ctx=ctx)
    bench = benchmark(conn, user_id, as_of, end=end, trades=ctx.trades)
    days = (end - min(d for d, _ in flows)).days
    too_short = days < MIN_DAYS
    known = end_value == end_value
    mine = xirr(flows + [(end, end_value)]) if known and not too_short else float("nan")
    return {
        "you": mine,
        "benchmark": float("nan") if too_short else xirr(bench.flows),
        "your_value": end_value,
        "benchmark_value": bench.value,
        "benchmark_dividends": bench.dividends,
        "your_profit": sum(a for _, a in flows) + end_value,
        "benchmark_profit": sum(a for _, a in bench.flows),
        "shortfall": bench.shortfall,
        "end": end,
        "days": days,
        "too_short": too_short,
        "stale_benchmark": bench.stale,
    }


def per_stock(conn, user_id, as_of=None):
    """Which stock helped or held back your result: each one against the STI ETF.

    For each stock, its own money in and out is replayed into the STI ETF, exactly like the
    whole-portfolio comparison. Two ways to read it:
    - the yearly rates (XIRR) say how good each pick was, whatever its size;
    - the DOLLAR difference says how much it actually moved your result, because a big
      holding that's slightly better matters more than a tiny one that doubled.
    Profit = everything that came out + what's still held - everything that went in.
    """
    ctx = _context(conn, user_id, as_of)
    rows = []
    for ticker in sorted(ctx.trades["ticker"].unique()) if ctx else []:
        flows, end, value = portfolio_flows(conn, user_id, as_of, only=ticker, ctx=ctx)
        mine = flows + [(end, value)]
        bench = benchmark(conn, user_id, as_of, only=ticker, end=end, trades=ctx.trades)
        your_profit = sum(a for _, a in mine)
        sti_profit = sum(a for _, a in bench.flows)
        put_in = -sum(a for _, a in mine if a < 0)
        difference = your_profit - sti_profit
        too_short = (end - min(d for d, _ in flows)).days < MIN_DAYS
        rows.append({
            "ticker": ticker,
            "you": xirr(mine) if value == value and not too_short else float("nan"),
            "sti": float("nan") if too_short else xirr(bench.flows),
            "your_profit": your_profit,
            "sti_profit": sti_profit,
            "difference": difference,
            "verdict": _verdict(difference, put_in),
        })
    df = pd.DataFrame(rows, columns=["ticker", "you", "sti", "your_profit", "sti_profit", "difference", "verdict"])
    return df.sort_values("difference", ascending=False, ignore_index=True)


LEVEL_SHARE = 0.005     # within 0.5% of the money put in counts as "about level"


def _verdict(difference, put_in):
    """The STI version buys at each day's closing price, while you paid a price during the day,
    so even buying the STI ETF itself can be a few dollars apart. Tiny gaps aren't a lesson."""
    if put_in and abs(difference) < LEVEL_SHARE * put_in:
        return "about level"
    return "helped" if difference > 0 else "held back"


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
    stocks = per_stock(conn, user["id"])
    conn.close()

    if c["end"] is None:
        print("No trades yet.")
        return 0
    print(f"Up to {c['end']}")
    if c["too_short"]:
        print(f"  Only {c['days']} days of history: too short for a yearly rate.")
        print(f"  Profit so far: you ${c['your_profit']:,.2f}, same money in the STI ETF ${c['benchmark_profit']:,.2f}")
        return 0
    if c["days"] < 365:
        print(f"  ! Only {c['days']} days of history: a yearly rate over a short time can look extreme.")
    if c["stale_benchmark"]:
        print("  ! The STI ETF's newest price is older than yours: run python src/market.py.")
    print("  Money-weighted (XIRR): what you earned, including when you added money")
    print(f"    Your portfolio            {c['you']:+.2%} a year")
    print(f"    Same money in the STI ETF {c['benchmark']:+.2%} a year")
    diff = c["you"] - c["benchmark"]
    print(f"    You {'beat' if diff > 0 else 'trailed'} the market by {abs(diff):.2%} a year")
    from history import time_weighted         # here: history imports this file
    conn = db.get_connection()
    t = time_weighted(conn, user["id"])
    conn.close()
    print("  Time-weighted (TWR): how your picks did, ignoring when you added money")
    print(f"    Your portfolio            {t['you_year']:+.2%} a year ({t['you_total']:+.2%} in total)")
    print(f"    STI ETF                   {t['sti_year']:+.2%} a year ({t['sti_total']:+.2%} in total)")
    print()
    print(f"  Your holdings now worth          ${c['your_value']:,.2f}")
    print(f"  The STI ETF version now worth    ${c['benchmark_value']:,.2f}"
          f"  (plus ${c['benchmark_dividends']:,.2f} of its dividends paid out)")
    if c["shortfall"]:
        print("  ! A sale took out more than the STI ETF version held, so the comparison is rough.")

    print()
    print("Which stocks helped or held you back (each against the same money in the STI ETF)")
    print(f"  {'Ticker':<8} {'You':>9} {'STI ETF':>9} {'Your profit':>12} {'STI profit':>11} {'Difference':>11}")
    for r in stocks.itertuples():
        print(f"  {r.ticker:<8} {r.you:>+9.1%} {r.sti:>+9.1%} {r.your_profit:>12,.2f} {r.sti_profit:>11,.2f} "
              f"{r.difference:>+11,.2f}  {r.verdict}")
    total = stocks["difference"].sum()
    print(f"  Together: {'+' if total >= 0 else '-'}${abs(total):,.2f} versus putting the same money in the STI ETF")
    return 0


if __name__ == "__main__":
    sys.exit(main())
