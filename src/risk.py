"""Risk view (w305): your investments' biggest fall, and how bumpy the ride has been, next to the STI ETF.

Both use the same day-by-day growth as the time-weighted return (history._growth): money you add or take out
is removed, so a deposit never looks like a gain and a withdrawal never looks like a fall. Dividends count,
like in the time-weighted return.

- Biggest fall (drawdown): the deepest drop from a high point in that growth, how long it took, and when (or
  whether) it climbed back.
- How bumpy (volatility): the usual size of a day's move, turned into a yearly figure the standard way
  (daily standard deviation x the square root of 252 trading days). Needs at least 60 trading days.
"""

import math

import history

MIN_DAYS_FOR_BUMPINESS = 60
TRADING_DAYS = 252


def _fall(index):
    """The biggest drop from a high in a growth index: {"pct", "peak_day", "low_day", "back_day", "now_pct"}."""
    peak = index.cummax()
    draw = index / peak - 1
    low_day = draw.idxmin()
    pct = float(draw[low_day])
    if pct >= 0:
        return {"pct": 0.0, "peak_day": None, "low_day": None, "back_day": None, "now_pct": 0.0}
    peak_day = index.loc[:low_day].idxmax()
    after = index.loc[low_day:]
    back = after[after >= index[peak_day] - 1e-12]
    return {"pct": pct, "peak_day": peak_day.date(), "low_day": low_day.date(),
            "back_day": back.index[0].date() if len(back) else None, "now_pct": float(draw.iloc[-1])}


def _bumpiness(growth, held):
    """Yearly volatility from daily growth factors, on the days you held something. NaN if too few days."""
    r = (growth[held] - 1.0)
    if len(r) < MIN_DAYS_FOR_BUMPINESS:
        return float("nan")
    return float(r.std(ddof=1) * math.sqrt(TRADING_DAYS))


def risk(conn, user_id, h=None):
    """The risk view's numbers, or None if they can't be worked out (no history, or a price missing).
    {"you": {fall..., "vol"}, "sti": {fall..., "vol"}, "days": trading days held, "start", "end"}."""
    h = h if h is not None else history.value_history(conn, user_id)
    if h is None or h.empty:
        return None
    g = history._growth(conn, user_id, None, h)
    if g is None or g.empty:
        return None
    held = h["value"].shift(1).fillna(0.0) > 0               # days that started with something held
    if held.sum() < 2:
        return None
    first = held[held].index[0]
    g = g.loc[first:]
    held = held.loc[first:]
    out = {"days": int(held.sum()), "start": first.date(), "end": g.index[-1].date()}
    for who in ("you", "sti"):
        index = g[who].cumprod()
        out[who] = {**_fall(index), "vol": _bumpiness(g[who], held)}
    return out
