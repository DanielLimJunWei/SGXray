"""Adding any SGX stock, REIT or ETF, looked up on Yahoo Finance (w309).

The starter list (instruments.py) has 10 well-known names. Anyone else's stock is typed in by its
SGX code (C6L for Singapore Airlines), checked here, looked up on Yahoo, and added to the list
for everyone, since a stock's name and type are the same whoever holds it.

Safety: only a code shaped like an SGX code is ever sent anywhere, and only to Yahoo through
yfinance, so nobody can make SGXray fetch an address of their choosing (SSRF). What Yahoo sends
back is checked too: it must be listed on SGX ("SES" in Yahoo's words) and be a share or an ETF.
"""

import re

CODE = re.compile(r"^[A-Z0-9]{1,6}$")       # SGX codes: D05, C38U, ES3, Z74, 5E2, ...
MAX_NAME_LENGTH = 120
LOOKUPS_PER_HOUR = 20                      # per person: plenty for real use, too few to hammer Yahoo


def normalise(text):
    """'c6l', ' C6L.si ' -> 'C6L.SI'. None if it can't be an SGX code."""
    code = str(text or "").strip().upper()[:16]
    if code.endswith(".SI"):
        code = code[:-3]
    return f"{code}.SI" if CODE.fullmatch(code) else None      # fullmatch: the whole text, no sneaky newline


def describe(info):
    """Turns Yahoo's answer into (name, type, sector), or None if it isn't something SGXray can track.

    info is the dict yfinance returns. A made-up code gives an empty one.
    """
    if not info or info.get("exchange") != "SES":            # not listed on SGX (or not found at all)
        return None
    kind = info.get("quoteType")
    if kind == "ETF":
        type_ = "etf"
    elif kind == "EQUITY":
        type_ = "reit" if str(info.get("industry") or "").startswith("REIT") else "stock"
    else:
        return None                                          # warrants, bonds, indices: not supported
    name = str(info.get("longName") or info.get("shortName") or "").strip()[:MAX_NAME_LENGTH]
    if not name:
        return None
    sector = info.get("industry") if type_ == "reit" else info.get("sector")
    return name, type_, (str(sector)[:60] if sector else None)


def yahoo_info(ticker):
    """Asks Yahoo about one ticker. Tests pass a fake instead, so they never use the internet.

    Returns Yahoo's dict (empty-ish for a code that doesn't exist), or None if Yahoo couldn't be reached.
    """
    import logging
    import yfinance as yf
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)   # a made-up code logs a 404; we report it ourselves
    try:
        return yf.Ticker(ticker).info or {}
    except Exception:                                         # network down, rate limited, Yahoo changed
        return None
