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


def form_values(form):
    """The trade's six fields from a submitted form, as short text."""
    return {f: str(form.get(f, "")).strip()[:MAX_FIELD_LENGTH] for f in FIELDS}


def trade_values(t):
    """A saved trade as form text, to fill in the edit form."""
    return {"ticker": t["ticker"], "date": t["trade_date"], "side": t["side"], "quantity": str(t["quantity"]),
            "price": f"{t['price']:g}", "fees": f"{t['fees']:.2f}" if t["fees"] else ""}


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
    if problems:
        return None, [_sentence(p) for p in problems]

    others = [dict(t) for t in db.get_trades(conn, user_id) if t["id"] != replacing]
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
