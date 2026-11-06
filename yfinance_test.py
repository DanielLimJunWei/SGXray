"""15-minute check: can yfinance get SGX prices and dividends?

Run it from this folder with:  python yfinance_test.py
"""
import yfinance as yf

TICKERS = ["D05.SI", "C38U.SI", "ES3.SI"]  # DBS, CapitaLand Integrated Commercial Trust, STI ETF

# 1. Daily closing prices since the start of 2024
data = yf.download(TICKERS, start="2024-01-01", progress=False)
print("Last 5 closing prices:")
print(data["Close"].tail())
print()

# 2. Dividend history for one REIT
print("Last 5 dividends for C38U.SI (per unit, SGD):")
print(yf.Ticker("C38U.SI").dividends.tail())
