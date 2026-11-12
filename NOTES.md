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
| Weeks of results say almost nothing | vs-sti | under 30 days (no yearly rate at all) |
| STI comparison is rough after a big withdrawal | vs-sti | shortfall |
| STI price out of date | vs-sti | stale benchmark |
| Bad timing: added money before falls (add bit by bit instead) | vs-sti | XIRR well below TWR |

- The vs-sti explainer has a **"Why SGXray shows two returns"** section (TWR = your picks, XIRR = your money, a big gap = timing), ending with what the user's own gap means. "Timing mattered" = XIRR and TWR are more than the larger of 2 points or 10% of the return apart (2 points is a lot at 5% a year, but little at 35%).
| Skill or luck? One stock did the work | vs-sti | one stock gives over 75% of the lead |
| Past results don't predict the future | vs-sti | always |
| An ETF gives you the average | vs-sti | when you're ahead |
| "On cost" isn't today's yield | yields | your cost is below today's price |
| Very high yield can be a yield trap | yields | yield over 7% |
| REIT one-off distributions inflate a year | yields | you hold a REIT |
| Yields and forecasts aren't promises | yields, forecast | always |
| Most income from one stock | forecast | one stock gives over 50% of expected income |
| Buying before the ex-date isn't free money | forecast | always |
| A rising line isn't all profit: much of it is your own money | X-ray chart | always |
| Price gains are on paper; dividends are cash you have | X-ray chart | price gains are positive |
| Prices below what you paid: a loss on paper | X-ray chart | price gains are negative |
| Below the dashed STI line | X-ray chart | worth + dividends below the STI ETF version |
| A short stretch of chart shows luck, not skill | X-ray chart | under a year of history |
| Income growth: more shares vs companies paying more | dividends by year | the last full year is higher than the first |
| Don't compare a part-year with a full year | dividends by year | the first year started after January, or this year isn't over |
| Most of a year's dividends from one stock | dividends by year | one stock gives over 50% of the latest year |
| A REIT's one-off payout can inflate a year | dividends by year | you've had REIT dividends |
| Price below your average cost: a loss on paper | stock chart | today's price is under your average cost |
| A bonus issue drops the price, not the value | stock chart | the stock had a bonus issue or split |
| Averaging down lowers your cost but adds risk | stock chart | you bought 5%+ below your average cost |
| The price line leaves out dividends | stock chart | always |
| One day's move tells you almost nothing | worth now | there's a day's change |
| A 3%+ day is big: check the news, don't rush | worth now | the day's change is over 3% |
| Closing prices, not live | worth now | always |
| A total isn't a yearly rate | total profit | always (with the simple total return) |
| Most profit is unrealised | total profit | over half the profit is unrealised |
| Stretches are totals, and short ones are noise | period returns | always |
| A period appears once you have that much history | period returns | a period is longer than your history |
| Selling locks it in: "would I buy it again today?" | sold | always |
| Selling after a fall often misses the recovery | sold | a stock was sold at a loss |
| Near the 52-week low isn't cheap | stock chart | today's price is in the bottom 20% of the range |
| Near the 52-week high isn't a forecast | stock chart | today's price is in the top 20% of the range |
| A bonus issue widens the 52-week range | stock chart | a bonus issue or split in the last 52 weeks |

## Database changes (migrations)

- `CREATE TABLE IF NOT EXISTS` won't add a new column to a table that already exists. New columns go in `MIGRATIONS` in `db.py`, which runs `ALTER TABLE ... ADD COLUMN` only if the column is missing.
- Only ever add to the end of that list. A released migration has already run on someone's database.
- First one: `dividends.ignored` (0 or 1). Ignored rows stay in the table, so the next download sees them and doesn't add them back.
- `trades.note` (w317): optional text, NULL when there's no note, with `CHECK (length(note) <= 280)`. SQLite allows a CHECK on an added column, so old databases get the same rule as new ones.

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

## Design system (design-system/)

- **Mood:** a rainy evening in a finance office. Cool navy outside, warm lamplight inside, a screen glowing calmly in blue. Clear, smooth, never loud or tiring on the eyes.
- `static/css/tokens.css` holds every colour, font, size, space, corner and timing as a named variable. Pages use only these; a missing value becomes a new token, never a hard-coded one.
- Colours: night `#0A0F1E`, dry navy `#121C33`, screen glow `#3A73FF` (data accent, sparingly; never small text), glow-as-text `#9CC4FF`, lamplight `#E3A35E` (warmth, Watch out), paper text `#EEE7DC` (never pure white), muted up/down `#7BC4A0` / `#D98282`.
- Fonts: Space Grotesk for headings and the wordmark (weight 500, -0.02em; the hero -0.04em), Inter for body text, JetBrains Mono for numbers. (The home page's "Scroll to look inside" hint was removed on 11 Nov 2026: the page reads fine without it, and the grab cursor already shows the chart can be turned.) History: Newsreader (too childish at display sizes), then Space Grotesk. A JetBrains-Mono-everywhere try on 11 Nov 2026 was reverted the same day: only the scroll hint was meant to change.
- Chart layers: your money = solid slate, price gains = blue halftone dots, dividends = amber halftone dots, STI = light dashed line with a dark outline so it reads over the dots.
- Textures (felt grain, dot grid, halftone, lightbox glow, ASCII, pixel X logo) only in backgrounds and decoration; numbers always on solid surfaces.
- Motion: real numbers count up once, then sit still; decoration (rain, the sample chart) may move gently; everything is still when "reduce motion" is on.
- `design-system/preview.html` shows it all, including the scroll-driven X-ray chart built from the demo portfolio. With the app running in debug mode, open http://127.0.0.1:5000/design-system/preview.html (hidden on the live site).
- The landing page (`templates/home.html`, scene in `static/js/home-scene.js`) is one made-up 3D stock chart (Three.js 0.186.1, smooth scroll from Lenis 1.3.26) that keeps its shape while the camera moves round it. Scrolling goes: whole chart behind the headline, then a zoom while a scan line reveals the numbers, then the line splits into money in / price gains / dividends (the X-ray), then a pull back. Small ▲/▼ arrows fade in where the line rises or falls. It's pure decoration (same fake data for everyone); real user charts animate in once, then stay still. One motif, as on the Conoid reference: no unrelated effects.
- Lessons from building it: many loose lines morphing between shapes looked messy; a single object with a moving camera reads better. Text over the scene needs a dark haze or solid panel behind it. Wait for the web font to load before drawing labels onto canvases, or they fall back to a default font.
- Lessons from building it: `.wrap { padding: 0 X }` silently wiped `section`'s vertical padding (class beats element), so use `padding-inline` / `padding-block`. On phones, SVG text shrinks with the chart, so the script resizes chart text to stay ~12px. Opening the HTML file directly in the browser pane loaded it as `data:` and dropped `tokens.css`, so serve it instead.

## Web app (app.py, Flask)

- Run it: `python -m flask --app app run --debug`, then open http://127.0.0.1:5000. Debug mode reloads when you save a file; never use it on the live site.
- `app.py` turns addresses into pages: `/` is the 3D landing page, `/demo` is the sample portfolio (GET only, so nobody can change it). Each page view opens its own database connection and closes it afterwards.
- `templates/` holds the HTML with blanks Jinja fills in. `base.html` is the shared frame (nav, lamp, grain, footer with the data credit); the other pages fill its blocks. `_explain.html` is the ⓘ / ⚠ pair of buttons and popups, reused under every table.
- `static/` holds files sent as they are: `css/tokens.css`, `css/site.css`, `js/home-scene.js` and `js/count-up.js`.
- Numbers on pages use fmt.py through template filters (`money`, `pct`, `num`), plus `trend` and `arrow`: colour is never the only signal, so up/down also get ▲/▼.
- Jinja escapes everything it fills in, so text from a CSV can't become HTML or a script. Every response says "don't put me in a frame" and "trust my file types".
- Home page: hold the left mouse button on any empty space and drag to turn the 3D chart: all the way round left and right (360 degrees and more), and a small tilt up and down (never upside down). Let go mid-swing and it keeps spinning with momentum, then slows to a stop: the spin speed is measured from the last 0.1 s of the drag, so a hard flick spins far and a gentle push barely coasts; holding still before letting go means no spin. The slow-down is time-based (speed halves about every 0.4 s), so it feels the same at any frame rate. Grabbing a spinning chart stops it. Double-click to turn it back the short way round. It swings the CAMERA around the chart's centre, together with the point it looks at, so the chart keeps its shape and every scroll stage (zoom, scan, X-ray layers) still lands on the same part of the chart from the new angle. Only the letters themselves and clickable things (links, buttons) stop a drag; the space beside a short line and the padding inside the panels still turn the chart (`onLetters` checks the exact character box under the pointer). The cursor follows the same rule: open hand to turn, arrow on letters, pointing hand on clickable things. Mouse and trackpad only: on phones a finger drag keeps scrolling the page.
- The X-ray chart (`static/js/xray-chart.js`, hand-drawn SVG, no chart library): month-end snapshots from history.py stacked as your money (solid), price gains (blue halftone) and dividends (amber halftone), with the STI ETF as a dashed line. The scan reveal plays ONCE when the chart first comes into view, then it stays still. "Animation: on/off" is remembered on the device (localStorage) and starts off when the system's "reduce motion" is on. Point, tap or use the arrow keys for any month's numbers; "Show as a table" lists every month for screen readers and anyone who prefers numbers.
- Dividend income by year (`income.by_year`, `explain.explain_income_by_year`): one amber halftone bar per calendar year, by ex-date. Part-years (the first year if you started after January, and the year that isn't over) are lighter with a dashed outline and labelled "from March" / "so far". The bars are drawn on the server as plain SVG (positions in `app._bar_layout`), so they show even without JavaScript; `static/js/reveal.js` makes them grow in once when they come into view, and follows the same "Animation: on/off" choice.
- The ⓘ and ⚠ boxes are non-blocking (`popover="manual"`, no dimmed backdrop), so you can keep one open and still point at the chart it explains. They open in the bottom corner, stay open until Close or Esc, can be dragged by the title bar or moved with the arrow keys on the ⠿ handle, and resized from the bottom-right corner by dragging or with the arrow keys (`static/js/popups.js`). A moved or resized box reopens the same way while the page is open. On phones they're capped at 45% of the screen height so the chart stays visible above.
- Per-stock price charts (`src/stocks.py`, `static/js/stock-chart.js`): "Price chart" under each stock in the holdings table opens its closing-price line right under the table, one stock at a time. On it: your buys (▲), sales (▽), dividend ex-dates (● along the bottom), bonus issues (a thin dashed line) and your average cost as a dashed STEP line, which only changes at a trade or a bonus issue. Point, tap or use the arrow keys for any day's price, your average cost then, and anything you did that day. The line draws in once when opened (if animation is on). At most 400 points are drawn, always keeping the days with a marker, so the page stays light.
- Compare points (`static/js/compare.js`, on the X-ray chart and every price chart): double-click (or double-tap) up to 3 days to set points A, B and C; click a point's circle to remove it, or "Clear". Below the chart each pair shows its change: for a price chart, the price move in $ and % plus the dividends paid per share in between (and a note if a bonus issue in between makes the move look smaller); for the X-ray chart, how much "All together" grew, split into your own money going in vs what you actually earned (price gains + dividends), next to the STI ETF version. Checked against other tools first: TradingView, Optuma, WH SelfInvest and Apple Stocks all have a two-point "measure" tool, and users request it (MultiCharts, Freetrade forums). Max 3 points to stay readable.
- Both charts have axis titles (S$ up the side, the date along the bottom). Sales on the price chart are solid peach triangles above the line on a short stem (buys: solid blue below), so markers never cover the line.
- Six extras (`src/insights.py`, plus `history.period_returns`), each with its own ⓘ/⚠ and tappable terms, placed so the page stays calm:
  - Day's change: a small line under "Worth now", the move from the previous close to the latest one, dated ("on 6 Nov 2026") so it never looks live. Profit change, so a buy or sale that day isn't counted as a gain.
  - Simple total return: under "Total profit", profit divided by ALL money put in (every buy, fees included): +75.7% on $15,207 for the demo. A total, not a yearly rate.
  - Weight %: a column in holdings (each stock's share of what the portfolio is worth).
  - Period returns: one slim row under the X-ray chart: 1M, 3M, YTD, 1Y and All, you vs the STI ETF. Time-weighted over each stretch, so deposits don't count as growth; "All" equals the time-weighted total. A stretch longer than your history shows "n/a" instead of a shorter one.
  - "Sold": a folded section under holdings, only when a stock has been sold completely: held from/to, put in, got back, realised, dividends, made in all.
  - 52-week range: a small bar under each price chart's heading (low, high, where today sits), with Watch outs for near the low / near the high / a bonus issue inside the year.
- Log in, sign up and account pages (`templates/_lightbox.html`, `static/js/lightbox.js`): designed with the charles-unslop process (after Charles Liu's "Removing AI slop, day 4: login screen"). Concept: "Logging in is putting your own film on the lightbox: it only lights up once it's yours." The form is a sheet of X-ray film clipped to a backlit panel; the film shows the demo portfolio's X-ray chart, printed from its real monthly numbers. While you type a password the light dims (a privacy cue, like covering the film); on submit it brightens, then the page changes. One primary button, no social logins, nested radii (14px box, 10px inset, 4px film and fields: exact, not soft), one depth cue (the backlight). The film edge is printed in small caps because real film edges are. The film shows a plain trading-screen price line (the demo's value, month by month) in the home chart's colours (blue line and fill, amber 3-month average, blue volume ticks), not the X-ray layers. The graph itself stays plain; the detail is on the board: a bevelled metal frame, four corner screws and a notched film corner. The edge just says "SGXRAY" (no "imaging", no footer strip, no switch: kept simple and firm). The line has a faint glow you only notice if you look (removed while the light is dimmed). Its edge reads like a real X-ray label: "PATIENT: YOUR PORTFOLIO | CHECK-UP DUE" (sign up: "PATIENT: NEW | FIRST SCAN"): the X-ray is what you get after logging in. While you type a password, the desk lamp in the top-right corner switches off too (`html.lamp-off`).
- Ambient colour (all pages, `.ambient` + `static/js/ambient.js`): after Conoid and Doors, the dark isn't one flat colour. Three very soft pools from SGXray's world (screen blue bottom-left, a deeper indigo low on the right, a navy glow along the floor), 3-8% at their centres; the indigo stays out of the top-right corner, where it used to tint the warm lamp purple, so it reads as "not plain black" without drawing the eye; they drift a little as you scroll. They sit behind the 3D chart and every panel (z-index -1), so nothing is covered. Gotcha found: `body` must have no background of its own (the night colour is on `<html>`), or it paints over a z-index -1 layer and hides it; the lamp's light now lives only in `.lamp`, so it can be switched off.
- Your trades (`/trades`, w308; `src/trades.py`, `templates/trades.html`, `_trade_form.html`): add, change and delete your own buys and sells. The form copies a broker's contract note (stock picked from the starter list, Bought/Sold switch, date, shares, price per share, optional fees). Every check is the importer's (`importer.check_fields`, then the sell check over all your trades), so the form and a CSV follow the same rules; a change or delete that would leave a later sale with too few shares is refused with the reason. Delete asks first on its own page (no script). A new stock, or a date earlier than the saved prices, downloads that stock's splits, prices and dividends straight away; if Yahoo fails the trade is still saved and the page says prices come with the next update. Upper limits added to the shared check (100 million shares, S$100,000 a share, S$100,000 fees) after a test showed 32 nines being saved as a price. Gotcha: two dev servers on `localhost:5000` and `localhost:5001` share cookies (cookies ignore the port), so one logs you out of the other; use `127.0.0.1` for the second.
- Any SGX stock (w309, `src/lookup.py`, `/trades/lookup`): "Can't find your stock in the list?" under the trade form takes an SGX code (C6L, c6l and C6L.SI all work), asks Yahoo, and adds it to the shared instruments list, already picked in the form. What Yahoo returns (checked 11 Nov 2026 with yfinance 1.8.0): `exchange` is "SES" for SGX; `quoteType` "EQUITY" or "ETF"; REITs are EQUITY with `industry` starting "REIT - "; a made-up code returns a dict of Nones (no error), while a network failure raises, so the page can tell "not on SGX" from "Yahoo is down". Only an SGX-shaped code is ever sent, only to Yahoo, 20 lookups an hour per person.
- "Why I bought" notes (w317, `trades.note`, `src/trades.py`): an optional line on any trade, labelled "Why I bought" or "Why I sold" (the label follows the Bought/Sold switch with CSS `:has()`, no script). Up to 280 characters, checked in the form and again by a CHECK rule in the table; line breaks and control characters become spaces (`clean_note`); always shown as escaped text. It shows quoted under the stock in the trades list, and again on the portfolio: a "Why you bought" link ("Your notes" once a sale has a note) beside the stock, in Holdings and in Sold, opens a box with each note, the trade it belongs to, and today's price, ending "Does your reason still hold?" (or, for a stock you've sold, "Did it turn out the way your note expected?"). The point is learning: beginners forget why they bought, then sell on a bad day. Tests: `tests/test_notes.py`.
- Bought today, no close yet: SGXray only uses final closes (~5:30pm SGT), so a stock bought today has no price until then. The portfolio says "Waiting" / "pending" instead of "n/a" for anything that needs that price (one switch: `g.waiting_for_close` makes the money/pct/num filters say "pending"); a yearly rate under 30 days says "under 30 days" in each column, because that doesn't change at 5:30pm. Bug found on the way: a per-stock result with no price (NaN) used to be called "held you back"; now "not known yet" (`performance._verdict`).
- Returns: yearly or so far (11 Nov 2026). From a year of history, "You vs the STI" and the per-stock table show a yearly rate ("+8.1% a year"); under a year, the plain total over the time held ("+3.0% over 4 months", via `performance.over_days`, which turns the XIRR back into a total); under a month, "too soon". Why: stretching a few months into "per year" exaggerates luck (+3% in 2 months = +19% a year), and the GIPS standard says not to annualise under a year. The 30-day floor stays because a few weeks against the STI is mostly noise. Explanations use `explain._rate` so the words match the numbers.
- **The page rule** (every table and figure, now and in future; `tests/test_page_rules.py` fails the build if one breaks it):
  1. Every cell shows a value or a reason in words, never a blank and never "n/a". The reason words, used the same way everywhere: **pending** = waiting on tonight's closing price; **too soon** = not enough history yet (under a month to compare, or a period longer than your history); **"in 4 months" / "a year"** under a return = a total so far / a yearly rate; **"after today's close"** = a price for a stock bought today; **no price yet** = no closing price saved for a stock for any other reason (most often: bought today, looked at after 5:30pm, before the price update has run). That last state is the one that showed "n/a" on 11 Nov 2026: none of the tested states covered it, so it now has its own test. The same rule covers links: a link never does nothing. A stock with no saved prices has no price chart yet, so its "Price chart" link opens the `no-chart` meaning (why there's no chart, and when it comes) instead of a dead click.
  2. An empty table shows one full-width row saying why (`empty_row(cols, reason)` in `dashboard.html`), never an empty frame.
  3. Total rows have no gaps: every column gets its own cell. A column with no whole-portfolio number (paid a share, price, avg cost, shares, last ex-date) says **per stock**, a tap-a-term explaining why a total there would mean nothing. No cell stretches over several columns (`colspan`), because the columns under it look empty: that was the demo's gaps on 11 Nov 2026, in the yields and forecast totals. Only an empty table's one-message row may stretch. The test checks for `colspan` in every table on the portfolio, demo and Trades pages.
  4. Every key figure and every table has a "What does this mean?" box, in every state (also "Too soon" and empty), from an `explain_*` function in `src/explain.py`.
  5. Every reason word is a tap-a-term, never a hover-only `title=` tooltip (phones can't hover, and most people never find one). Glossary keys: `pending` (also the big "Waiting"), `too-soon`, `after-close`, `not-yet` (no STI ETF prices saved), and `a-year` for "in 4 months" / "a year" under a return. "pending" comes from the number filters in `app.py`, so they return the same button as the `term()` macro: both use `glossary.button()`, the one place a tappable word is built. `check_reason_words()` in `tests/test_page_rules.py` fails if a table cell, big figure or period row shows a reason word outside a term button.
- Tap a term: key words on the demo (dividends, unrealised, avg cost, yield, STI ETF, ex-date...) have a quiet dotted underline; tapping one opens a short meaning and an example next to the word. Every meaning lives in `src/glossary.py`, so the dashboard and the coming Learn page say the same thing. `templates/_term.html` has the `term()` macro. The meaning boxes are the same movable, resizable boxes as ⓘ/⚠ (`static/js/popups.js`): they open centred under the word (above it if there's no room), only one at a time, and every box is kept fully inside the visible page, measured without the scrollbar (measuring with it is what let boxes on the far right slide off screen). A test checks every tappable word has a meaning. Kept uncluttered on purpose: labels and headers only, never every word in a sentence.
- `tests/test_web.py` opens each page with Flask's test client: no crash, the right totals, no "nan", the demo is read-only.
- Found while building it: the dashboard crashed when the STI ETF had no prices yet (compare() raises). The page now shows "n/a: no STI ETF prices saved yet".

## Feature research (9 Nov 2026)

What investors value in trackers (Financial Horse, Seedly, PortfolioTrackr, The Accounting Investor): accurate SGX REIT and stock dividends, projected dividends and income by year, returns including dividends, comparison with the STI, allocation charts, multiple portfolios. Complaints: small free tiers, poor local broker support, no good CPF/SRS or regular-savings-plan support, and trackers that encourage daily price-watching. Beginner mistakes (Endowus, The Smart Investor, Saxo): too little diversification and home bias (local banks and REITs), not knowing about fees, emotional decisions, not understanding what they own.

Added because of it: Week 3 gets allocation and concentration (moved up from stretch), a Learn page, regular savings plans, a Simple/Detailed switch, a fees insight, dividend income by year, and "why I bought" notes. Stretch gets a monthly check-in, a "what if" calculator, alerts, a watchlist, Savings Bonds/T-bills/FDs, goals, REIT and bank health numbers, a PWA and dark mode.

## Accounts and security (src/auth.py, app.py)

Built with the security-and-hardening skill. No new libraries: Werkzeug (comes with Flask) does the hashing.

| Protection | How | What it stops |
|---|---|---|
| Salted, slow password hashes | scrypt via `generate_password_hash`, a fresh random salt per password, stored with the hash | Stolen databases giving away passwords; rainbow tables |
| Show / Hide on password boxes | A small button inside every password box (`static/js/lightbox.js`) shows what you typed; the box turns back to hidden the moment the form is sent | Typos in a password you can't see, without the browser ever saving it as plain text |
| Password rules | 12-128 characters, not on the built-in common list, not your email name | Easily guessed passwords; huge inputs that tie up scrypt |
| Login rate limit | 10 failures per 15 minutes per email AND per network address, counted in the `login_attempts` table (shared by every server process) | Robots guessing passwords. While locked, even the right password is refused |
| No account enumeration | Same message, status and timing for "wrong password" and "no such email" (a dummy hash is checked); sign-up doesn't say "email taken" | Finding out who has an account |
| Server-side sessions | A `sessions` table holds a SHA-256 of each session id; logout and password changes delete rows; 7-day limit | A copied cookie staying valid after logout (found in the 54-check audit) |
| Safe session cookie | Signed with a secret from `SGXRAY_SECRET_KEY` (or `instance/secret_key`, Git-ignored); HttpOnly, SameSite=Lax, Secure on the live site (`SGXRAY_HTTPS=1`), 7 days | Cookie theft by scripts, forged sessions, other sites riding your login |
| New session at login; session_version | `session.clear()` at login; changing your password bumps `users.session_version`, so other devices are logged out | Session fixation; a stolen session outliving a password change |
| CSRF tokens | A random token in the session and in every form, compared in constant time; logout is POST-only | Other websites submitting forms as you |
| Ownership | The user id comes only from the signed session, never the URL; every query filters by it | Reading or changing someone else's portfolio (IDOR) |
| Safe redirects | `next=` must be a path inside SGXray | Login links that bounce you to a fake site |
| Security headers | CSP (scripts only from SGXray, the jsDelivr CDN, or an inline script with this page's random nonce), X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy, HSTS on the live site, no-store on private pages | Injected scripts, clickjacking, downgrade to HTTP, private pages left in the browser cache |
| Security log | `security_log` table: signup, login, login_failed, login_blocked, logout, password_changed, with time and network address. Never passwords | Spotting attacks; an audit trail |
| Data minimisation | Only email + password hash are stored | Holding personal data with no purpose (PDPA) |

**The account page** (`/account`): an overview of your email, the day you joined (in Singapore time; SQLite saves UTC) and a "Change password" button. The password form is its own page, `/account/password`, with every check it had (current password, rate limit, security log, other devices logged out). After a change it redirects back to the overview (so refreshing can't send the form twice), and a one-time flag in your signed session shows "Password changed" once; adding `?changed=1` to the address can't fake it. The overview takes no form posts at all. "Log in as someone else" logs you out and opens the log-in page (the logout form sends `then=login`, a fixed choice, never an address). Export my data and Delete my account (w411) become new rows in the same list.

**Forgot your password?** (`/forgot`, `src/mailer.py`): type your email; if it has an account, SGXray emails a link that works for 30 minutes, once. The page says "If an account uses …, we've sent it a link" either way, so it can't be used to find out who has an account. Only a SHA-256 hash of the link's secret is stored (`password_resets` table), like sessions. Opening the link (`/reset/<secret>`) only moves the secret into your session and redirects to `/reset`, so it leaves the address bar and history, and email apps that open links to scan them can't use it up. Saving the new password ends every session (every device, this one too) and lands on log in with a green note. Limits: 3 emails an hour per address (no inbox flooding), 10 requests an hour per network address. Email goes out through any service's SMTP with Python's own `smtplib` (no new library); without `SGXRAY_SMTP_HOST`, on your computer it's printed in the server's terminal (the "dev outbox"), and on the live site nothing is sent or printed. On the live site, links use `SGXRAY_BASE_URL` only: building them from the visitor's request would let someone send a real reset email whose link points at their own site (host-header poisoning). Attack tests: `tests/test_reset.py`.

**The log-in film** says "Patient: unidentified" (you haven't said who you are yet), and quietly fills in with the email as you type it (`static/js/lightbox.js`, `data-patient-from`). Its one line under the heading is short on purpose: "This is the demo portfolio. Log in to X-ray yours."

**The Trades page** has its own "What does this mean?" box (`explain_trades` in `src/explain.py`): what the list is, how Total is worked out, and the fees paid so far, with a reminder to copy trades from the broker's contract note. In its Side column, Bought is a soft green (`--color-buy` #8FD9B4) and Sold a soft rose (`--color-sell` #EC9A9A): a touch brighter than the profit/loss pair, which stays as it was. The words stay, so colour is never the only clue. The add/change trade form's Bought/Sold switch matches: the chosen side shows its colour on a faint wash (`--color-up-wash` / `--color-down-wash`, 16%), and the other side hints its colour on hover. **"Add or change trades"** on the portfolio is a box, not a bare link (`.btn-well`): darker than the panels and tables (`--color-well` #0D1528 vs the panels' #121C33), with a hairline edge that lights up on hover.

The 70-check audit (results and evidence) is in `SECURITY.md`. Part 4 (checks 55-70) added: one account per email even when two sign-ups race, sign-up timing that doesn't reveal existing emails, a forged-cookie test, and `requirements.lock` (all 29 libraries at exact versions, audited clean). The first 54 checks found and fixed: server-side session invalidation, rate limits on sign-up and password changes, retention for security records (180 days) and failed-login counts (1 day), generic error pages, and pinned versions in `requirements.txt`.

`tests/test_auth.py` attacks all of this: same-password users get different hashes, weak passwords are refused, wrong-password and unknown-email answers are identical, the 11th guess is locked out, the demo account can't be logged into, cookie flags, a new session at login, password change logs out the other device, logout can't be triggered by a link, forms without a token are rejected, users can't see each other's trades, SQL injection in the login form does nothing, four kinds of evil redirect are refused, a fresh CSP nonce every page, and nothing secret reaches the log.

**For the live site (Week 4):** set `SGXRAY_SECRET_KEY` (a long random value) and `SGXRAY_HTTPS=1` in Render's settings; add Werkzeug's `ProxyFix` so the rate limit sees each visitor's real address behind Render's proxy; never run with `--debug`.

**Future security features** (not built yet):
- Email verification and "forgot password" with single-use, short-lived reset links (needs an email service).
- Two-factor sign-in with an authenticator app (TOTP), and backup codes.
- Checking new passwords against known breaches (Have I Been Pwned's private range lookup; it never sends the password itself, but it's an outside service).
- "Your devices": see and log out individual sessions; an email when there's a login from a new device.
- Delete my account and export my data (w411), including the security log.
- A dependency audit (`pip-audit`) and GitHub's secret scanning and Dependabot in CI (w402).
- An automated penetration test with Strix against a staging copy (Week 4), plus Content-Security-Policy violation reports.
- Encrypted, regularly tested database backups on the live host.

## Who SGXray is for (10 Nov 2026)

Two groups: people who already invest and want to understand their numbers, and people with **no stocks yet** who want to learn before using their own money. For the second group, the app must be fully useful without a portfolio:
- a "Before you invest" lesson path, taught with the demo portfolio's real numbers (w313);
- a practice portfolio: pretend trades at real SGX prices, with the same tables, explainers and STI comparison (w320);
- an "Am I ready to start?" self-check (w321);
- tap any term in a table for a one-line meaning (w322);
- a home page that speaks to learners too, with "Start learning" beside "Try the demo" (w323).

Rules: education, never advice (no "buy this"); calm, not gamified (no points or streaks; progress at most "3 of 8 lessons read").

Lesson path plan (w313, agreed 11 Nov 2026; 9 lessons since a scams lesson was added the same day, see below): `/learn` lists 8 lessons, each at `/learn/<slug>`, readable without an account: 1 Before your first dollar, 2 What you actually own, 3 Where your shares are kept (CDP vs custodian), 4 What fees really cost, 5 Dividends, 6 Risk and time, 7 Picking stocks vs buying the market, 8 Reading SGXray. It ends at the "Am I ready to start?" self-check (w321). Every lesson: the idea in one line; 2-3 short sections with tap-a-terms from `src/glossary.py`; an "In the demo" box with live numbers from the demo portfolio (worked out by the same code as the dashboard) and a link to that table on the demo; Watch out (the usual beginner mistake); one "Check yourself" question, answer hidden until tapped, never scored; Next; a one-line not-advice note; sources named (SGX, MAS, CDP). Progress shows as "3 of 8 read": saved to the account when logged in, in the browser (localStorage) when not. Built in two steps: the Learn page and lessons 1-2 first, reviewed, then the other 6 in the same style.

Built so far (11 Nov 2026): the Learn page and lessons 1-2. Code: `src/lessons.py` (the list of 8, and the demo numbers: `biggest_dip` finds the demo's biggest fall with no trades in between, so it's the market and not money going in or out; `what_you_own` lists the demo's holdings by kind), `templates/learn/_lesson.html` (the shared layout every lesson fills in), one template per lesson, `static/js/learn.js` (logged-out progress in localStorage), the `lesson_reads` table (only the lesson's name and when; deleted with the account), routes `/learn`, `/learn/<slug>` and `POST /learn/<slug>/done`. "Check yourself" is a plain `<details>` box, so it works without JavaScript. Unwritten lessons show on the list as "Being written" and their addresses give 404. Facts checked 11 Nov 2026: MoneySense (3-6 months of expenses, 12 if income is irregular; not CPF), POSB card interest 27.8% a year, IRAS (REITs pay out at least 90% for tax transparency). Lesson 1's demo fall: 27 Mar to 9 Apr 2025, $17,964 to $15,197 (15%), back by 3 Jul 2025. Tests: `tests/test_learn.py`.

Gap check (11 Nov 2026): a 9th lesson, "Spotting investment scams" (lesson 4: check MAS's Financial Institutions Directory before sending anyone money; guaranteed returns and chat-group tips are red flags), because scams are the biggest danger for Singapore beginners. Folded into planned lessons instead of new ones: why invest at all (inflation and compounding) and investing monthly go in "Risk and time" (now lesson 7); Singapore's tax rules (dividends from Singapore companies are tax-free, share gains usually aren't taxed) go in "Dividends" (now lesson 6). Pre-launch legal checks from the same review are in SECURITY.md checks 71-78.

All 9 lessons built (12 Nov 2026). Every "In the demo" box comes from `lessons.facts_for(conn, slug)`: `biggest_dip` (lessons 1, 4, 7), `what_you_own` (2), `money_summary` (3, 5, 6, 7: fees, dividends by stock, total profit, smallest buy, first and last buy), `returns_summary` (4, 8, 9: money-weighted and time-weighted returns vs the STI ETF, stock by stock), `xray_layers` (9: the X-ray's last day split into layers) and `scam_compare` (4: "3% a month" = 42.6% a year, works without the demo). Every box has a sentence for "not loaded yet", and lessons 3 and 6 a separate one for "loaded but no dividends yet". Wording follows the numbers: "an unusually good run" only above 12% a year, "a year" only for a year or more of history, "beat" or "trailed" the market from the real result. Facts checked 12 Nov 2026: CDP vs custodian (own name and direct dividends vs nominee; voting usually indirect; transfer fees), SGX clearing fee 0.0325% and trading access fee 0.0075% plus 9% GST, MAS Financial Institutions Directory and the ScamShield helpline 1799, IRAS one-tier (Singapore dividends tax-exempt; US withholds 30%), SPIVA US year-end 2024 (at least 80% of equity funds trailed their benchmark over 10 years). Where sources disagreed on detail (days from ex-date to payment), lessons point to the company's SGX announcement instead of a number.

"Am I ready to start?" self-check plan (w321, agreed 12 Nov 2026): a page at `/learn/ready`, 8 one-tap questions: emergency fund (months of expenses in cash; 12 months if income is irregular), expensive debt, protection (would a big medical bill or a gap in income be covered), time frame, a goal, what you'd do in a 15% fall (the demo's April 2025 fall), knowing your broker's minimum fee and CDP vs custodian, and checking MAS's directory before paying anyone. The result is a calm "6 of 8 in place" with each item "In place" or "Usually sorted first", one line on why and a link to its lesson. It's a checklist, never a verdict: no "you're ready", no score or grade, and it ends "Only you can decide when to start" (MAS: general education isn't advice). Answers are personal, so nothing is saved: the form is a POST (kept out of the address bar, browser history and server logs), the result is shown once, and nothing goes to the database or the logs. Offered after lesson 9 and at the top of the Learn page. Built 12 Nov 2026: `src/readiness.py` holds the 8 questions, which answers count as "in place", and the one-line reasons; `answers_from` accepts only the listed answers (anything else counts as skipped), and the irregular-income tick box moves the emergency-fund target to "more than 12 months". Route `/learn/ready` (GET and POST, `Cache-Control: no-store`); the "a fall" question quotes the demo's real biggest fall. Tests in `tests/test_ready.py` count every row of every table before and after answering, so "nothing is saved" is checked, not just promised.

Lesson films and frame numbers (12 Nov 2026, from the design skill's review: the Learn pages had nothing from SGXray's world, so they looked like any learning site). Concept: every lesson is read off the demo's real film. Each "In the demo" box is lit faintly from behind (about 5%, like the login lightbox) and, where the lesson has real data, shows a small chart drawn as plain SVG in `_lesson.html` with the login film's 1px line and 22% glow, no animation: the fall (lessons 1, 4, 7, with only the falling part in soft red), a split bar (lesson 2 holdings, lessons 3 and 6 dividends by stock, lesson 9 the X-ray layers) with matching colour keys in the list, or up/down bars per stock against the STI ETF (lesson 8). `lessons.dip_film` keeps the chart inside the stretch with no trades, so a buy's jump is never drawn as the market rising (`test_the_fall_film_never_draws_a_trade_as_a_market_move`). No data, no film. The Learn list numbers lessons 1-9 along a 1px edge, like frames on a strip of film; a read lesson's number is green (he tried "01" and lamp-lit numbers and preferred plain numbers in green). The self-check result is a film on the login's lightbox, labelled "Diagnosis" (patient: your email, or "unidentified" when logged out), without the portfolio chart: `lightbox()` in `_lightbox.html` now takes `chart=False`, `wide=True` and `switch=True`. On the Diagnosis film (only there, not the login) both clips are light switches, always showing the same state: real buttons (keyboard and screen readers work, `aria-pressed`), and clicking it fades the backlight to 4% and back with the login's 450ms fade (`static/js/lightbox.js`). Nothing is saved.

## Automatic daily prices and live pages (w410, 12 Nov 2026)

Why it was needed: prices only changed when someone ran `python src/market.py`, so every page said "Prices as of 6 November" on 12 November, and a portfolio bought on 11 November had no worth and no X-ray (no price on or after its buy date).

- `src/updater.py`: a background thread inside the app checks every 15 minutes (first check 20 seconds after start-up, so missed days are caught up quickly). It runs when the STI ETF's newest close is older than the last trading day (`last_trading_day`: today after 5:45pm Singapore time, else the day before, skipping weekends), and downloads splits, prices and dividends for every held stock, real and practice, plus the STI ETF (`download_all`, the same steps as market.py). No new close yet: it tries again next check, and gives up on that day after 12 tries (public holidays). A crash never stops later checks.
- One at a time: a row in the `jobs` table is a lock taken with one atomic UPDATE, so two server processes (or Flask's debug reloader) can't both run it; a crashed run's lock expires after 20 minutes.
- Off in the tests (they must never reach the internet) and with `SGXRAY_AUTO_PRICES=0`.
- `/prices/latest` returns a version label, newest date / number of prices / their total, e.g. `2026-11-11/1948/38131.0013`. The date alone wasn't enough (found while testing: OCBC already had 11 November while DBS was catching up, and Yahoo sometimes corrects a past close). No personal data, no login, `no-store`.
- `static/js/live.js` on the portfolio, practice and demo pages: asks every 2 minutes while the tab is visible (and straight away when you come back to the tab). When the version changes it fetches the page in the background, rolls the key figures and the holdings' price and worth from the old close to the new one (about a second, eased; instant with reduce motion), then swaps in the new page content and re-runs the chart scripts (not count-up.js, so numbers don't restart from zero), and the "Prices as of" line glows faintly once. It only counts new prices as shown once the page really shows them, retrying 3 times 10 seconds apart if the fetch fails; a backup timer finishes a roll even if the browser pauses animation frames (background tabs).
- "Prices as of" adds "the newer close comes in by itself, usually after about 5:45pm" when the page's prices are behind the last trading day.
- Tested end to end on a scratch copy: the updater downloaded the missed days from Yahoo by itself ("[prices] ... updated"), and an open demo page picked up changed prices and redrew its X-ray without a refresh. The rolling animation itself couldn't be watched (the test browser pane was hidden, which pauses animation frames). Tests: `tests/test_updater.py`. Serious, not gamified.

Practice portfolio plan (w320, agreed 12 Nov 2026): logged-in accounts only. Each account gets a hidden "practice twin" user (can't log in, deleted with the account), so every existing calculation (holdings, profit, dividends, the X-ray, the STI comparison) runs on practice trades unchanged and real and practice trades never mix. Pages `/practice` and `/practice/trades`, marked Practice everywhere. Rules that make it real practice: a pretend trade happens today at the latest closing price (no choosing dates or prices, so no hindsight); you start with $10,000 of pretend cash and can't spend more than you have (sales and dividends go back into the cash); every trade pays a fee, by default a typical one (0.1% with a $10 minimum, plus SGX's 0.0325% + 0.0075% and 9% GST, shown on each trade), and you can type your own broker's rate and minimum instead. "Start over" (with an are-you-sure step) deletes the practice trades. Built 12 Nov 2026: `src/practice.py` (cash, fees, `place`), `db.practice_user` (the twin: email `practice-<owner id>@practice.invalid`, password marker `!practice-no-login`, `practice_of` points to the owner with ON DELETE CASCADE, and its `fee_rate` / `fee_min` hold your own broker's fee), routes `/practice`, `/practice/trades`, `/practice/fees`, `/practice/reset` (all login-only, `no-store`, the twin found from the session's user id). The dashboard has a third mode, "practice", with the pretend cash under the title. A practice trade is dated on the day of the latest close it uses, then goes through the same checks as a real trade (`trades.check`: e.g. you can't sell more than you hold), plus the cash check. Every stock the real trade form lists can be chosen (12 Nov 2026, his request): one with no saved price yet shows "price fetched when you trade", and placing the trade downloads its prices first through the same downloader real trades use (`practice.place(..., download)`), then uses the latest close. "Can't find your stock in the list?" is on the practice page too: it posts to the same `/trades/lookup` with a hidden `then=practice`, and comes back to practice trades (only those two pages are possible, so it can't be used to redirect anywhere else). Fee maths: commission = max(rate x amount, minimum); SGX = 0.04% of the amount; GST = 9% of both; the typical fee is 0.1% with a $10 minimum ($12.21 on $3,000, $13.94 on 100 DBS at $69.72). `.invalid` emails are refused at sign-up so nobody can take a twin's address. Tests: `tests/test_practice.py`.

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

## Audit 2 (9 Nov 2026)

Checked against sources: ES3 distributions 9.1c (Feb 2025), 8.9c (Aug 2025), 8.5c (Feb 2026); CICT 2026 advanced distribution 3.98c (Apr) + 2.04c (Aug); ES3's 2025 price change +22.6% vs the official STI +22.7% (total return 28.6%). The STI comparison is a recognised method: the Long-Nickels Public Market Equivalent (PME), used to benchmark funds; its known weakness (the index side going negative) is the "shortfall" flag. XIRR checked on 300 random cash-flow sets: leftover NPV under 0.00001 every time.

Fixed in audit 2:
- **Split inside the last 12 months doubled the yield and forecast.** Dividends paid per OLD share are now restated per CURRENT share.
- **The STI side was valued on ES3's own newest date.** If ES3's prices stopped, the two sides covered different periods (+10% vs +21%). Both now use your end date, with a stale flag.
- **XIRR crashed on very long spans** (100 years: divide-by-zero from underflow). It now uses exp/log with a capped exponent. Losing everything gives -100% instead of "unknown".
- **Under 30 days, no yearly rate** (+10% in a week would show as +14,000% a year). Dollar profits are still shown.
- **Portfolio yield with a missing price** was quietly too high; it's now unknown.
- **Per-stock comparison was slow** (1.3s for 10 stocks / 400 trades; it recalculated everything per stock). Now 0.16s.
- **Added time-weighted return (TWR)** next to XIRR. Research: indexes and funds report TWR; good trackers show both. TWR = how the picks did ignoring timing; XIRR = what YOU earned, timing included. Demo: TWR +34.17% vs the STI +25.19% a year; XIRR +32.08% vs +25.86%.
- My first TWR counted buys at the start of the day, priced at the previous close. A test buying at the bottom of a dip caught it (0% showed as +50%). Buys now count at the end of the day, except the very first.

Known gaps (unchanged): rights and preferential-offering adjustments in Yahoo data, mergers and ticker changes, floats for money, dividends counted on the ex-date rather than the payment date, ES3 Aug 2026 (9.3c in Yahoo, about 9c in one unofficial source; not confirmed officially).

## Audit 3 (9 Nov 2026): property-based testing

Method: build hundreds of RANDOM portfolios (random trades, prices, holidays, dividends, splits and bonus issues) and check that every calculation agrees with every other. Any disagreement is a bug. These are the invariants:
1. Shares from positions() = an independent share count written separately.
2. Total profit = money out + value + dividends − money in.
3. The daily history's last row = the portfolio snapshot (value, profit, money in).
4. The history's STI line = the STI comparison.
5. XIRR really makes NPV ≈ 0.
6. Per-stock differences add up to the whole-portfolio difference (unless there's a shortfall).
7. Forecast total = the yields table's yearly income.
8. TWR is never NaN when all values are known.
After the fixes, 300 random portfolios passed all 8; 12 run in every `pytest` (tests/test_audit3.py).

Fixed in audit 3:
- **Older trades added later crashed the app.** Prices only downloaded forward. `update_prices` now also fills the gap at the START when the history begins earlier than the saved prices.
- **Sold-out portfolios** were compared up to the last sale but charted up to today. One `valuation_date()` (as_of, else the newest trading day) is now used by everything.
- **STI version after a shortfall:** its TWR and profit line used YOUR sales instead of what it really paid out. It now tracks its own withdrawals.
- **Yahoo missing the price on your trade day** made that day unknown and TWR NaN. The trade price now fills that gap, but only for stocks that HAVE saved prices, so a missing download can't hide.
- **ES3 missing its price on your first trade day** crashed the comparison. It now uses the next price within 7 days.
- **Trades on days with no saved price** were dropped from TWR's cash flows. They now count on the next trading day.
- **TWR's yearly rate** gave "invalid value" for −100%. It's guarded now.
- **Terminal output:** 4 crashes on an empty portfolio or with no dividends, "nan" and "$nan", "$-200.00", and "Prices as of None". All numbers now go through `src/fmt.py`: -$200.00, n/a, +12.34%.
- **Printing a CSV error with Chinese characters crashed the importer** on Windows. Every program now calls `safe_console()`, so such characters print as "?".
- The "STI can't be compared" case (extreme shortfall) is now explained in words instead of "+nan%".

Still known limits (unchanged): Yahoo's rights and preferential-offering adjustments, mergers and ticker changes, floats for money, dividends counted on the ex-date, prices never re-downloaded if Yahoo corrects one, ES3's Aug 2026 amount unconfirmed.

Plan for them (agreed 9 Nov 2026):
- Week 4: re-download the last ~10 trading days each run (plus a weekly full check) and update changed prices; round money to cents when saving and showing it. A full Decimal rewrite isn't worth it: float errors are trillionths of a cent, and pandas would be much slower.
- Stretch: a dividend payment date (estimated from each stock's usual gap after the ex-date, or typed in); ticker changes and delistings/privatisations (as a sale at the offer price); then mergers (old shares → new at the announced ratio, plus cash).
- After launch: undo Yahoo's rights-issue adjustments with a user-entered "price adjustment", or get unadjusted data from a paid provider. A licensed provider would also supply payment dates and corporate actions.

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


## Works well on phones (w307, 12 Nov 2026)

Checked every page at 375px wide (a typical phone) on a scratch copy, logged in and out: nothing spilled off the screen, forms and lessons fit, wide tables scroll sideways inside their own box. Two real problems, both fixed:
- The top bar hid its links on phones, so Learn, Practice, Trades and Account couldn't be reached at all. Now, at 720px and narrower, a "Menu" button opens a panel with every link (logged in: Home, Demo, Learn, Your portfolio, Practice, Trades, Account, Log out; logged out: Home, Demo, Learn, Log in, Create an account). It's the browser's own popover (`popover` / `popovertarget`), so it closes by tapping outside or pressing Esc with no extra script. Rows are 44px tall (a comfortable finger target), and the page you're on has a faint blue bar. Wider screens keep the links in the bar.
- Wide tables kept scrolling the stock's name out of view. On phones the first column is pinned (`position: sticky`), so you always know which row you're reading.
- The tappable words inside sentences are under 24px tall; that's allowed for links inside text (WCAG 2.2 target size has an exception for them), so they stay.
Tests: `tests/test_phone.py`.

## Where your money is (s02, 12 Nov 2026)

A section on every portfolio page (yours, practice, demo), after Holdings: the same worth split by type (shares in companies, REITs, ETFs) and by sector, each as a split bar plus a small table, with its own explanation box. `src/allocation.py` does the maths; `explain.explain_allocation` the words.
- Warnings (his choice, a common beginner rule of thumb): one company over 25% of what you hold, one sector over 50%. ETFs never count as "one company" and count as "Whole market (index fund)" in the sector split, since they already hold many companies. Exactly 25% doesn't warn.
- "Everything is Singapore" is a note in the explanation, not a warning: it's true for everyone on SGXray, and the fix (overseas funds) is outside the app.
- A holding with no price yet is left out and named in the explanation ("Not counted yet: ..."), never a blank.
- The demo shows both warnings: DBS 65%, banks 65%.
- Found on the phone check: the cards wouldn't shrink below their tables' width (a grid item's default `min-width: auto`), which pushed the Menu button off-screen; fixed with `min-width: 0`.
Tests: `tests/test_allocation.py`.

## Insights: fees and yield traps (w304, 12 Nov 2026)

Both checks partly existed (a yield over 7% got a gentle warning; fees only came up in the monthly summary). Now:
- Fees: `explain.fee_summary` adds up every trade's fees (sales included) against what the buys cost. The "Total profit" and Trades boxes say "Fees so far: $60.00 on $15,157.00 of buys, 0.40%". "Watch out" when fees are over 0.5% of everything bought, and names any single buy that lost over 1% to fees ("Your C38U.SI buy on 11 Jun 2024 paid $10.00 in fees on $1,930.00..." only if over 1%). The demo is under both lines, so it gets the fee line with no warnings.
- Yield traps: a yield over 6% together with a price at least 20% below its 52-week high is the classic pattern (the market expecting a dividend cut), so it gets a specific warning with the drop and the high. A high yield on a steady price keeps the gentler "unusually high" note (over 7%). Skipped when a bonus issue or split happened inside the 52 weeks, since those make the price drop without any loss.
Tests: `tests/test_insights_w304.py`.

## Ups and downs (w305, 12 Nov 2026)

`src/risk.py`, a section on every portfolio page (Detailed view): three figures, each with its own explanation buttons (the page rule).
- Biggest fall (drawdown): the deepest drop from a high in the day-by-day growth used for the time-weighted return (`history._growth`), so money added or taken out never counts as a rise or a fall, and dividends count. With its dates, when it climbed back (or "not back yet"), and the STI ETF's biggest fall.
- How bumpy (volatility): the standard deviation of daily growth on days you held something, x the square root of 252 trading days. "Too soon" under 60 trading days. Shown "per year" (not "a year", which on this site is the tappable reason word for yearly-rate returns).
- Below its high: how far it is now under its best point.
- Cross-checked on the demo with a completely separate calculation built straight from value, money in and dividends: biggest fall 14.73% (27 Mar to 9 Apr 2025, back by 6 Jun 2025), bumpiness 13.50% per year; the STI ETF 14.3% and 12.4%. Lesson 1's 15% differs on purpose: it's the portfolio's value alone, without dividends.
- Found by tests: a divide-by-zero when the STI ETF didn't move at all, and the section vanishing with one day of prices (now it says "Too soon").
Tests: `tests/test_risk.py`, each figure against hand or plain-arithmetic answers.

## Monthly plans (w314, 12 Nov 2026)

On the Trades page, "Monthly plans": stock, amount, buy day (1-28), start month, your bank's fee (% and minimum). `src/plans.py` records each month's buy itself, the way Singapore banks' plans work (POSB Invest-Saver, OCBC Blue Chip Investment Plan, checked 12 Nov 2026): on the buy day or the next trading day with a close, at that close; fee = max(rate x amount, minimum), taken first; whole shares only; the leftover cash isn't invested (POSB refunds it). A month with no close on or after its buy day yet waits; each month is recorded once (`trades.plan_month`). New months are added after every daily price update (`updater.download_all` -> `plans.catch_up_all`) and when the Trades page opens. Stop: no more months (it ends at the last month actually bought); past buys stay. Delete: the plan and every buy it recorded (for a plan typed in by mistake), after an are-you-sure page. One plan buy can be changed (to match the bank's statement, which can differ by a few cents) but not deleted on its own, since it would be recorded again. Checked on a scratch copy: a $100 / 15th / 0.82% STI ETF plan since June 2025 recorded 17 months, every one identical to an independent recalculation from the saved prices (342 shares, $1,668.99), none on a weekend. Tests: `tests/test_plans.py`.

## Simple / Detailed (w315, 12 Nov 2026)

A switch under the portfolio title (`static/js/view.js`). Simple: the key figures, the X-ray, Holdings, Where your money is. Detailed adds everything marked `data-detail`: Ups and downs, period returns, each stock vs the STI, yields, dividends by year, the forecast, Sold. Remembered on the device only (localStorage); starts on Detailed so nothing disappears until someone chooses; without JavaScript, everything shows. A link to a Detailed-only section (from a lesson, or within the page) shows Detailed for that visit without changing the saved choice. It survives live.js swapping in new prices.

## In the news (w312, 12 Nov 2026)

`src/news.py`. Headlines from four Singapore newsrooms' public RSS feeds (CNA Business, The Business Times Companies & Markets, The Straits Times Business, The Edge Singapore), fetched every 3 hours by the background updater (`updater.news_once`, its own timer in the `jobs` table). Shown on every portfolio page (Detailed view, "In the news": date, headline, source, the stocks you hold that it mentions; 30 days, newest 8) and as small hollow squares along the top of each stock's price chart, with the headline in the chart's tooltip.
- What's kept and shown: only the headline as published, the source, the date and a link to the full article. No summaries, images or edits, and no ads beside them. Mediacorp (CNA) publishes feed terms asking exactly that (working link to the article, no modifying, no ads); the other three publishers' terms weren't found, so the same rules apply to all, and confirming each publisher's terms is pre-launch task w422.
- Safety: only those four fixed addresses are fetched (no SSRF); 2 MB cap, 10-second time-out; feeds with a DOCTYPE or ENTITY are refused (the "billion laughs" trick); a link must be https on the publisher's own site (a look-alike such as businesstimes.com.sg.evil.example is refused); titles are stripped to plain text and always shown escaped, including inside the chart's data; links open with `rel="noopener noreferrer nofollow"` and no referrer. Headlines are kept 60 days.
- Matching (`news.ALIASES`): each stock's names and short forms (DBS; OCBC; UOB / United Overseas Bank; Singtel; CICT / CapitaLand Integrated; SIA / Singapore Airlines; STI / Straits Times Index for the STI ETFs...). Short forms in capitals only match in capitals and as whole words, so "Asia", "Sia the singer" and "STIX" don't match. A looked-up stock uses its own name without "Limited", "Holdings" and the like. Trial on the live feeds (12 Nov 2026): 9 of 162 headlines matched, every one correctly.

## Chart markers and today vs the STI (w302, 12 Nov 2026)

Buys, sells and dividends were already marked on each stock's price chart; news markers are added (above). "Day's change" now ends with the STI ETF's move between the same two closes ("+0.57% on 11 Nov 2026 · STI ETF +0.75%", checked against the raw closes 5.33 -> 5.37).
- Found in the browser check: the new chart code declared a variable named `last` twice, a syntax error that stopped the whole price-chart script, so every price chart would have broken. Python tests can't see that, so `tests/test_js.py` now runs `node --check` on every script (skipped where Node.js isn't installed).

## Empty screens (w319, 12 Nov 2026)

A portfolio with nothing in it (yours, practice, or the demo before it's loaded) has one faint glowing trace drifting slowly behind the message (40 seconds a loop, opacity 0.3, low under the text), like a film being scanned. Two identical waves side by side moved left by one wave's width, so the loop is seamless (checked: same height at both ends, smooth join). No numbers, axes or labels, hidden from screen readers, still with "reduce motion". Left out on purpose: ticking sample numbers, which on a finance site could be mistaken for real prices. Real data still animates in once, then stays still.