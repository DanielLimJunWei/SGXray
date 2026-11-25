"""Adding, changing and deleting trades on the website.

Every check is the importer's own (importer.check_fields for each field, then the "can't sell more
than you hold" check over all your trades), so a trade typed into the form and a trade in a CSV
file follow exactly the same rules. Nothing is saved unless every check passes.
"""

import re
from datetime import date

import db
from importer import _check_sells, check_fields

FIELDS = ("ticker", "date", "side", "quantity", "price", "fees")
MAX_FIELD_LENGTH = 32        # longer than any real value; anything past it is cut off before checking
MAX_TRADES = 5000            # per person. A real beginner portfolio has tens to hundreds.
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


NOTE_MAX = 280               # "Why I bought": about a tweet. Enough for a reason, short enough to reread.
CONTROL = re.compile(r"[\x00-\x1f\x7f]+")   # line breaks, tabs and invisible control characters


def clean_note(text):
    """Your "why I bought / sold" as one tidy line: control characters and line breaks become spaces,
    runs of spaces become one. It's only ever shown as escaped text, never as HTML."""
    text = CONTROL.sub(" ", str(text)[: NOTE_MAX * 4])     # cap the work on a huge paste before tidying
    return " ".join(text.split())


def form_values(form):
    """The trade's six fields from a submitted form, as short text, plus the optional note."""
    values = {f: str(form.get(f, "")).strip()[:MAX_FIELD_LENGTH] for f in FIELDS}
    values["note"] = clean_note(form.get("note", ""))
    return values


def trade_values(t):
    """A saved trade as form text, to fill in the edit form."""
    return {"ticker": t["ticker"], "date": t["trade_date"], "side": t["side"], "quantity": str(t["quantity"]),
            "price": f"{t['price']:g}", "fees": f"{t['fees']:.2f}" if t["fees"] else "", "note": t["note"] or ""}


def _sentence(text):
    """'sells 5 on 2025-06-02' -> 'Sells 5 on 2 Jun 2025.': a capital, a full stop, and dates as people write them."""
    text = ISO_DATE.sub(lambda m: _nice_date(m.group(0)), text)
    text = text[0].upper() + text[1:]
    return text if text.endswith(".") else text + "."


def _nice_date(iso):
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso                       # not a real date (that's the error being reported): leave it as typed
    return f"{d.day} {d:%b %Y}"


def _actions(conn, tickers):
    """Every split and bonus issue for these tickers: they change how many shares you hold."""
    return [dict(a, ticker=tk) for tk in sorted(tickers) for a in db.get_actions(conn, tk)]


def check(conn, user_id, values, today=None, replacing=None):
    """Checks a trade from the form. replacing is the id of the trade being edited.

    Returns (trade, problems): trade is None if anything is wrong.
    """
    today = today or date.today()
    known = {i["ticker"] for i in db.get_instruments(conn)}
    trade, problems = check_fields(values, known, today)
    note = values.get("note", "")
    if len(note) > NOTE_MAX:
        problems = [*problems, f"Your note is longer than {NOTE_MAX} characters. Shorten it a little."]
    if problems:
        return None, [_sentence(p) for p in problems]
    trade["note"] = note or None

    others = [dict(t) for t in db.get_trades(conn, user_id) if t["id"] != replacing]
    if replacing is not None:
        trade["id"] = replacing              # an edit keeps its place among that day's trades (see _check_sells)
    if replacing is None and len(others) >= MAX_TRADES:
        return None, [f"You've reached the limit of {MAX_TRADES:,} trades."]
    tickers = {t["ticker"] for t in others} | {trade["ticker"]}
    problems = _check_sells(others, [trade], _actions(conn, tickers), form=True)
    if problems:
        return None, [_sentence(p) for p in problems]
    return trade, []


def check_delete(conn, user_id, trade_id):
    """Deleting a buy can leave a later sale with too few shares. Returns the problems, if any."""
    others = [dict(t) for t in db.get_trades(conn, user_id) if t["id"] != trade_id]
    tickers = {t["ticker"] for t in others}
    return [_sentence(p) for p in _check_sells(others, [], _actions(conn, tickers), form=True)]


# ---------- "Add a stock I already own" ----------
# For beginners without their old contract notes: shares, average cost and roughly when. Saved as ONE buy at the
# average cost (fees counted in it), dated the 15th of that month, or the latest weekday before it. Marked
# "approximate", so the pages can say returns and the STI comparison are estimates until the real trades are in.

MONTH = re.compile(r"^\d{4}-\d{2}$")
MAX_SHARES = 10_000_000
MAX_AVG_COST = 100_000


def existing_values(form, today=None):
    """The form's fields as trade values for check(), or problems. Returns (values, problems)."""
    from datetime import timedelta
    today = today or date.today()
    ticker = str(form.get("ticker", "")).strip()[:MAX_FIELD_LENGTH]
    shares = str(form.get("quantity", "")).replace(",", "").strip()[:MAX_FIELD_LENGTH]
    cost = str(form.get("avg_cost", "")).replace("$", "").replace(",", "").strip()[:MAX_FIELD_LENGTH]
    month = str(form.get("month", "")).strip()[:7]
    problems = []
    if not ticker:
        problems.append("Choose the stock, REIT or ETF.")
    if not shares.isdigit() or not 1 <= int(shares) <= MAX_SHARES:
        problems.append("Shares must be a whole number, like 100.")
    try:
        avg = float(cost)
        if not 0 < avg <= MAX_AVG_COST:
            raise ValueError
    except ValueError:
        problems.append("Average cost is the price you paid per share on average, like 35.20.")
    day = None
    if not MONTH.match(month):
        problems.append("Choose roughly when you bought it: a month and year.")
    else:
        try:
            day = date(int(month[:4]), int(month[5:]), 15)
        except ValueError:
            problems.append("Choose roughly when you bought it: a month and year.")
    if day is not None:
        if day.replace(day=1) > today:
            problems.append("That month hasn't happened yet.")
        elif day.year < 1990:
            problems.append("Choose a month from 1990 on.")
        else:
            day = min(day, today)
            while day.weekday() >= 5:                       # SGX is closed at weekends
                day -= timedelta(days=1)
    if problems:
        return None, problems
    values = {"ticker": ticker, "date": day.isoformat(), "side": "BUY", "quantity": shares,
              "price": f"{avg:g}", "fees": "0", "note": clean_note(form.get("note", ""))}
    return values, []


# ---------- A price that doesn't look like that day's close ----------

PRICE_CHECK = 0.25          # 25% away from SGX's close that day: likely a typo or a price from another stock


def price_check(conn, trade):
    """The day's close when the trade's price is far from it (a likely typo), else None. Skipped for an
    approximate trade (its price is an average) and when a bonus issue or split came after (old closes can then
    be on a different footing)."""
    if trade.get("approx"):
        return None
    close = db.get_close(conn, trade["ticker"], trade["trade_date"])
    if close is None or abs(trade["price"] / close - 1) <= PRICE_CHECK:
        return None
    if any(a["ex_date"] > trade["trade_date"] for a in db.get_actions(conn, trade["ticker"])):
        return None
    return close


# ---------- Prices for a new stock or an earlier date ----------

def needs_market_data(conn, ticker, trade_date):
    """The tickers whose prices must be downloaded before this trade can be shown: a stock with no
    prices yet, or a date earlier than the saved prices go back (for the stock, and for the STI ETF
    that the portfolio is compared with)."""
    from market import BENCHMARK
    needed = []
    for tk in (ticker, BENCHMARK):
        earliest = db.get_earliest_price_date(conn, tk)
        if earliest is None or trade_date < earliest:
            needed.append(tk)
    return needed


def download_market_data(conn, tickers):
    """Downloads splits, then prices, then dividends for these tickers (the same order as market.py,
    because prices and dividends are corrected with the split factors). Only tickers already in the
    starter list reach here, and only Yahoo Finance is called, so a user can't make SGXray fetch any
    other address. Returns True if everything downloaded."""
    import market
    results = (market.update_actions(conn, tickers, pause=0)
               + market.update_prices(conn, tickers, pause=0)
               + market.update_dividends(conn, tickers, pause=0))
    return not any(r.error for r in results)
