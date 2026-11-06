# SGXray notes

Important things to remember about how SGXray works and the data it uses. Newest additions go at the bottom of each section.

## Database (src/db.py)

- All SQL lives in `db.py`. The rest of the app calls its functions and never builds SQL itself.
- Every query uses `?` placeholders, never f-strings, so user input can't change the SQL (SQL injection).
- `ON CONFLICT ... DO NOTHING / DO UPDATE` works in both SQLite and Postgres, so the same SQL will move to Postgres. The one change needed then: Postgres placeholders are `%s`, not `?`.
- SQLite ignores `REFERENCES` (foreign keys) unless `PRAGMA foreign_keys = ON` is run on every connection. `get_connection()` does it.
- `instruments`, `prices` and `dividends` are shared by all users; `trades` belong to one user (`user_id`).
- A dividend entered manually is never overwritten by yfinance data.
- Column names avoid SQL keywords like `date`: use `trade_date`, `price_date`, `ex_date`.

## Price data (yfinance)

- yfinance is **unofficial**: it can break or rate-limit. SGXray saves prices in SQLite and only fetches new days.
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
