"""Plain-English explanations of SGXray's numbers: the "What does this mean?" box.

These are written by code from the numbers themselves, not by AI, so they're free, instant
and can never disagree with the table. (The AI box is only for "why did the price move?",
which needs news.)

Each explanation has two parts:
- lines: what the numbers mean, using a real row as a worked example;
- watch_out: common beginner traps and warning signs, shown only when YOUR numbers make
  them relevant (plus the odd general one). The web app shows these under a "Watch out" heading.

    python src/explain.py 2024-03        explain the March 2024 row of the monthly table
    python src/explain.py holdings       explain the holdings table
    python src/explain.py vs-sti         explain you vs the STI ETF, and per stock
    python src/explain.py yields         explain the dividend yields table
    python src/explain.py forecast       explain the 12-month dividend forecast
"""

import sys
from dataclasses import dataclass, field

import pandas as pd

import db
from history import value_history
from portfolio import dividends_received, positions, summary, trades_frame

HIGH_YIELD = 0.07           # a yield above 7% gets a "could be a yield trap" warning
BIG_MONTH_MOVE = 0.05       # a monthly profit swing above 5% of the value gets a "one month is noisy" note
ONE_STOCK_SHARE = 0.5       # one stock giving over half the expected income gets a concentration warning


@dataclass
class Explanation:
    lines: list = field(default_factory=list)       # what it means
    watch_out: list = field(default_factory=list)   # traps and warning signs

    @property
    def text(self):
        return " ".join(self.lines + self.watch_out)


def money(x):
    return f"${abs(x):,.2f}"


def up_down(x):
    """'$131.00 up' / '$5.00 down' / 'exactly even'."""
    if round(x, 2) == 0:
        return "exactly even"
    return f"{money(x)} {'up' if x > 0 else 'down'}"


def _day(d):
    return f"{d.day} {d:%B %Y}"                     # 28 March 2024 (no leading zero)


def _reason(from_prices, from_dividends):
    """Why profit changed, in words: price moves and dividends, and how they combined."""
    p, d = round(from_prices, 2), round(from_dividends, 2)
    rose = f"prices rose by {money(p)}"
    fell = f"prices fell by {money(p)}"
    if p and d:
        if p > 0:
            return f"{rose}, and you received {money(d)} in dividends"
        if p + d > 0:
            return f"{fell}, but {money(d)} of dividends more than made up for it"
        return f"{fell}, partly made up for by {money(d)} of dividends"
    if d:
        return f"you received {money(d)} in dividends (prices ended about where they were)"
    return rose if p > 0 else fell


def _trade_sentences(trades, month):
    lines = []
    for t in trades[trades["trade_date"].str[:7] == month].itertuples():
        when = _day(pd.Timestamp(t.trade_date))
        if t.side == "BUY":
            lines.append(f"On {when} you bought {t.quantity:,} {t.ticker} for "
                         f"{money(t.quantity * t.price + t.fees)} (including {money(t.fees)} in fees).")
        else:
            lines.append(f"On {when} you sold {t.quantity:,} {t.ticker} and got back "
                         f"{money(t.quantity * t.price - t.fees)} after fees.")
    return lines


def explain_month(conn, user_id, month, history=None):
    """Explains one row of the monthly table. month is 'YYYY-MM'."""
    h = history if history is not None else value_history(conn, user_id)
    if h.empty:
        return Explanation(["There's no history yet: add trades and update prices first."])
    rows = h[h.index.to_period("M") == pd.Period(month)]
    if rows.empty:
        return Explanation([f"There's no snapshot for {month}: it's before your first trade or after the newest price."])
    day, r = rows.index[-1], rows.iloc[-1]
    earlier = h[h.index < rows.index[0]]
    before = earlier.iloc[-1] if not earlier.empty else None

    trades = trades_frame(conn, user_id)
    paid = dividends_received(conn, user_id)
    month_paid = paid[paid["ex_date"].str[:7] == month] if not paid.empty else paid

    out = []
    # 1. What you did this month.
    did = _trade_sentences(trades, month)
    if did:
        out.append(" ".join(did))
    if not month_paid.empty:
        parts = [f"{money(d.total)} from {d.ticker} ({d.shares:,} shares x ${d.amount:g})" for d in month_paid.itertuples()]
        out.append("You earned dividends this month: " + "; ".join(parts) + ".")
    if not did and month_paid.empty:
        out.append("You didn't buy or sell anything this month, and no dividends were due.")

    # 2. The snapshot.
    if r.value != r.value:                                 # NaN: a held stock has no price yet
        out.append(f"The value on {_day(day)} can't be worked out yet: a stock you hold has no saved price.")
        return Explanation(out)
    out.append(f"Money in: you had put {money(r.net_invested)} of your own money into the portfolio by then "
               f"(what you paid for buys, minus what you got back from sales).")
    out.append(f"Value: at the close on {_day(day)}, your shares were worth {money(r.value)}.")
    div_note = f", plus {money(r.dividends)} of dividends received so far" if r.dividends else ""
    out.append(f"Profit: {money(r.value)} worth - {money(r.net_invested)} put in{div_note} "
               f"= {up_down(r.profit)}.")

    # 3. What changed since the last snapshot, and why.
    if before is not None:
        change = r.profit - before.profit
        new_divs = r.dividends - before.dividends
        from_prices = change - new_divs
        if round(change, 2) == 0:
            out.append("Your profit didn't change since last month.")
        else:
            out.append(f"Since last month your profit {'grew' if change > 0 else 'shrank'} by {money(change)}: "
                       f"{_reason(from_prices, new_divs)}.")
        if did:
            out.append("Buying or selling doesn't change your profit by itself: it moves Money in and "
                       "Value by the same amount. Only price moves and dividends change profit.")

    # 4. Against the STI ETF.
    gap = r.profit - r.sti_profit
    out.append(f"STI profit: the same money put into the STI ETF on the same days would have been "
               f"{up_down(r.sti_profit)}. So you were {money(gap)} {'ahead of' if gap >= 0 else 'behind'} the market.")

    # 5. Watch out: only what these numbers make relevant.
    watch = []
    month_buys = trades[(trades["trade_date"].str[:7] == month) & (trades["side"] == "BUY")]
    if not month_buys.empty:
        spent = (month_buys["quantity"] * month_buys["price"]).sum()
        fees = month_buys["fees"].sum()
        if spent and fees / spent >= 0.002:
            watch.append(f"Fees: you paid {money(fees)} in fees on {money(spent)} of buys ({fees / spent:.2%}). "
                         f"Every buy starts slightly in the red because of fees, and many small buys "
                         f"cost more in fees than one bigger buy.")
    s = summary(positions(conn, user_id, as_of=day.strftime("%Y-%m-%d")))
    if r.profit > 0 and s["unrealised"] > 0.5 * r.profit:
        part = "All" if s["unrealised"] >= r.profit - 0.005 else f"{money(s['unrealised'])}"
        watch.append(f"{part} of your {money(r.profit)} profit is unrealised: it's only on paper "
                     f"until you sell, and a market drop can shrink it.")
    if before is not None and r.value and abs(r.profit - before.profit) > BIG_MONTH_MOVE * r.value:
        watch.append("One month's move tells you very little. Prices swing month to month; "
                     "judge your investments over years, not weeks.")
    if gap < 0:
        watch.append("You're behind the STI ETF here. If that keeps happening over years, simply "
                     "buying the STI ETF may suit you better than picking stocks.")
    return Explanation(out, watch)


def explain_value_chart(conn, user_id, history=None):
    """Explains the X-ray chart: one line (worth + dividends) split into money in, price gains and dividends."""
    h = history if history is not None else value_history(conn, user_id)
    h = h.dropna(subset=["value"]) if not h.empty else h
    if h.empty:
        return Explanation(["There's no history to chart yet: add trades and update prices first."])
    day, r = h.index[-1], h.iloc[-1]
    gains = r.value - r.net_invested
    total, sti_total = r.value + r.dividends, r.sti_value + r.sti_dividends

    out = [
        f"The solid light-blue line along the top is your TOTAL: everything your investing has given you so far, "
        f"what your shares are worth plus the dividends paid to you. On {_day(day)} that was {money(total)}. "
        f"An ordinary chart shows only this line. SGXray X-rays the space under it into three layers, so you can "
        f"see where that total came from.",
        f"Your own money (the plain dark-blue area at the bottom): {money(r.net_invested)}, what you paid for buys "
        f"minus what you got back from sales. It's the bottom layer because it was yours to begin with. It isn't profit.",
        f"Price gains (blue dots): {up_down(gains)}, what price changes have added on top of your money "
        f"(or taken away, if prices fell).",
        f"Dividends (amber dots): {money(r.dividends)} paid to you in cash so far.",
        f"The dashed line is the market: the same money, put into the STI ETF on the same days, would be "
        f"{money(sti_total)} now, dividends included. Where your light-blue total line is above the dashed line, "
        f"your picks were doing better than the market; below it, worse.",
        "Point at (or tap) any month to see its numbers, or open \"Show as a table\" for every month.",
    ]
    watch = ["A line going up isn't all profit. Much of the climb in a chart like this is your own money going "
             "in, not growth. That's why SGXray splits the line: only the dotted layers are what you earned."]
    if gains > 0:
        watch.append(f"The {money(gains)} of price gains is on paper until you sell. A market drop can shrink it; "
                     f"the dividends layer is cash you already have.")
    elif gains < 0:
        watch.append(f"Prices are below what you paid: the price-gains layer is {up_down(gains)}. That's a loss "
                     f"on paper, and it only becomes real if you sell at these prices.")
    if total < sti_total:
        watch.append(f"Your light-blue total line is below the dashed STI ETF line: {money(sti_total - total)} behind the "
                     f"market. If that lasts for years, buying the STI ETF would have been simpler.")
    if (day - h.index[0]).days < 365:
        watch.append("Less than a year of history. A short stretch of chart mostly shows luck, not skill.")
    return Explanation(out, watch)


def explain_yields(conn, user_id, as_of=None):
    """Explains the dividend yields table, one stock at a time, using its own numbers."""
    from income import portfolio_yield, yields

    y = yields(conn, user_id, as_of)
    if y.empty:
        return Explanation(["You don't hold any stocks right now, so there are no yields to show."])

    out = ["This table shows how much each stock paid in dividends over the last 12 months, "
           "compared with two prices: today's price, and what you paid."]
    watch, bought_cheap = [], []
    for r in y.itertuples():
        if r.per_share_12m == 0:
            out.append(f"{r.ticker} paid no dividends in the last 12 months, so both yields are 0%.")
            continue
        if r.price != r.price:
            out.append(f"{r.ticker} has no saved price yet, so its yield can't be worked out. "
                       f"Its dividends were ${r.per_share_12m:g} a share over the last 12 months.")
            continue
        # "divided by" in words: plain for beginners, and a Windows terminal can't show the ÷ sign.
        out.append(
            f"{r.ticker}: each share paid ${r.per_share_12m:g} in dividends over the last 12 months. "
            f"Yield: ${r.per_share_12m:g} divided by today's price ${r.price:.2f} = {r.div_yield:.2%}, which is what "
            f"someone buying today would earn a year in dividends if payouts stay the same. "
            f"On cost: ${r.per_share_12m:g} divided by your average cost ${r.avg_cost:.2f} = {r.yield_on_cost:.2%}, "
            f"which is what the dividends pay on the money you put in."
        )
        if r.yield_on_cost > r.div_yield * 1.05:
            bought_cheap.append(f"{r.ticker} ({r.yield_on_cost:.2%} on cost, {r.div_yield:.2%} for a new buyer)")
        elif r.yield_on_cost < r.div_yield * 0.95:
            out.append(f"  Your 'On cost' is lower because you paid more than today's price for {r.ticker}.")
        if r.div_yield > HIGH_YIELD:
            watch.append(f"{r.ticker}'s {r.div_yield:.2%} yield is unusually high. That can be a warning sign "
                         f"(a 'yield trap'): sometimes the price has fallen because investors expect the "
                         f"dividend to be cut. Check why before buying for the yield.")

    if bought_cheap:
        watch.insert(0, f"'On cost' is higher than 'Yield' for {', '.join(bought_cheap)}, because you bought "
                        f"for less than they cost now. That shows you bought well, not that they're good buys "
                        f"today: a new buyer only gets the 'Yield'. Compare stocks using 'Yield', not 'On cost'.")
    total = portfolio_yield(y, positions(conn, user_id, as_of))
    if total == total:
        out.append(f"Whole portfolio: a year's dividends on everything you hold, ${y['income_12m'].sum():,.2f}, "
                   f"divided by what it's all worth today = {total:.2%} a year.")
    else:
        out.append("The whole portfolio's yield can't be worked out until every stock you hold has a price.")
    watch.append("Yields look back at the last 12 months. A company can raise, cut or stop its dividend, "
                 "so they're a guide, not a promise.")
    reits = {i["ticker"] for i in db.get_instruments(conn) if i["type"] == "reit"} & set(y["ticker"])
    if reits:
        watch.append(f"REITs ({', '.join(sorted(reits))}) sometimes pay extra one-off distributions, for example "
                     f"before raising money, which can make one year's yield look higher than usual.")
    return Explanation(out, watch)


def explain_forecast(conn, user_id, as_of=None):
    """Sentences explaining the 12-month dividend forecast, with its biggest months and its limits."""
    from income import forecast

    f = forecast(conn, user_id, as_of)
    if f.empty:
        return Explanation(["No dividends are expected: either you hold nothing, or nothing you hold "
                            "paid a dividend in the last 12 months."])

    by_month = f.groupby(f["expected"].dt.to_period("M"))["total"].sum()
    best = by_month.idxmax()
    out = [
        "This is an estimate of the dividends you'll receive over the next 12 months. "
        "It takes every dividend each stock paid in the last 12 months and assumes it comes again "
        "about a year later, on the number of shares you hold now.",
        f"For example: {f.iloc[0].ticker} paid ${f.iloc[0].amount:g} a share on "
        f"{_day(pd.Timestamp(f.iloc[0].based_on))}. You hold {f.iloc[0].shares:,} shares, so around "
        f"{_day(f.iloc[0].expected)} you can expect about {f.iloc[0].shares:,} x ${f.iloc[0].amount:g} = {money(f.iloc[0].total)}.",
        f"In total, about {money(f['total'].sum())} over {len(by_month)} months with payouts. "
        f"The biggest month is {best:%B %Y}, at about {money(by_month[best])}.",
        "You get a dividend only if you own the shares before the ex-date. The cash usually reaches "
        "your bank a few weeks after that.",
    ]
    watch = [
        "It's only an estimate: companies can raise, cut or skip a dividend; one-off payouts (like a "
        "REIT's advanced distribution before it raises money) may not happen again; and the dates are "
        "guesses until the company announces the real ex-date. Don't count on this money before it arrives.",
    ]
    by_stock = f.groupby("ticker")["total"].sum()
    top = by_stock.idxmax()
    share = by_stock[top] / by_stock.sum()
    if len(by_stock) > 1 and share > ONE_STOCK_SHARE:
        watch.append(f"{share:.0%} of your expected dividends ({money(by_stock[top])}) come from one stock, {top}. "
                     f"If it cuts its dividend, your income drops a lot. Spreading across more stocks "
                     f"makes your income steadier.")
    watch.append("Buying just before an ex-date to 'catch' a dividend doesn't make free money: "
                 "the price usually drops by about the dividend on the ex-date.")
    return Explanation(out, watch)


def explain_holdings(conn, user_id, as_of=None):
    """Explains the holdings table from portfolio.py: what you own, what it cost, what it's worth."""
    df = positions(conn, user_id, as_of)
    held = df[df["shares"] > 0]
    if held.empty:
        return Explanation(["You don't hold any stocks right now."])
    s = summary(df)

    out = ["Each row is one stock you own."]
    total_value = held["value"].sum()
    if total_value == total_value and total_value:
        top = held.loc[held["value"].idxmax()]
        out.append(f"'Weight' is each stock's share of what the whole portfolio is worth. {top['ticker']} is "
                   f"{top['value'] / total_value:.0%} of yours: {money(top['value'])} of {money(total_value)}.")
    r = held.sort_values("value", ascending=False).iloc[0]
    if r["value"] == r["value"]:
        out.append(
            f"For example, {r['ticker']}: you own {int(r['shares']):,} shares. They cost you {money(r['cost'])} in "
            f"total, fees included, which is {money(r['avg_cost'])} a share on average ('Avg cost'). At today's "
            f"price of ${r['price']:.2f} they're worth {money(r['value'])}, so you're {up_down(r['unrealised'])} on "
            f"them ({r['unrealised_pct']:+.1%}). That's 'Unrealised': profit you'd make if you sold today."
        )
    if s["value"] == s["value"]:
        out.append(f"Altogether: {money(s['unrealised'])} unrealised {'profit' if s['unrealised'] >= 0 else 'loss'} "
                   f"on what you still hold, {money(s['realised'])} realised from shares you've sold, and "
                   f"{money(s['dividends'])} of dividends. Total profit: {up_down(s['total_profit'])}.")

    watch = []
    if s["value"] == s["value"] and s["total_profit"] > 0 and s["unrealised"] > 0.5 * s["total_profit"]:
        watch.append(f"{money(s['unrealised'])} of your {money(s['total_profit'])} total profit is unrealised. "
                     f"It isn't money in your bank until you sell, and a market drop can shrink it or "
                     f"turn it into a loss. Only realised profit and dividends are locked in.")
    total_value = held["value"].sum()
    if len(held) > 1 and total_value == total_value and total_value:
        top = held.loc[held["value"].idxmax()]
        share = top["value"] / total_value
        if share > ONE_STOCK_SHARE:
            watch.append(f"{share:.0%} of your portfolio's value is in one stock, {top['ticker']}. If that one "
                         f"company has a bad year, your whole portfolio feels it. Spreading across more "
                         f"stocks, or an ETF, lowers that risk.")
    for ticker in held["ticker"]:
        actions = db.get_actions(conn, ticker)
        if actions:
            a = actions[-1]
            watch.append(f"{ticker} had a {'bonus issue' if a['factor'] > 1 else 'consolidation'} on "
                         f"{_day(pd.Timestamp(a['ex_date']))} (x{a['factor']:g}). Bonus shares aren't free money: "
                         f"the price drops to match, so your holding is worth about the same on the day. "
                         f"Your average cost per share goes down because the same cost is spread over more shares.")
    if s["missing_prices"]:
        watch.append(f"No price yet for {', '.join(s['missing_prices'])}, so the totals can't be worked out.")
    if s["stale_prices"]:
        watch.append(f"The prices for {', '.join(s['stale_prices'])} are older than the rest, so their value may be out of date.")
    return Explanation(out, watch)


TIMING_GAP = 0.02           # XIRR and TWR more than 2 points apart a year...
TIMING_SHARE = 0.10         # ...and more than 10% of the return apart = timing mattered


def _timing_mattered(xirr_year, twr_year):
    """How far apart counts as 'timing mattered'. 2 points means a lot at 5% a year, but little at
    35% a year, so it's the larger of 2 points and 10% of the return."""
    return abs(xirr_year - twr_year) > max(TIMING_GAP, TIMING_SHARE * abs(twr_year))


def _two_returns_section(xirr_year, twr_year):
    """'Why SGXray shows two returns', ending with what the gap between them means for THIS user."""
    lines = [
        "Why SGXray shows two returns:",
        "  - TWR is fair for judging your picks. It's how funds and the STI report their returns, so it's the like-for-like comparison.",
        "  - XIRR is what actually happened to your money. It's the number that matters for your bank account.",
        "  - If they're very different, timing played a big part: good timing (adding money before prices rose) "
        "or bad timing (adding a lot just before a fall).",
    ]
    gap = xirr_year - twr_year
    if not _timing_mattered(xirr_year, twr_year):
        lines.append(f"  - Yours: XIRR {xirr_year:+.2%} and TWR {twr_year:+.2%} are close, so your timing didn't "
                     f"help or hurt much. Your result came mostly from what you picked.")
    elif gap > 0:
        lines.append(f"  - Yours: XIRR {xirr_year:+.2%} is higher than TWR {twr_year:+.2%}, so your timing helped: "
                     f"you tended to add money before prices rose.")
    else:
        lines.append(f"  - Yours: XIRR {xirr_year:+.2%} is lower than TWR {twr_year:+.2%}, so your timing cost you: "
                     f"you tended to add money before prices fell.")
    return lines


def _span(days):
    """'2 years and 7 months' / '5 months' / '20 days', for how long you've been investing."""
    years, months = divmod(round(days / 30.44), 12)
    if years:
        return f"{years} year{'s' if years != 1 else ''}" + (f" and {months} month{'s' if months != 1 else ''}" if months else "")
    return f"{months} month{'s' if months != 1 else ''}" if months else f"{days} days"


def explain_worth(conn, user_id, change):
    """Explains 'Worth now' and the day's change under it."""
    s = summary(positions(conn, user_id))
    if s["value"] != s["value"]:                       # a held stock has no price yet
        return Explanation([f"'Worth now' can't be worked out yet: there's no price for {', '.join(s['missing_prices'])}."])
    out = [f"'Worth now' is what everything you hold would sell for at the latest closing prices: {money(s['value'])}."]
    watch = ["SGXray uses end-of-day closing prices, not live ones: they change once a day, after the market closes."]
    if change:
        out.append(f"The line under it is the day's change: from the close on {_day(pd.Timestamp(change['previous']))} "
                   f"to the close on {_day(pd.Timestamp(change['date']))}, your holdings went {up_down(change['change'])} "
                   f"({change['pct']:+.2%}). Buying or selling that day doesn't count: only price moves and dividends do.")
        if change["movers"]:
            m = change["movers"][0]
            out.append(f"The biggest mover was {m['ticker']}: {up_down(m['change'])} ({m['pct']:+.2%}).")
        watch.insert(0, "One day's move tells you almost nothing. Prices go up and down every day; judge your "
                        "investments over months and years.")
        if abs(change["pct"]) > 0.03:
            watch.append(f"A {abs(change['pct']):.1%} move in a day is big. It's worth checking the news for the "
                         f"stock that moved most, but don't rush to buy or sell because of one day.")
    return Explanation(out, watch)


def explain_total_return(conn, user_id):
    """Explains 'Total profit' and the simple total return under it."""
    from insights import simple_return
    s = summary(positions(conn, user_id))
    r = simple_return(conn, user_id)
    if s["total_profit"] != s["total_profit"]:
        return Explanation([f"'Total profit' can't be worked out yet: there's no price for {', '.join(s['missing_prices'])}."])
    out = [f"'Total profit' is everything you've made: {money(s['unrealised'])} unrealised (on paper, on what you "
           f"still hold) + {money(s['realised'])} realised (locked in by selling) + {money(s['dividends'])} of "
           f"dividends = {up_down(s['total_profit'])}."]
    watch = []
    if r["pct"] == r["pct"]:
        out.append(f"The line under it is your simple total return: that profit divided by all the money you've put "
                   f"in ({money(r['put_in'])} of buys, fees included) = {r['pct']:+.1%}, over {_span(r['days'])}.")
        watch.append(f"This is a total, not a yearly rate: {r['pct']:+.1%} over {_span(r['days'])} is much less "
                     f"per year. For a fair yearly number, see 'You vs the STI a year'.")
        if s["unrealised"] > 0.5 * s["total_profit"] > 0:
            watch.append("Most of this profit is unrealised: it's only real once you sell, and a market drop can shrink it.")
    return Explanation(out, watch)


def explain_periods(rows):
    """Explains the period returns row (1M, 3M, YTD, 1Y, All)."""
    shown = [r for r in rows if r["available"]]
    if not shown:
        return Explanation(["There isn't enough history for any period yet."])
    out = ["Each figure is how much your investments grew over that stretch, next to the STI ETF over the same "
           "stretch. YTD means 'year to date': since the last close of last year.",
           "They're time-weighted, like 'Your picks alone': money you added in the middle doesn't count as "
           "growth, so a big deposit can't make a month look good."]
    best = max(shown, key=lambda r: r["you"] - r["sti"])
    out.append(f"For example, over {best['words']} you made {best['you']:+.1%} and the STI ETF {best['sti']:+.1%}.")
    watch = ["These are totals for each stretch, not yearly rates, and short stretches are mostly noise: a bad "
             "month says little about a good investment."]
    missing = [r["key"] for r in rows if not r["available"]]
    if missing:
        watch.append(f"{', '.join(missing)} will appear once you have that much history.")
    return Explanation(out, watch)


def explain_sold(rows):
    """Explains the 'Sold' table: stocks you've sold completely."""
    if not rows:
        return Explanation(["You haven't sold all your shares of any stock yet."])
    r = rows[0]
    out = ["These are stocks you've sold completely. They're no longer in your holdings, but what they made "
           "still counts in your total profit.",
           f"For example, {r['ticker']}: you put in {money(r['put_in'])} and got back {money(r['got_back'])} after "
           f"fees, a realised {up_down(r['realised'])}, plus {money(r['dividends'])} of dividends while you held it."]
    watch = ["Selling locks in the result. A winner you sold can keep rising without you, and a loser you sold can "
             "recover: neither means the sale was wrong, but it's worth asking 'would I buy it again today?'"]
    if any(x["realised"] < 0 for x in rows):
        watch.append("Some of these were sold at a loss. Many beginners sell after a fall and miss the recovery; "
                     "only sell when your reason for owning it has changed.")
    return Explanation(out, watch)


def explain_two_returns(conn, user_id, as_of=None):
    """Explains the 'You vs the STI, a year' figure: the money-weighted (XIRR) and time-weighted (TWR) returns."""
    from history import time_weighted
    from performance import compare

    c = compare(conn, user_id, as_of)
    t = time_weighted(conn, user_id, as_of)
    if c["too_short"] or c["you"] != c["you"] or t["you_year"] != t["you_year"]:
        return Explanation(["A yearly rate needs at least 30 days of history and a price for everything you hold."])
    out = [
        f"The big number, {c['you']:+.2%} a year, is your money-weighted return (XIRR): what actually happened to "
        f"YOUR money, counting when each dollar went in or came out. The same dollars in the STI ETF, on the same "
        f"days, made {c['benchmark']:+.2%} a year.",
        f"\"Your picks alone\", {t['you_year']:+.2%} a year, is the time-weighted return (TWR): how the investments "
        f"themselves did, as if you'd put one dollar in at the start and never added or taken out any. On the same "
        f"measure the STI ETF made {t['sti_year']:+.2%} a year.",
    ] + _two_returns_section(c["you"], t["you_year"])
    watch = []
    if c["you"] < t["you_year"] and _timing_mattered(c["you"], t["you_year"]):
        watch.append("Your timing cost you: your money earned less than your picks did, which usually means more "
                     "money went in just before prices fell. Adding money bit by bit on a schedule makes timing matter less.")
    if t["you_year"] < t["sti_year"]:
        watch.append("Your picks alone did worse than the STI ETF. Over several years, that would mean simply buying "
                     "the STI ETF was the easier, cheaper choice.")
    if c["days"] < 365:
        watch.append("Less than a year of history: a yearly rate from a short stretch mostly shows luck.")
    watch.append("Past returns don't predict future ones, whichever way they're measured.")
    return Explanation(out, watch)


def explain_income_by_year(conn, user_id, as_of=None):
    """Explains the dividend income by year chart, using the biggest full year as the example."""
    from income import by_year

    rows = by_year(conn, user_id, as_of)
    if not rows or not any(r["total"] for r in rows):
        return Explanation(["No dividends received yet, so there's nothing to show by year."])

    out = ["Each bar is the dividends paid to you in one calendar year, counted by ex-date: the cut-off you "
           "had to own the shares by."]
    full = [r for r in rows if not r["part"]]
    best = max(full or rows, key=lambda r: r["total"])
    parts = ", ".join(f"{t} {money(v)}" for t, v in best["by_stock"].items())
    out.append(f"For example, {best['year']}: {money(best['total'])} in all ({parts}).")
    for r in rows:
        if r["part"] == "first":
            out.append(f"{r['year']} is a part-year: you started in {r['from_month']}, so it's lower than a full year.")
        elif r["part"] == "so far":
            out.append(f"{r['year']} isn't over yet: {money(r['total'])} so far, to {_day(pd.Timestamp(r['to_date']))}.")
    out.append(f"Altogether: {money(sum(r['total'] for r in rows))} of dividends since you started.")

    watch = []
    if len(full) >= 2 and full[-1]["total"] > full[0]["total"]:
        watch.append(f"Your income grew from {money(full[0]['total'])} in {full[0]['year']} to {money(full[-1]['total'])} "
                     f"in {full[-1]['year']}. Some of that is from buying more shares, some from companies paying more "
                     f"per share. Only the second is the companies doing better.")
    if any(r["part"] for r in rows):
        watch.append("Don't compare a part-year bar with a full year: a short year always looks smaller.")
    top_year = rows[-1] if rows[-1]["total"] else best
    if len(top_year["by_stock"]) > 1:
        ticker, value = next(iter(top_year["by_stock"].items()))
        share = value / top_year["total"]
        if share > ONE_STOCK_SHARE:
            watch.append(f"{share:.0%} of your {top_year['year']} dividends came from one stock, {ticker}. "
                         f"If it cuts its dividend, your income drops a lot.")
    reits = {i["ticker"] for i in db.get_instruments(conn) if i["type"] == "reit"}
    if any(t in reits for r in rows for t in r["by_stock"]):
        watch.append("A REIT's one-off extra payout can make one year look unusually high. It may not repeat.")
    return Explanation(out, watch)


def explain_stock_chart(conn, user_id, ticker, history=None, as_of=None):
    """Explains one stock's price chart: the line, your buys and sells, dividends and your average cost."""
    from stocks import last_avg, stock_history

    h = history if history is not None else stock_history(conn, user_id, ticker, as_of)
    if h is None or not h["prices"]:
        return Explanation([f"There are no saved prices for {ticker} yet."])
    last_day, last_price = h["prices"][-1]
    out = [f"The line is {ticker}'s closing price each trading day since you first bought it."]
    buys = [t for t in h["trades"] if t["side"] == "BUY"]
    sells = [t for t in h["trades"] if t["side"] == "SELL"]
    if buys:
        b = buys[0]
        out.append(f"Each triangle pointing up is a buy. Your first: {b['qty']:,} shares at ${b['price']:.2f} on "
                   f"{_day(pd.Timestamp(b['date']))}." + (f" You bought {len(buys)} times in all." if len(buys) > 1 else ""))
    if sells:
        s = sells[-1]
        out.append(f"Triangles pointing down are sales. Your latest: {s['qty']:,} shares at ${s['price']:.2f} on "
                   f"{_day(pd.Timestamp(s['date']))}.")
    if h["dividends"]:
        total = sum(d["total"] for d in h["dividends"])
        out.append(f"Each dot is a dividend ex-date: {len(h['dividends'])} so far, {money(total)} paid to you in all.")
    avg = last_avg(h)
    watch = []
    if avg:
        gap = last_price / avg - 1
        out.append(f"The dashed line is your average cost: what each share cost you, fees included. It only moves when "
                   f"you buy, sell, or get bonus shares. It's ${avg:.2f} now; the price on {_day(pd.Timestamp(last_day))} "
                   f"was ${last_price:.2f}, {abs(gap):.1%} {'above' if gap >= 0 else 'below'} it.")
        if gap < 0:
            watch.append(f"The price is below your average cost, so this stock is at a loss on paper ({gap:.1%}). "
                         f"It only becomes a real loss if you sell at this price.")
    for a in h["actions"]:
        watch.append(f"The price drops on {_day(pd.Timestamp(a['date']))} because of a "
                     f"{'bonus issue' if a['factor'] > 1 else 'consolidation'} (x{a['factor']:g}), not a fall in value: "
                     f"you got more shares, so your average cost dropped with it.")
    for t in h["trades"]:
        earlier = [s for s in h["avg_steps"] if s["date"] < t["date"] and s["avg"]]
        previous = earlier[-1]["avg"] if earlier else None
        if t["side"] == "BUY" and previous and t["price"] < previous * 0.95:
            watch.append(f"On {_day(pd.Timestamp(t['date']))} you bought below your average cost ('averaging down'). "
                         f"It lowers your average, but only helps if the price recovers: it also puts more money in one stock.")
            break
    from insights import week52
    w = week52(conn, ticker, last_day)
    if w:
        where = ("near the top of" if w["position"] > 0.8 else "near the bottom of" if w["position"] < 0.2
                 else "in the middle of")
        out.append(f"52-week range: over the last year it closed as high as ${w['high']:.2f} "
                   f"({_day(pd.Timestamp(w['high_date']))}) and as low as ${w['low']:.2f} "
                   f"({_day(pd.Timestamp(w['low_date']))}). Today's ${w['now']:.2f} is {where} that range.")
        if w["position"] < 0.2:
            watch.append("Near its 52-week low doesn't mean cheap: a price can keep falling, often for a reason. "
                         "Check why it fell before buying more.")
        elif w["position"] > 0.8:
            watch.append("Near its 52-week high doesn't mean it must fall, or that it will keep rising. "
                         "The range is history, not a forecast.")
        if w["action_inside"]:
            watch.append("A bonus issue or split happened in the last 52 weeks. Prices are real, so they dropped "
                         "that day without any loss in value: the range looks wider than it really was.")
    watch.append("The line shows the price only. Dividends aren't in it, so the line alone undersells what a "
                 "dividend stock has paid you.")
    return Explanation(out, watch)


def explain_performance(conn, user_id, as_of=None):
    """Explains 'you vs the STI ETF', for the whole portfolio and per stock."""
    from performance import compare, per_stock

    c = compare(conn, user_id, as_of)
    if c["end"] is None:
        return Explanation(["You haven't made any trades yet."])
    if c["too_short"]:
        return Explanation(
            [f"You have only {c['days']} days of history, which is too short for a yearly rate. "
             f"So far you're {up_down(c['your_profit'])}; the same money in the STI ETF would be "
             f"{up_down(c['benchmark_profit'])}."],
            ["A few days or weeks of results say almost nothing about how good your picks are. "
             "Check back after a few months."])
    if c["you"] != c["you"]:
        return Explanation(["A stock you hold has no saved price yet, so your return can't be worked out. "
                            "Run the price update first."])
    if c["benchmark"] != c["benchmark"]:
        return Explanation(
            [f"Your portfolio grew at {c['you']:+.2%} a year (money-weighted, XIRR).",
             f"The STI comparison can't be given a yearly rate here. Your picks did so much better than the "
             f"index that, when you sold, you took out more money than the same dollars in the STI ETF would "
             f"have been worth. In dollars: you're {up_down(c['your_profit'])}; the STI ETF version would be "
             f"{up_down(c['benchmark_profit'])}."],
            ["One or two big winners can produce results like this. Past results don't predict the future."])
    gap = c["you"] - c["benchmark"]
    out = [
        f"Your portfolio grew at {c['you']:+.2%} a year. That's the money-weighted return (XIRR): it counts "
        f"when each dollar went in or came out, so money you added recently isn't treated as if it had "
        f"been invested from the start.",
        f"SGXray then replayed exactly the same dollars, on the same days, with the same fees, into the STI "
        f"ETF. That would have grown at {c['benchmark']:+.2%} a year.",
        f"So you {'beat' if gap > 0 else 'trailed'} the market by {abs(gap):.2%} a year. Because the timing and "
        f"amounts are the same on both sides, the difference comes only from what you chose to buy.",
    ]
    # The second measure (TWR) and "why two returns" are explained once, under "You vs the STI, a year"
    # at the top of the page (explain_two_returns), so here it's just a pointer.
    out.append("For your picks alone (the time-weighted return) and why SGXray shows two returns, see "
               "\"What does this mean?\" under \"You vs the STI a year\" at the top of the page.")
    timing_watch = None
    stocks = per_stock(conn, user_id, as_of)
    if stocks["shortfall"].any():
        out.append("Note: for " + ", ".join(stocks.loc[stocks["shortfall"], "ticker"]) + ", a sale took out "
                   "more than the STI version of that stock held, so the per-stock rows won't add up exactly "
                   "to the whole-portfolio difference.")
    for r in stocks.itertuples():
        if r.verdict == "about level":
            out.append(f"{r.ticker}: about the same as the STI ETF ({money(r.difference)} apart).")
        else:
            verb = "helped you" if r.verdict == "helped" else "held you back"
            out.append(f"{r.ticker} {verb}: it made {up_down(r.your_profit)}, while the same money in "
                       f"the STI ETF would have made {up_down(r.sti_profit)}, a difference of "
                       f"{'+' if r.difference >= 0 else '-'}{money(r.difference)}.")

    watch = [timing_watch] if timing_watch else []
    if c["shortfall"]:
        watch.append("At one point you took out more money than the STI ETF version was worth (your picks "
                     "did far better than the index), so the STI comparison is rough from then on.")
    if c["stale_benchmark"]:
        watch.append("The STI ETF's newest saved price is older than yours, so the comparison may be out of "
                     "date. Run the price update.")
    if c["days"] < 365:
        watch.append(f"Only {c['days']} days of history. Turning a short period into a yearly rate assumes the "
                     f"same luck repeats all year: +10% in 2 months works out to about +77% a year (1.10 x 1.10 "
                     f"x ... six times), which rarely happens.")
    helped = stocks[stocks["difference"] > 0]
    total_gain = helped["difference"].sum()
    if gap > 0 and not helped.empty and total_gain and helped["difference"].max() / total_gain > 0.75:
        star = helped.loc[helped["difference"].idxmax(), "ticker"]
        watch.append(f"Skill or luck? Most of your lead comes from one stock, {star}. One great pick can make "
                     f"anyone look like a genius; beating the market across many stocks over many years is "
                     f"much harder.")
    watch.append("Past results don't predict the future. A stock that beat the market for two years can trail it for the next two.")
    if gap < 0:
        watch.append("You're behind the STI ETF. If that holds over several years, simply buying the STI ETF "
                     "would have been easier and cheaper than picking stocks.")
    else:
        watch.append("The STI ETF gives you the market's average: you can't beat the market with it, but you "
                     "won't badly trail it either. Picking stocks is only worth it if you beat it over years.")
    return Explanation(out, watch)


def main(argv):
    from fmt import safe_console
    safe_console()                     # never crash printing characters the terminal can't show
    usage = ("Usage:\n  python src/explain.py YYYY-MM     the monthly table, e.g. 2024-03\n"
             "  python src/explain.py holdings    the holdings table\n"
             "  python src/explain.py vs-sti      you vs the STI ETF, and per stock\n"
             "  python src/explain.py yields      the dividend yields table\n"
             "  python src/explain.py forecast    the 12-month dividend forecast")
    if len(argv) != 2:
        print(usage)
        return 1
    from importer import DEMO_EMAIL

    conn = db.get_connection()
    db.init_db(conn)
    user = db.get_user_by_email(conn, DEMO_EMAIL)
    if not user:
        print("No demo portfolio yet. Run: python src/importer.py data/demo_trades.csv")
        return 1
    try:
        if argv[1] == "holdings":
            e = explain_holdings(conn, user["id"])
        elif argv[1] == "vs-sti":
            e = explain_performance(conn, user["id"])
        elif argv[1] == "yields":
            e = explain_yields(conn, user["id"])
        elif argv[1] == "forecast":
            e = explain_forecast(conn, user["id"])
        elif len(argv[1]) == 7:
            e = explain_month(conn, user["id"], argv[1])
        else:
            print(usage)
            return 1
    except ValueError:
        print(f"'{argv[1]}' isn't a month. Use YYYY-MM, e.g. 2024-03")
        return 1
    finally:
        conn.close()
    print("What does this mean?")
    for line in e.lines:
        print("   " + line.lstrip() if line.startswith("  -") else " - " + line)   # sub-points indent
    if e.watch_out:
        print()
        print("Watch out")
        for line in e.watch_out:
            print(" !", line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
