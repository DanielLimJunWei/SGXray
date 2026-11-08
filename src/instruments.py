"""The SGX stocks, REITs and ETFs SGXray knows about to start with.

A trade can only be saved for a ticker in this list (the trades table's foreign key
checks it), so add new tickers here.
"""

import db

# (ticker, name, type, sector)
STARTER_INSTRUMENTS = [
    ("D05.SI", "DBS Group Holdings", "stock", "Banks"),
    ("O39.SI", "OCBC", "stock", "Banks"),
    ("U11.SI", "United Overseas Bank", "stock", "Banks"),
    ("Z74.SI", "Singapore Telecommunications", "stock", "Telecoms"),
    ("C38U.SI", "CapitaLand Integrated Commercial Trust", "reit", "Retail and office"),
    ("A17U.SI", "CapitaLand Ascendas REIT", "reit", "Industrial"),
    ("M44U.SI", "Mapletree Logistics Trust", "reit", "Logistics"),
    ("N2IU.SI", "Mapletree Pan Asia Commercial Trust", "reit", "Retail and office"),
    ("ES3.SI", "SPDR Straits Times Index ETF", "etf", "Singapore market (STI)"),
    ("G3B.SI", "Nikko AM Singapore STI ETF", "etf", "Singapore market (STI)"),
]


def seed_instruments(conn):
    """Adds the starter list to the database. Safe to run again: existing tickers are updated."""
    for ticker, name, type_, sector in STARTER_INSTRUMENTS:
        db.save_instrument(conn, ticker, name, type_, sector)
