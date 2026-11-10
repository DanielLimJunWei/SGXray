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
- Fonts: Newsreader (headings, like a financial paper), Inter (body), JetBrains Mono (numbers and ASCII, so columns line up).
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
- Log in, sign up and account pages (`templates/_lightbox.html`, `static/js/lightbox.js`): designed with the charles-unslop process (after Charles Liu's "Removing AI slop, day 4: login screen"). Concept: "Logging in is putting your own film on the lightbox: it only lights up once it's yours." The form is a sheet of X-ray film clipped to a backlit panel; the film shows the demo portfolio's X-ray chart, printed from its real monthly numbers. While you type a password the light dims (a privacy cue, like covering the film); on submit it brightens, then the page changes. One primary button, no social logins, nested radii (14px box, 10px inset, 4px film and fields: exact, not soft), one depth cue (the backlight). The film edge is printed in small caps because real film edges are. The film shows a plain trading-screen price line (the demo's value, month by month), not the X-ray layers: the X-ray is what you get after logging in. While you type a password, the desk lamp in the top-right corner switches off too (`html.lamp-off`).
- Ambient colour (all pages, `.ambient` + `static/js/ambient.js`): after Conoid and Doors, the dark isn't one flat colour. Three very soft pools from SGXray's world (screen blue bottom-left, deep indigo right, a navy glow along the floor), under 20% strength, drifting a little as you scroll. They sit behind the 3D chart and every panel (z-index -1), so nothing is covered; the lamp's light now lives only in `.lamp`, so it can be switched off.
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
