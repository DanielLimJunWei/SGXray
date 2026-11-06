# SGLens notes

Important things to remember about how SGLens works and the data it uses. Newest additions go at the bottom of each section.

## Price data (yfinance)

- yfinance is **unofficial**: it can break or rate-limit. SGLens saves prices in SQLite and only fetches new days.
- Prices come back with tiny rounding errors (`71.709999`). Round when displaying.
- `auto_adjust=True` (the default) adjusts old prices for **dividends**. Use `auto_adjust=False` for the price actually traded that day.
- Even with `auto_adjust=False`, yfinance still adjusts for **splits and bonus issues**. Example: DBS's 1-for-10 bonus issue in April 2024 makes March 2024's ~$34.60 show as ~$31.47 (÷ 1.1). Trade prices and price history must use the same basis, or values will be ~10% off.

## Dividends

- Dividend data is **irregular** (different amounts, extra payouts) and Yahoo can have gaps. Keep manual dividend entry and check against the company's own announcements.
- Dividend dates from yfinance are **ex-dividend dates** in Singapore time (`+08:00`).

## Trade data (demo_trades.csv)

- Columns: `ticker,date,side,quantity,price,fees`
- Dates as **YYYY-MM-DD** so they sort correctly. Weekdays only (SGX is closed on weekends).
- Rows in date order, oldest first. A SELL must come after enough BUYs of that ticker.
- SGX shares usually trade in lots of **100**.
- No spaces around commas, no blank line at the end.
- `pd.read_csv` does **not** check the data: a word in the price column or a weekend date loads without any error. The CSV importer must validate every row (numbers are numbers, dates are trading days, SELLs don't exceed holdings) and reject bad rows with a clear message.
