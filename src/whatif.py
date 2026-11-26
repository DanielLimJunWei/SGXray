"""The "what if" calculator (s12): "if I'd put $200 a month into the STI ETF since January 2015, what would I have now?"

It replays a monthly plan over real saved closing prices, with the same rules as SGXray's own monthly plans
(src/plans.py), which follow how Singapore banks' plans work:
- One buy a month, on the first trading day on or after the plan's day. A month with no trading within a week of
  that day is skipped, as banks do.
- The fee comes off first, then only whole shares are bought. The leftover cash isn't invested (banks refund it),
  so "money in" is what the shares and fee actually cost. A month where one share costs more than the amount
  after the fee buys nothing and costs nothing.
- Splits and bonus issues change the share count on their ex-date, before that day's buy.
- Dividends: every share held BEFORE an ex-date gets it (buying on the ex-date is too late), paid out as cash, not
  reinvested. That's how SGXray counts your real dividends, from the ex-date (the cash arrives a few weeks later).

Prices are as they really traded (see src/adjust.py), so the numbers match what a person really paid.

Nothing is saved: it's a calculation over prices SGXray already has. A stock whose saved prices start after the
chosen month gets its older history downloaded once (db.want_history), and keeps it.

    python src/whatif.py ES3.SI 200 2015-01      (needs that history saved already)
"""

import sys
from dataclasses import dataclass, field
from datetime import date

import db
import fmt
import plans
import sgtime
from adjust import shares_after
from performance import YEARLY_DAYS, xirr

EARLIEST = "2010-01"             # the earliest month you can start from
MIN_AMOUNT, MAX_AMOUNT = 10, 100_000
DEFAULT = {"ticker": "ES3.SI", "amount": 200, "start": "2015-01", "fee_rate": 0.3, "fee_min": 5}
# OCBC Blue Chip Investment Plan, from OCBC's own fees page (checked 26 Nov 2026): 0.3% of the amount or S$5 per
# counter, whichever is higher (0.88% flat if you're under 30, on up to S$500 a counter). Banks change their fees,
# so the form says to check your own.
BUY_DAY = 1
DOWNLOADS_PER_HOUR = 10     # older-history downloads per person or address: plenty for real use


@dataclass
class Result:
    ticker: str
    amount: float
    start_month: str
    fee_rate: float               # a fraction: 0.003 = 0.3%
    fee_min: float
    buys: list = field(default_factory=list)       # dicts: date, shares, price, fee, cost
    skipped: list = field(default_factory=list)    # (month, reason) for months that bought nothing
    dividends: list = field(default_factory=list)  # dicts: ex_date, shares, amount, total
    shares: int = 0               # held at the end, after every split or bonus issue
    end_date: str = None          # the latest saved close
    end_price: float = None
    money_in: float = 0.0
    fees: float = 0.0
    dividends_total: float = 0.0
    worth: float = 0.0
    profit: float = 0.0
    days: int = 0
    yearly: float = float("nan")  # XIRR, shown only from a year of history
    total_return: float = float("nan")    # profit / money in, shown under a year
    path: list = field(default_factory=list)       # (month-end date, money in so far, worth + dividends so far)


def months_between(start_month, last_month):
    return list(plans._months(start_month, last_month))


def simulate(conn, ticker, amount, start_month, fee_rate, fee_min, day=BUY_DAY):
    """Replays the plan. Returns a Result, or None if there's no saved price at all for the ticker."""
    end_date = db.get_latest_price_date(conn, ticker)
    if end_date is None:
        return None
    r = Result(ticker, amount, start_month, fee_rate, fee_min, end_date=end_date)
    r.end_price = db.get_prices(conn, ticker, start=end_date)[0]["close"]

    earliest = db.get_earliest_price_date(conn, ticker)
    for month in months_between(start_month, end_date[:7]):
        found = plans._buy_day(conn, ticker, month, day)
        if found is None:
            continue                                        # this month's buy day hasn't come yet
        if found == "skip":
            # Before the first close SGXray has (not listed yet, or Yahoo's history starts later), or a month
            # with no trading within a week of the buy day (a long suspension).
            r.skipped.append((month, "no-price" if f"{month}-{day:02d}" < earliest else "no-trading"))
            continue
        buy_date, price = found
        shares, f = plans.buy(amount, price, fee_rate, fee_min)
        if shares == 0:
            r.skipped.append((month, "too-dear"))
            continue
        cost = fmt.cents(shares * price + f)
        r.buys.append({"date": buy_date, "shares": shares, "price": price, "fee": f, "cost": cost})

    # One walk through the dates, exactly as portfolio._dividends_received: on each day, splits first, then that
    # day's buy; a dividend counts the shares held before its ex-date.
    events = sorted([(a["ex_date"], 0, "ACTION", a["factor"]) for a in db.get_actions(conn, ticker)]
                    + [(b["date"], 1, "BUY", b["shares"]) for b in r.buys], key=lambda e: (e[0], e[1]))
    first = r.buys[0]["date"] if r.buys else None
    shares, i = 0, 0
    for d in db.get_dividends(conn, ticker, include_ignored=False):
        day_ = d["ex_date"]
        if first is None or day_ <= first or day_ > end_date:
            continue
        while i < len(events) and events[i][0] < day_:
            shares = shares_after(shares, events[i][3]) if events[i][2] == "ACTION" else shares + events[i][3]
            i += 1
        if shares > 0:
            r.dividends.append({"ex_date": day_, "shares": shares, "amount": d["amount"],
                                "total": fmt.cents(shares * d["amount"])})
    while i < len(events) and events[i][0] <= end_date:
        shares = shares_after(shares, events[i][3]) if events[i][2] == "ACTION" else shares + events[i][3]
        i += 1
    r.shares = shares

    r.money_in = fmt.cents(sum(b["cost"] for b in r.buys))
    r.fees = fmt.cents(sum(b["fee"] for b in r.buys))
    r.dividends_total = fmt.cents(sum(d["total"] for d in r.dividends))
    r.worth = fmt.cents(r.shares * r.end_price)
    r.profit = fmt.cents(r.worth + r.dividends_total - r.money_in)
    if r.buys:
        r.days = (date.fromisoformat(end_date) - date.fromisoformat(first)).days
        flows = ([(date.fromisoformat(b["date"]), -b["cost"]) for b in r.buys]
                 + [(date.fromisoformat(d["ex_date"]), d["total"]) for d in r.dividends]
                 + [(date.fromisoformat(end_date), r.worth)])
        r.yearly = xirr(flows)
        r.total_return = r.profit / r.money_in if r.money_in else float("nan")
        r.path = _path(conn, r, events)
    return r


def _path(conn, r, events):
    """Month by month: (last close of the month, money in so far, worth + dividends so far), for the chart."""
    closes = {p["price_date"]: p["close"] for p in db.get_prices(conn, r.ticker, start=r.buys[0]["date"])}
    by_month = {}
    for d in sorted(closes):
        by_month[d[:7]] = d                                  # the month's last saved close
    points, shares, i, money, divs, di = [], 0, 0, 0.0, 0.0, 0
    for month in sorted(by_month):
        day_ = by_month[month]
        while i < len(events) and events[i][0] <= day_:
            shares = shares_after(shares, events[i][3]) if events[i][2] == "ACTION" else shares + events[i][3]
            i += 1
        money = sum(b["cost"] for b in r.buys if b["date"] <= day_)
        while di < len(r.dividends) and r.dividends[di]["ex_date"] <= day_:
            divs += r.dividends[di]["total"]
            di += 1
        points.append((day_, money, shares * closes[day_] + divs))
    return points


def _nice_step(top):
    """A round gridline step (1, 2 or 5 x a power of ten) giving about 3 to 5 lines up to `top`."""
    import math
    raw = top / 4
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    return next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)


def chart(r, w=800, h=260, left=70, right=16, top=14, bottom=34, max_years=8):
    """SVG drawing instructions for the chart: money in as steps, worth + dividends as a line, month by month.
    None with under two months to draw. The page draws it twice: wide for screens, and taller with fewer year labels
    for phones (a wide chart squeezed onto a phone is a thin strip with overlapping labels)."""
    pts = r.path
    if len(pts) < 2:
        return None
    peak = max(max(m, v) for _, m, v in pts)
    step = _nice_step(peak)
    ymax = step * -(-peak // step)                       # the gridline at or just above the peak
    pw, ph = w - left - right, h - top - bottom
    x = lambda i: round(left + i / (len(pts) - 1) * pw, 1)
    y = lambda v: round(top + ph - v / ymax * ph, 1)
    money = f"M{x(0)},{y(pts[0][1])}" + "".join(f"H{x(i)}V{y(m)}" for i, (_, m, _) in enumerate(pts) if i)
    worth = "M" + " L".join(f"{x(i)},{y(v)}" for i, (_, _, v) in enumerate(pts))
    grid = [(y(g), f"${g:,.0f}") for g in [step * k for k in range(int(ymax // step) + 1)]]
    years = []                                           # a label each January (fewer if many years)
    jans = [i for i, (d, _, _) in enumerate(pts) if d[5:7] == "01"]
    every = max(1, -(-len(jans) // max_years))
    for i in jans[::every]:
        years.append((x(i), pts[i][0][:4]))
    return {"w": w, "h": h, "left": left, "right": w - right, "bottom": top + ph, "money": money, "worth": worth,
            "grid": grid, "years": years, "end": (x(len(pts) - 1), y(pts[-1][2]))}


def explain(r):
    """The ⓘ boxes: "result" (the figures), "chart" and "buys" (the table of every month). Facts about the past,
    never a prediction or advice."""
    from explain import Explanation, _day
    first, last = date.fromisoformat(r.buys[0]["date"]), date.fromisoformat(r.end_date)
    n = len(r.buys)
    per = r.money_in / n
    fee_share = r.fees / r.money_in if r.money_in else 0.0
    lines = [
        f"This replays ${r.amount:,.0f} a month into {r.ticker} from {_day(first)} to {_day(last)}: {n} monthly "
        f"buy{'s' if n != 1 else ''}, each on the first trading day of the month at that day's real closing price, the "
        "way banks' monthly plans buy.",
        f"Money in is what the shares and fees really cost: ${r.money_in:,.2f}. It's a little under ${r.amount:,.0f} a "
        f"month (about ${per:,.2f} on average) because only whole shares are bought and the leftover cash isn't "
        "invested; banks give it back.",
        f"It's worth ${r.worth:,.2f} now ({r.shares:,} shares at ${r.end_price:g}, the close on {_day(last)}), and "
        f"paid ${r.dividends_total:,.2f} of dividends along the way, counted as cash, not reinvested.",
    ]
    if r.days >= YEARLY_DAYS and r.yearly == r.yearly:
        lines.append(f"Profit = worth + dividends - money in = ${r.profit:,.2f}. As a yearly rate that's "
                     f"{r.yearly:.2%} a year (XIRR, money-weighted): it allows for each month's money going in at a "
                     "different time, so later money, which had less time to grow, isn't counted as if it was there "
                     "from the start.")
    else:
        lines.append(f"Profit = worth + dividends - money in = ${r.profit:,.2f}, {r.total_return:.2%} of the money "
                     "in. It's shown as a total, not a yearly rate, because it's under a year.")
    watch = [
        f"Fees took ${r.fees:,.2f}, {fee_share:.2%} of the money in. With a minimum fee, small monthly amounts pay a "
        f"bigger share: S$5 on $100 is 5%, on $1,000 it's 0.5%.",
        "This is the past, replayed. The same plan from another month, or for the next ten years, can end up "
        "very differently.",
    ]
    if r.skipped:
        watch.append(f"{len(r.skipped)} month{'s' if len(r.skipped) != 1 else ''} bought nothing (listed in the table "
                     "of every buy, with the reason).")
    result = Explanation(lines, watch)
    chart = Explanation([
        "The flat steps are your money going in, month by month. The other line is what everything was worth at each "
        "month's last close, plus the dividends paid so far.",
        "When the line is above the steps the plan was ahead; below, it was sitting on a loss on that day. Buying "
        "the same amount every month gets more shares when the price is low and fewer when it's high.",
    ])
    buys = Explanation([
        "Every month the plan bought, so you can check the maths: the day, the closing price, whole shares, the fee "
        "and what it cost. A split or bonus issue changes the share count later, on its own day.",
        "A month with no buy says why: no price yet (before SGXray's prices for this stock start), no trading "
        "that week, or one share costing more than the month's money after the fee.",
    ])
    return {"result": result, "chart": chart, "buys": buys}


def from_args(conn, args):
    """The form's values (a GET query): (values, problems). Empty values get the defaults."""
    problems = []
    tickers = {i["ticker"] for i in db.get_instruments(conn)}
    ticker = str(args.get("ticker") or DEFAULT["ticker"]).strip()[:16]
    if ticker not in tickers:
        problems.append("Choose a stock, REIT or ETF from the list.")

    def number(name, label, lo, hi):
        raw = str(args.get(name, "")).replace(",", "").replace("$", "").replace("%", "").strip()[:12]
        if raw == "":
            return DEFAULT[name]
        try:
            v = float(raw)
        except ValueError:
            problems.append(f"{label} must be a number.")
            return None
        if not (v == v and lo <= v <= hi):
            problems.append(f"{label} must be between {lo:g} and {hi:,g}.")
            return None
        return v
    amount = number("amount", "The monthly amount", MIN_AMOUNT, MAX_AMOUNT)
    rate = number("fee_rate", "The fee (%)", 0, 5)
    minimum = number("fee_min", "The minimum fee", 0, 100)
    start = str(args.get("start") or DEFAULT["start"]).strip()[:7]
    this_month = sgtime.today().strftime("%Y-%m")
    try:
        y, m = map(int, start.split("-"))
        start = f"{y:04d}-{m:02d}"
        if not (1 <= m <= 12 and EARLIEST <= start <= this_month):
            raise ValueError
    except ValueError:
        problems.append(f"Choose a start month from {EARLIEST[5:]}/{EARLIEST[:4]} to this month.")
        start = None
    values = {"ticker": ticker, "amount": amount, "start": start, "fee_rate": rate, "fee_min": minimum}
    return values, problems


def needs_history(conn, ticker, start_month):
    """True if the saved prices for `ticker` start after the plan's first buy day, so older ones must be fetched."""
    earliest = db.get_earliest_price_date(conn, ticker)
    return earliest is None or earliest > f"{start_month}-{BUY_DAY:02d}"


def main(argv=None):
    from fmt import safe_console
    safe_console()
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 3:
        print(__doc__)
        return 1
    conn = db.get_connection()
    db.init_db(conn)
    r = simulate(conn, argv[0], float(argv[1]), argv[2], DEFAULT["fee_rate"] / 100, DEFAULT["fee_min"])
    if r is None:
        print("No prices saved for", argv[0])
        return 1
    print(f"{len(r.buys)} buys, {len(r.skipped)} months skipped, {r.shares} shares at ${r.end_price} on {r.end_date}")
    print(f"money in ${r.money_in:,.2f} (fees ${r.fees:,.2f}), dividends ${r.dividends_total:,.2f}, "
          f"worth ${r.worth:,.2f}, profit ${r.profit:,.2f}, yearly {r.yearly:.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
