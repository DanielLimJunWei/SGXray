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

## Performance vs the STI (src/performance.py)

- A simple "profit ÷ cost" % ignores WHEN money went in. SGXray uses the money-weighted return, **XIRR** (same as Excel): the one yearly rate that turns every amount in and out, on its date, into what you have now.
- XIRR is solved by bisection (keep halving the range that contains the answer). It's slower than Excel's Newton method but can't fail to converge. Tested against Microsoft's own XIRR example (37.34%).
- The benchmark replays YOUR cash flows into ES3: each buy's dollars buy ES3 that day, each sale's dollars come out, ES3's dividends are paid out, and it pays the same fees you did. Without the fees it got a small free ride: a test (buy only ES3 → must tie exactly) caught it.
- ES3 units can be fractions in the what-if, so rounding doesn't decide the result.
- If a sale takes out more than the ES3 version is worth (you did much better than the index), it's flagged as a shortfall.
- Dividends count from their ex-date, a few weeks before the cash arrives. That's a tiny bias in the yearly rate.
- Under a year of history, the yearly rate can look extreme (a 10% gain in 2 months ≈ +77% a year), so the output warns.
- Demo portfolio, up to 2026-11-06: you +32.08% a year vs the STI ETF +25.86% a year.
- **Per stock** (`per_stock`): each stock's own money is replayed into ES3. The yearly rates show how good each pick was; the **dollar difference** shows how much it moved your result (a big holding matters more than a tiny one that doubled). The per-stock differences add up exactly to the whole-portfolio difference (tested).
- Demo: DBS helped (+$3,415.34), C38U held back (−$1,057.02), ES3 about level (−$4.99). Together +$2,353.33.
- Even ES3 vs itself is a few dollars apart: the STI version buys at the day's close, you paid a price during the day. Gaps under 0.5% of the money put in are shown as "about level".
- On the same date, the benchmark replay handles the dividend, then any split, then trades in their saved order. It used to sort same-day events alphabetically, which put a bonus before a dividend (fixed with a test).

## Value over time (src/history.py)

- Three tables that line up by date: **prices** (days × tickers), **holdings** (days × tickers), and **value** = holdings × prices, cell by cell, added across each row.
- `ffill` carries the last known price or holding over a gap (holidays, suspended days). `cumsum` gives running totals (money in, dividends). `resample("ME").last()` picks each month's last trading day.
- Holdings on a day: that day's bonus issue first (start of day), then that day's trades (by the close).
- `net_invested` = buys (with fees) − sales (after fees), as a running total. Profit on any day = value − net_invested + dividends so far. On the last day it equals `summary()["total_profit"]` exactly (tested), and the STI line equals `benchmark()` (tested).
- A day where a held stock has no price is NaN, not lower: `(holdings × prices).where(holdings > 0, 0)` then `sum(skipna=False)`.
- Running totals are summed over their OWN dates first, then read off on the trading days. Doing it the other way round dropped a dividend whose ex-date had no saved price (caught by the explainer's test).
- The monthly table uses `groupby(month).tail(1)` rather than `resample`, so each row keeps the real date of its last trading day (e.g. 28 Mar 2024, because 29 Mar was Good Friday).
- Demo: 666 trading days. Profit peaked at $14,032.78 on 2026-09-04 and is $11,517.48 now, so it fell about $2,500 from the peak. That's the idea behind drawdown (Week 3 risk view).

## Dividend income (src/income.py)

- **Forecast** = each dividend from the last 12 months, repeated one year later, on the shares held now. It's an estimate: dividends can be cut or raised, one-off payouts (REIT advanced distributions) may not repeat, and the real ex-date is announced shortly before.
- It's cautious when a company has just raised its dividend: DBS's Nov 2026 estimate uses Nov 2025's $0.75, though DBS now pays $0.81.
- **Dividend yield** (trailing 12 months) = last 12 months' dividends per share ÷ today's price. **Yield on cost** = the same ÷ your average cost. A high yield on cost means you bought cheaply, not that it's a good buy today.
- Dividends are now saved from 400 days BEFORE the first trade, so a stock bought last week still has a year of payouts to forecast from. Dividends received still only count ones you held (unchanged: $2,183.28).
- Python gotcha: `yield` is a reserved word, so a pandas column called "yield" can't be read as `row.yield`. It's called `div_yield`.
- Demo: portfolio yield 4.29%; DBS 4.56% on price, 8.45% on cost; about $973 expected in the next 12 months.

## Plain-English explanations (src/explain.py)

- "What does this mean?" boxes are written by **code from the numbers**, not by AI: free, instant, and they can never disagree with the table. AI is only for "why did the price move?", which needs news.
- Each month says: what you did, the snapshot (money in, value, profit as an equation), why profit changed since last month (prices vs dividends, and how they combined), and how you compare with the STI.
- It reminds users that buying or selling doesn't change profit by itself (it moves Money in and Value equally), but only in months with a trade.
- Tests check the exact sentences, so the wording can't drift away from the numbers.
- **Every table gets one**, and every new feature must come with its own: `explain.py 2024-03` (monthly table), `holdings`, `vs-sti`, `yields`, `forecast`. Each walks through one real row as a worked example. In the web app, each becomes an ⓘ button.
- Each explanation has two parts: **What does this mean?** (`lines`) and **⚠️ Watch out** (`watch_out`): beginner traps and warning signs, shown only when the user's own numbers make them relevant, plus a few general ones.

- Write maths in words ("divided by"), not symbols like ÷: the Windows terminal showed ÷ as "�". The web app can use symbols.
- One warning that applies to several stocks is merged into one line listing them, not repeated per stock.

- **Web design (Week 3):** each table gets two buttons. **ⓘ "What does this mean?"** opens the explanation; **⚠️ with a count** opens the Watch out popup and only appears when there are warnings. A warning about one stock also puts a small ⚠️ on that row. Use amber, not red: these are "think twice" notes, not errors. The terminal keeps printing both sections, since it can't do popups.

### Watch out catalogue (what triggers each)
| Trap | Shown in | When |
|---|---|---|
| Unrealised profit is only on paper | monthly, holdings | over half the profit is unrealised |
| Too much in one stock | holdings | one stock is over 50% of the value |
| Bonus shares aren't free money | holdings | the stock had a bonus issue or split |
| Missing or stale prices | holdings | a held stock has no price, or an old one |
| Fees eat returns | monthly | buys that month cost 0.2%+ in fees |
| One month's move tells you little | monthly | profit swung by over 5% of the value |
| Behind the STI: an ETF may suit you | monthly, vs-sti | you're behind |
| Short history makes yearly rates extreme (+10% in 2 months ≈ +77% a year) | vs-sti | under a year of history |
| Skill or luck? One stock did the work | vs-sti | one stock gives over 75% of the lead |
| Past results don't predict the future | vs-sti | always |
| An ETF gives you the average | vs-sti | when you're ahead |
| "On cost" isn't today's yield | yields | your cost is below today's price |
| Very high yield can be a yield trap | yields | yield over 7% |
| REIT one-off distributions inflate a year | yields | you hold a REIT |
| Yields and forecasts aren't promises | yields, forecast | always |
| Most income from one stock | forecast | one stock gives over 50% of expected income |
| Buying before the ex-date isn't free money | forecast | always |

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

## Audit (8 Nov 2026)

Checked against official sources: DBS bonus issue (1-for-10, ex-date 22 Apr 2024, on SGX), DBS dividends 2024–26 (54c quarterly in 2024; 60c in Apr 2025; 60c + 15c capital return from May 2025; 66c + 15c from Apr 2026), CICT distributions (2.16c advanced Sep 2024, 3.29c Feb 2025, 5.62c + 1.35c on one Aug 2025 ex-date, 4.61c Feb 2026), SGX close (closing auction 5:00–5:06pm, trade-at-close until 5:16pm, so 5:30pm is safe), IRAS (one-tier dividends and S-REIT distributions are tax-free for individuals). Demo totals re-added by hand: cost 13,639, value 22,695.20, dividends 2,183.28.

Fixed in the audit:
- Two identical fills (same ticker, day, side, quantity, price) in separate files: the second was wrongly skipped as a duplicate. Duplicates are now counted, not just spotted.
- Spreadsheet-style numbers ("1,000", "$34.62", "S$10") are accepted; digits from other scripts ("١٠٠") are rejected; "D05" suggests "D05.SI".
- A held stock with no price made totals quietly too low. Totals are now unknown, and the stock is named.
- Stale prices (5+ days older than the newest) are flagged; "Prices as of" shows the newest date.
- An impossible sale saved without the importer crashed with a divide-by-zero; it's now a clear error.
- A dividend on the same ex-date as a bonus issue was paid on the bonus shares too. Bonus shares arrive after the record date, so they don't get it.
- New check: a saved price that moves more than 30% in a day (not on a split day), a common bad-tick problem in free data.

Known gaps (not bugs, but limits):
- Yahoo also adjusts for rights issues and preferential offerings without listing them as splits. CICT's 1H 2024 DPU was 5.43c, but Yahoo shows 5.4159c after its Sep 2024 preferential offering. The effect is under 1%; fix it by hand with `dividends.py add`. Older prices for that counter are a little low for the same reason.
- Mergers, ticker changes, delistings and privatisations aren't handled yet.
- Scrip dividends (e.g. DBS's scrip scheme): record the new shares as a BUY at the scrip price. The dividend is still counted as income, which is correct, because it paid for those shares.
- Money is stored as floats, so tiny leftovers like 0.5999999 appear inside calculations. Everything is rounded for display; integer cents or Decimal before launch.
- Fees should be the broker's total charge: commission, clearing fee, SGX fee and GST.

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
