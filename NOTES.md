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

## Analysis (src/portfolio.py)

- Uses the **average cost** method, like Singapore brokers. Fees are added to the cost of a buy and taken off the money from a sale.
- A SELL removes cost at the average cost per share at that moment. So it's a loop over trades, not one pandas formula: each sale depends on everything before it.
- **Realised** = profit locked in by selling. **Unrealised** = value now − cost of what's still held; it changes daily.
- Selling everything resets the cost to exactly 0, so no rounding leftovers carry into a later buy.
- No saved price means value shows as blank (NaN), never as 0: a wrong number is worse than no number.
- Demo portfolio by hand: DBS avg cost $37.96 (7,592 / 200); C38U realised $278 on the 800-unit sale. The tests check these.
- Fixed with corporate actions: the demo DBS trade is now the real price (34.62), and SGXray shows the real 210 shares, $14,641.20 value, +85.2%.

- **Dividends received** = shares held at the start of each ex-date × amount. Bought on the ex-date = too late. Splits and bonus issues up to that day count. Ignored dividends don't.
- SGXray counts a dividend from its ex-date; the cash really arrives a few weeks later (the payment date). Singapore dividends and REIT distributions are tax-free for individuals.
- Total profit = unrealised + realised + dividends. Fees are already inside the costs, so they're not taken off again.
- A sold-out position is worth $0 even with no saved price; otherwise one missing price made the whole total NaN (a test caught it).
- Yahoo's dividend list can be odd: check unusual amounts against the company's announcements, then fix with `dividends.py add` or `dividends.py ignore`.

## Database changes (migrations)

- `CREATE TABLE IF NOT EXISTS` won't add a new column to a table that already exists. New columns go in `MIGRATIONS` in `db.py`, which runs `ALTER TABLE ... ADD COLUMN` only if the column is missing.
- Only ever add to the end of that list. A released migration has already run on someone's database.
- First one: `dividends.ignored` (0 or 1). Ignored rows stay in the table, so the next download sees them and doesn't add them back.

## Splits and bonus issues (src/adjust.py)

- **Rule: everything is stored as it really was.** Trades as on the broker statement; prices and dividends as really traded and paid.
- Yahoo rewrites old prices and dividends after a split or bonus issue. `market.py` downloads the actions first, then multiplies Yahoo's older numbers back: real = Yahoo × the factor of every action after that day. DBS 15 Mar 2024: 31.52 × 1.1 = 34.67; dividend 0.490909 × 1.1 = 0.54.
- `factor` = shares after per share before: 1-for-10 bonus = 1.1, 2-for-1 split = 2, 10-to-1 consolidation = 0.1. Yahoo calls them all "splits".
- Holdings change at the start of the ex-date: bought on the ex-date = no bonus; sold on the ex-date = already had it. Fractions of a share are dropped, as SGX does.
- The total cost doesn't change with a bonus, so the average cost per share drops.
- Manual actions (ones Yahoo doesn't know) change holdings, but are NOT used to un-adjust Yahoo's prices, because Yahoo never adjusted for them.
- Rights issues aren't actions: you pay for the new shares. Record them as a BUY at the rights price.
- Saved prices never need rewriting, even if a split happens later, because they're stored as real.
- Changing the price basis meant rebuilding the database (delete it, import, run market.py).

## Price data (yfinance)

- yfinance is **unofficial**: it can break or rate-limit. SGXray saves prices in SQLite and only fetches new days.
- `src/market.py` only saves a day's close after **5:30pm Singapore time**. Before that, Yahoo's price for today is still moving, and saving it would store a wrong close forever.
- First download for a ticker starts at its first trade. The STI ETF benchmark starts at the first trade in *anything*, so the comparison covers the whole portfolio.
- A close on the trade day differs slightly from the trade price (e.g. DBS 2024-03-15: close 34.67, bought at 34.62). That's normal: the trade happened during the day.
- Prices come back with tiny rounding errors (`71.709999`). Round when displaying.
- `auto_adjust=True` (the default) adjusts old prices for **dividends**. Use `auto_adjust=False` for the price actually traded that day.
- Even with `auto_adjust=False`, yfinance still adjusts for **splits and bonus issues**. Example: DBS's 1-for-10 bonus issue in April 2024 makes March 2024's ~$34.60 show as ~$31.47 (÷ 1.1). SGXray undoes this when saving (see Splits and bonus issues).

## Dividends

- Dividend data is **irregular** (different amounts, extra payouts) and Yahoo can have gaps. Keep manual dividend entry and check against the company's own announcements.
- Dividend dates from yfinance are **ex-dividend dates** in Singapore time (`+08:00`).
- Yahoo adjusts old dividends for bonus issues, like prices: DBS's 54-cent dividend (ex-date 2024-04-05) comes back as $0.490909. `market.py` turns it back into the real $0.54 before saving (see Splits and bonus issues).
- `market.py` fetches the whole dividend list each run (one small request), so Yahoo's corrections get saved. A change only counts when the amount is actually different.
- Fix a wrong or missing dividend by hand: `python src/dividends.py add D05.SI 2024-04-10 0.54`. Manual entries are marked `manual` and never overwritten by yfinance.
- A dividend Yahoo has wrong: `python src/dividends.py ignore D05.SI 2024-04-10`. It stays ignored after later downloads; `unignore` brings it back.

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
- Real trades before a split or bonus issue pass the 10% check, because saved prices are real too.
- `pd.read_csv` does **not** check the data: a word in the price column or a weekend date loads without any error. The CSV importer must validate every row (numbers are numbers, dates are trading days, SELLs don't exceed holdings) and reject bad rows with a clear message.
