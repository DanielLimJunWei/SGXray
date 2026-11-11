"""The practice portfolio (w320): pretend trades at real SGX prices, with no real money.

What makes it practice and not a toy:
- A pretend trade happens at the latest closing price, dated that day. You can't choose a date or a
  price, so there's no buying with hindsight.
- You start with $10,000 of pretend cash and can't spend more than you have. Sales and dividends go back
  into the cash.
- Every trade pays a fee: a typical one by default, or your own broker's rate and minimum.

The trades belong to the account's hidden "practice twin" (db.practice_user), so every calculation on the
portfolio pages works on them exactly as on real trades, and real and practice trades never mix.
"""

import db
import trades as trade_rules
from portfolio import positions, summary

START_CASH = 10_000.0
TYPICAL_RATE = 0.001          # 0.1% of the trade ...
TYPICAL_MIN = 10.0            # ... with a $10 minimum: a common Singapore broker price
SGX_CLEARING = 0.000325       # SGX clearing fee, 0.0325%
SGX_ACCESS = 0.000075         # SGX trading access fee, 0.0075%
GST = 0.09
MAX_SHARES = 1_000_000


def fee_settings(twin):
    """(rate, minimum, is_typical) for this practice portfolio."""
    if twin["fee_rate"] is None or twin["fee_min"] is None:
        return TYPICAL_RATE, TYPICAL_MIN, True
    return float(twin["fee_rate"]), float(twin["fee_min"]), False


def fee(amount, rate=TYPICAL_RATE, minimum=TYPICAL_MIN):
    """What one trade of `amount` dollars costs, in parts: {"commission", "sgx", "gst", "total"}.
    Commission is the broker's rate with its minimum; SGX adds its two fees; GST is 9% of both."""
    commission = max(amount * rate, minimum)
    sgx = amount * (SGX_CLEARING + SGX_ACCESS)
    gst = GST * (commission + sgx)
    return {"commission": round(commission, 2), "sgx": round(sgx, 2), "gst": round(gst, 2),
            "total": round(commission + sgx + gst, 2)}


def cash(conn, twin_id):
    """Pretend cash left: $10,000, minus what buys cost, plus what sales brought in, plus dividends."""
    money = START_CASH
    for t in db.get_trades(conn, twin_id):
        amount = t["quantity"] * t["price"]
        money += -(amount + t["fees"]) if t["side"] == "BUY" else amount - t["fees"]
    df = positions(conn, twin_id)
    if df is not None and not df.empty:
        money += float(summary(df)["dividends"])
    return round(money, 2)


def quote(conn, ticker, shares, rate, minimum):
    """What a trade would be right now: the latest close, its date, the amount and the fee. None if the
    stock has no saved price yet (then it can't be practised until the next price update)."""
    last = db.latest_close(conn, ticker)
    if last is None:
        return None
    day, price = last
    amount = shares * price
    return {"day": day, "price": price, "amount": amount, "fee": fee(amount, rate, minimum)}


def place(conn, twin, form, download=None):
    """Checks and saves one practice trade from the form. Only the stock, side, number of shares and the
    optional note come from the person: the price and date are always the latest close. A stock with no
    saved prices yet gets them first through `download(conn, tickers)` (the same downloader real trades
    use), so every stock in the list can be practised. Returns (trade_id, problems)."""
    ticker = str(form.get("ticker", "")).strip()[:16]
    side = str(form.get("side", "")).strip().upper()[:4]
    raw = str(form.get("quantity", "")).replace(",", "").strip()[:12]
    note = trade_rules.clean_note(form.get("note", ""))
    problems = []
    known = {i["ticker"] for i in db.get_instruments(conn)}
    if ticker not in known:
        problems.append("Choose a stock, REIT or ETF from the list.")
    if side not in ("BUY", "SELL"):
        problems.append("Choose bought or sold.")
    if not raw.isdigit() or not 1 <= int(raw) <= MAX_SHARES:
        problems.append(f"Shares must be a whole number from 1 to {MAX_SHARES:,}.")
    if len(note) > trade_rules.NOTE_MAX:
        problems.append(f"Your note is longer than {trade_rules.NOTE_MAX} characters. Shorten it a little.")
    if problems:
        return None, problems
    shares = int(raw)
    rate, minimum, _ = fee_settings(twin)
    q = quote(conn, ticker, shares, rate, minimum)
    if q is None and download is not None:
        from market import BENCHMARK
        needed = [tk for tk in (ticker, BENCHMARK) if db.latest_close(conn, tk) is None]
        download(conn, needed)                     # Yahoo Finance only, for listed stocks only
        q = quote(conn, ticker, shares, rate, minimum)
    if q is None:
        return None, ["That stock has no closing price saved yet, so it can't be practised today. "
                      "Its price comes with the next price update."]
    if side == "BUY" and q["amount"] + q["fee"]["total"] > cash(conn, twin["id"]) + 0.005:
        return None, [f"That would cost ${q['amount'] + q['fee']['total']:,.2f} with fees, and you have "
                      f"${cash(conn, twin['id']):,.2f} of pretend cash."]
    # The same checks as real trades (e.g. you can't sell more than you hold), with the latest close filled in.
    values = {"ticker": ticker, "date": q["day"], "side": side, "quantity": str(shares),
              "price": f"{q['price']}", "fees": f"{q['fee']['total']:.2f}", "note": note}
    trade, problems = trade_rules.check(conn, twin["id"], values)
    if problems:
        return None, problems
    tid = db.add_trade(conn, twin["id"], trade["ticker"], trade["trade_date"], trade["side"], trade["quantity"],
                       trade["price"], trade["fees"], trade["note"])
    return tid, []


def fee_problem(rate_text, min_text):
    """Your broker's fee from the form: (rate, minimum, problem). The rate is typed as a percentage."""
    try:
        rate = float(str(rate_text).replace("%", "").strip()[:8]) / 100
        minimum = float(str(min_text).replace("$", "").replace("S", "").strip()[:8])
    except ValueError:
        return None, None, "Type the rate as a percentage (like 0.08) and the minimum in dollars (like 10)."
    if not 0 <= rate <= 0.02:
        return None, None, "The rate must be between 0% and 2%."
    if not 0 <= minimum <= 100:
        return None, None, "The minimum must be between $0 and $100."
    return rate, minimum, None
