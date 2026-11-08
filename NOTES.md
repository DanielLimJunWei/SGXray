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
- `src/market.py` only saves a day's close after **5:30pm Singapore time**. Before that, Yahoo's price for today is still moving, and saving it would store a wrong close forever.
- First download for a ticker starts at its first trade. The STI ETF benchmark starts at the first trade in *anything*, so the comparison covers the whole portfolio.
- A close on the trade day differs slightly from the trade price (e.g. DBS 2024-03-15: close 31.52, bought at 31.47). That's normal: the trade happened during the day.
- Prices come back with tiny rounding errors (`71.709999`). Round when displaying.
- `auto_adjust=True` (the default) adjusts old prices for **dividends**. Use `auto_adjust=False` for the price actually traded that day.
- Even with `auto_adjust=False`, yfinance still adjusts for **splits and bonus issues**. Example: DBS's 1-for-10 bonus issue in April 2024 makes March 2024's ~$34.60 show as ~$31.47 (÷ 1.1). Trade prices and price history must use the same basis, or values will be ~10% off.

## Dividends

- Dividend data is **irregular** (different amounts, extra payouts) and Yahoo can have gaps. Keep manual dividend entry and check against the company's own announcements.
- Dividend dates from yfinance are **ex-dividend dates** in Singapore time (`+08:00`).
- Old dividends are adjusted for bonus issues, like prices: DBS's 54-cent dividend (ex-date 2024-04-05) shows as **$0.490909** (0.54 ÷ 1.1). That's correct on the same basis as the prices, but it won't match DBS's announcement.
- `market.py` fetches the whole dividend list each run (one small request), so Yahoo's corrections get saved. A change only counts when the amount is actually different.
- Fix a wrong or missing dividend by hand: `python src/dividends.py add D05.SI 2024-04-10 0.54`. Manual entries are marked `manual` and never overwritten by yfinance.
- Not handled yet: deleting a dividend that Yahoo has wrong (it would come back on the next fetch). It needs an "ignore" flag later.

## Trade data (demo_trades.csv)

- Columns: `ticker,date,side,quantity,price,fees`
- Dates as **YYYY-MM-DD** so they sort correctly. Weekdays only (SGX is closed on weekends).
- Rows in date order, oldest first. A SELL must come after enough BUYs of that ticker.
- SGX shares usually trade in lots of **100**.
- No spaces around commas, no blank line at the end.
- The importer (`src/importer.py`) reads every value as text (`dtype=str`) and checks it itself. It's **all or nothing**: one bad row means nothing is saved, and every problem is listed by row number (row 2 = first trade, like Excel).
- Importing the same file twice is safe: a trade with the same ticker, date, side, quantity and price as a saved one is skipped.
- Editing a trade in the CSV and importing again **adds a second trade**, because it no longer matches the saved one. The web app needs edit and delete buttons for trades.
- SELL checks use all of the user's trades in date order, saved and new together.
- Only weekends are rejected so far. SGX public holidays (e.g. Chinese New Year) aren't checked yet; the price data can catch those later.
- A ticker must be in `src/instruments.py` (the starter list) before trades in it can be saved.
- `src/checks.py` compares saved trades and manual dividends with market data and gives **warnings, not errors**: a trade on a day SGX didn't trade (public holiday), a price more than 10% from that day's close, a manual dividend at a time of year the company doesn't usually pay. They only work once prices are saved, so the order is: import, then `market.py`, then `checks.py`.
- A real trade before a split or bonus issue can be flagged by the 10% check, because Yahoo's older prices are adjusted. That's expected until corporate actions are handled.
- `pd.read_csv` does **not** check the data: a word in the price column or a weekend date loads without any error. The CSV importer must validate every row (numbers are numbers, dates are trading days, SELLs don't exceed holdings) and reject bad rows with a clear message.
