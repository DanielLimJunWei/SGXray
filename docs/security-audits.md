# SGXray security audits

The full record behind [SECURITY.md](../SECURITY.md): every limit, every audit, and every check with its
evidence (a test, a file or a setting). Every number here is the one in the code (`src/auth.py`, `app.py`).

## The limits, exactly

| What | Limit | Then |
|---|---|---|
| Wrong passwords for one email | **5** within 15 minutes | Log-ins for that email pause: 15 minutes the first time that day, then 30, then 60 (never longer). The right password is refused too while paused. A countdown shows. |
| Wrong passwords from one network address | 20 within 15 minutes (schools and offices share one) | The same pause, for that address |
| Wrong "current password" on Change password or Delete my account | 5 within 15 minutes | Wait 15 minutes |
| New accounts from one network address | 5 an hour | Wait an hour |
| Password-reset emails | 3 an hour per email, 10 an hour per network address | Wait an hour; the reply is the same whether or not the email has an account |
| Reset link | Works once, for 30 minutes | Only a hash of it is stored |
| Stock-code lookups on Yahoo | 20 an hour per person | Wait an hour |
| Logged-in session | 7 days | Log in again. Logging out or changing your password ends it on the server, so a copied cookie stops working |
| One request | 2 MB | Refused (413) |
| Password length | 12 to 128 characters | Refused, with the reason |
| Page views | 120 a minute per person (per network address when logged out); the open demo page 60 a minute | Wait a minute (in-memory count per server process) |
| Saved changes (trades, plans, notes, practice) | 300 an hour per person | Wait an hour |

**Why the log once seemed to say 5 when 10 worked (fixed 25 Nov 2026).** Until 17 Nov the log-in limit really
was 10 per email (the database shows a 12 Nov test with 20 failures across two emails). This page's old check 28
said "5 per 15 minutes", but that line was about the *change-password* page, and it read as if it were the
log-in limit. Since 17 Nov the code says 5, and audit 4 proved it on a running copy: wrong tries 1 to 4 answer
"N tries left", the 5th pauses log-ins, and the right password, upper-case or space-padded versions of the email
and a faked network address are all refused while paused.

## Audits

| Date | Audit | Result |
|---|---|---|
| 10 Nov 2026 | 70-point launch checklist (OWASP ASVS, API Top 10, LLM Top 10) | 7 fixes (checks 1-70) |
| 11 Nov 2026 | Pre-launch checklist and "ways to get sued" (US law + Singapore's PDPA) | 2 fixes, 4 launch tasks (checks 71-79) |
| 12-17 Nov 2026 | Each new feature checked as it was built | Checks 80-86 |
| **25 Nov 2026** | **Audit 4: full audit.** Automated scanners, black-box attacks on a running copy, the "20 pen-test attacks on vibe-coded apps" list, every calculation against outside references, and a lawyer's read | **11 problems fixed, each with a test that fails on the old code (except the double-click guard, checked in a browser, and the speed-up, timed)**; checks 87-100 |
| **25 Nov 2026** | **Audit 4b: second pass.** Every explanation, lesson, glossary entry, template and script re-read line by line; every worked number recalculated; gitleaks over all 93 commits; OWASP ZAP full scans, logged out and logged in | **Wording and logic: 16 fixes. ZAP: 0 real high alerts; inline styles removed, so the CSP no longer allows them; cross-origin isolation headers added**; checks 104-106 |

### Audit 4b, 25 November 2026

**Wording and logic (16 fixes, tests in `test_audit4.py`, `test_explain.py`, `test_ready.py`, `test_web.py`)**
- Facts: yield on cost does not grow with the price; not every SGX-listed company's dividends are tax-free
  (foreign-based ones, e.g. Thai Beverage, may have tax taken off); MoneySense says 3 to 6 months, so
  "about a year" for an irregular income is now SGXray's own suggestion; SGX closes at 5pm (5:45pm is
  SGXray's update); the fees quiz answer is $11.34; "1.23 percentage points", not "1.23% points".
- Logic: a split is no longer called a bonus issue, and a consolidation's price jump is no longer called a drop;
  a bonus issue from before you owned the stock is no longer a permanent "Watch out"; the Risk lesson no longer
  says "hasn't climbed back yet" and then "holding on is what got it back"; the Stocks-vs-market lesson no
  longer praises a "lead" when the portfolio is behind.
- Wording that edged toward advice ("may suit you better", "only sell when...") is now phrased as questions;
  instructions meant for the server's owner ("Run python src/market.py", "Run the price update") are no longer
  shown to visitors; the Detailed-view note no longer promises the removed portfolio news.

**Leaked secrets:** gitleaks (Docker `zricethezav/gitleaks`) over all 93 commits: none.

**OWASP ZAP 2.x full scans** (Docker `ghcr.io/zaproxy/zaproxy:stable`, `zap-full-scan.py`) against a running
copy on a scratch database, first logged out (137 rules passed), then logged in as a throwaway account (138 passed):
| Alert | Verdict |
|---|---|
| SQL injection (High) on `/login`'s `next` | False positive: `next` never reaches the database (`auth.safe_next` only); the page differed because each failed try lowers "tries left". Every query uses `?` placeholders; the one built from text (`PRAGMA table_info`) takes fixed table names from the code |
| CSP allows inline styles (Medium) | FIXED (check 104): the 5 inline `style=""` attributes became classes (the 52-week dot is an SVG `cx` attribute), so `style-src 'self'` |
| Cross-origin headers missing (Low) | FIXED (check 105): `Cross-Origin-Opener-Policy`, `-Resource-Policy` and `-Embedder-Policy` set; everything SGXray loads is its own |
| HTTP only site (Medium) | Local scan only; the live site sends HSTS with `SGXRAY_HTTPS=1` |
| Server version in the `Server` header (Low) | Werkzeug's development server; hide gunicorn's on Render (check 106) |
| "Potential XSS" in `next` and a `class` | False positives: Jinja escapes every value; the `class` was SGXray's own |
| Suspicious comments, cookie slack, cacheable public pages, user-agent fuzzer | Informational: comments are plain explanations, no secrets; private pages are already `no-store` |

### Audit 4, 25 November 2026

**How it was checked**
- **Known-vulnerable libraries:** `pip-audit -r requirements.lock` (all 29 libraries): no known vulnerabilities.
- **Static analysis:** Bandit 1.9.4 over `app.py` and `src/`: 7 notes, all reviewed. The XML ones are covered
  by refusing DTDs and entities (check 83); the redirect one is fixed (check 89); the 3 SQL ones are
  fixed text with `?` placeholders, not user input.
- **Leaked secrets:** detect-secrets over every file, plus a search of the whole Git history for keys,
  tokens, private keys and passwords. Only test passwords and the banned-password list matched, and no
  `.env`, database or key file has ever been committed.
- **Black-box attacks:** 125 attacks from a throwaway script on a running copy of the app, with a scratch
  copy of the database (never the real one). Covered: the log-in limit, two-user data theft (IDOR) on every
  trade, plan, note and practice route, CSRF, 12 cross-site scripting reflections and a stored one,
  12 open-redirect tricks, SQL injection, impossible numbers and dates, 3 MB uploads, session fixation, stolen
  and forged cookies, security headers, path traversal (`/.git`, `/.env`, the database, the secret key),
  TRACE, account enumeration on log-in and "forgot password", template injection, and the new data and
  delete routes. All pass after the fixes below.
- **The "20 pen-test attacks" list** (murphmaxxing.com):
  - Not used by SGXray, so not applicable: HTTP/2 server, bcrypt, SAML, Microsoft login, GraphQL, TOTP, JWT,
    request smuggling, Postgres views, padding oracles, Node prototype pollution and WebSockets.
  - Pass: ReDoS (the email check takes microseconds on crafted input), weak random numbers (secrets
    come from `secrets`; `Math.random` only names a chart element), timing attacks (`hmac.compare_digest`),
    template injection (no template is ever built from user text; `{{7*7}}` stays text) and XXE (DTDs refused).
  - Fixed: spoofed X-Forwarded-For (check 87), cache poisoning via the Host header (never trusted) and Unicode
    email look-alikes (check 90).
- **OWASP ZAP** (an automated scanner for a running site): not run. Docker Desktop wouldn't start on this
  computer, so it's a Week 4 task against the deployed site (check 99).

**What was found and fixed**

| # | Problem | Who could hit it | Fix and test |
|---|---|---|---|
| 87 | Behind the hosting proxy, every visitor would have looked like ONE network address: 20 wrong log-ins by anyone would have locked everyone out, and 5 sign-ups an hour would have been the whole site's limit | Anyone, on the live site | `SGXRAY_PROXIES=1` on Render trusts exactly one proxy hop; a typed-in X-Forwarded-For is ignored. `test_audit4.py` |
| 88 | Learn, the demo and the news weren't marked "don't store" while logged in, so your progress could show to the next person on a shared computer | Shared computers | Every page is `no-store` while logged in. `test_audit4.py` |
| 89 | Fetching an article's summary followed a redirect before checking where it led, even to `http`, `ftp` or the server's own network; a backslash in a link's host passed the publisher check | A compromised publisher feed | Every redirect checked first; plain host names only. `test_audit4.py` |
| 90 | Look-alike letters: the Kelvin sign "K" lower-cases to a plain "k", so `Kate@…` written with it became `kate@…` | Sign-up tricks | Emails must be plain letters. `test_audit4.py` |
| 91 | A double click on "Add trade" saved the trade twice (the holding doubled) | Anyone | `static/js/forms.js`: a form sends once until the next page arrives (checked in a browser: 3 clicks, 1 trade) |
| 92 | The open demo page took 3.3 seconds of server work per view, an easy way to overload the server | Anyone, no log-in | Dividend counting rewritten as one pass (same results on every account and 600 random portfolios): 0.4 s. A page cache for the demo is a Week 4 task |
| 93 | Selling on the same day as a buy that was saved later: the check passed, then the whole portfolio page crashed (500) | The account's owner | The check now adds same-day trades in the same order as the maths (save order; an edit keeps its place). `test_audit4.py` |
| 94 | "Today" came from the server's clock: on a UTC server, a trade made before 8am in Singapore was "in the future" | Everyone, every morning, once hosted | `src/sgtime.py`, Singapore time everywhere. `test_audit4.py` |
| 95 | A trade dated 1900 was accepted (and 126 years of prices requested) | The account's owner | Dates from 1990 on. `test_audit4.py` |
| 96 | A monthly plan in a suspended stock bought every missed month on the same day it reopened | Plan owners | A month's buy must be within a week of its day, or that month is skipped (as banks do). `test_audit4.py` |
| 97 | No way to download or delete your data; no privacy notice or terms (PDPA) | Every user | Account → Download my data (JSON, your data only) and Delete my account (password needed, everything removed, every device logged out); `/privacy` and `/terms`, linked from every page and at sign-up. `test_legal.py` (10 tests) |

**Calculations, against outside references** (all match):
- XIRR (the money-weighted return) gives Microsoft Excel's own documented example, 0.373362535, and matches
  scipy's solver on 486 random cash-flow sets (largest gap 0.00000005%).
- The time-weighted return is exactly 21% on a hand-worked case.
- Average cost, realised profit, a bonus issue's rounding and a same-day dividend match working by hand.
- The practice fees ($11.34 on a $1,000 trade, $76.30 on $50,000) match SGX's published fees and 9% GST.
- On the demo portfolio, volatility and the biggest fall match numpy, the per-stock profits add up exactly to
  the portfolio's, and two separate code paths give the same total profit.
- SGXray shows no Sharpe ratio, so there was none to check.

## Every check

PASS = proven by the evidence named. FIXED = was a problem, now proven fixed. N/A = SGXray doesn't have that
feature. OPEN = still to do, with its task. LIVE = can only be proven on the deployed site (Week 4).

### Secrets and setup
| # | Check | Status | Evidence |
|---|---|---|---|
| 01 | Database credentials | PASS | SQLite file, no credentials; Postgres URL only from Render's secret settings (Week 4) |
| 02 | Public `.env` files | PASS | `.gitignore` has `.env`, `instance/`, `*.db`; history shows none ever committed (audit 4) |
| 03 | Hard-coded secrets | PASS | Secret key from `SGXRAY_SECRET_KEY` or a random `instance/secret_key` |
| 13 | Secrets in Git history | PASS | Searched 10 Nov and again 25 Nov (detect-secrets + history search) |
| 14 | Secrets in browser JavaScript | PASS | `static/js` holds no keys |
| 36 | Source maps, build files | PASS | No build step |
| 10 | Debug tools in production | PASS | `app.debug` is off (`test_errors_are_generic_and_debug_is_off`); the design preview is a 404 unless debugging |
| 12 | Detailed error pages | FIXED | Generic pages for 400/404/405/413/429/500 |

### Log-in and accounts
| # | Check | Status | Evidence |
|---|---|---|---|
| 04 | Password storage | PASS | scrypt with a random salt per password (Werkzeug) |
| 28, 86 | Guessing limits | FIXED | See "The limits, exactly". `test_auth.py` |
| 25 | Sessions end for real | FIXED | Server-side sessions (only hashes stored), ended at log-out, password change, reset and account deletion |
| 47 | Cookie settings | PASS / LIVE | HttpOnly, SameSite=Lax; Secure once `SGXRAY_HTTPS=1` |
| 56 | Who has an account (enumeration) | PASS / mitigated | Log-in and "forgot password" answer identically (checked again in audit 4); sign-up says nothing about "taken" and is limited |
| 24 | Password reset | PASS / LIVE | 256-bit one-time link, hash stored, 30 minutes, every session ended; email settings in Week 4 |
| 30 | Default accounts | PASS | None; the demo and practice twins can't log in |
| 55 | Two-factor on your own accounts | OPEN: you | See "Your to-do" |
| 76 | Bot sign-ups | PARTLY | Rate limit only; email confirmation once email works (w420) |
| 90 | Look-alike Unicode emails | FIXED | Audit 4 |

### What each person can reach
| # | Check | Status | Evidence |
|---|---|---|---|
| 05, 06, 33, 34, 49 | Only your own data | PASS | Every query has the session's user id; another person's id gives 404 (audit 4: 9 routes attacked) |
| 09 | Admin pages | PASS | None |
| 51 | Extra form fields | PASS | Forms read named fields only (`user_id=1` ignored, audit 4) |
| 80 | Practice twin | PASS | Can't log in or reset; reached only through its owner's session |
| 82 | Monthly plans | PASS | `test_someone_elses_plan_is_untouchable` |
| 85 | Notes, undo, corrections | PASS | `test_someone_elses_note_cant_be_edited` and others |

### Input and output
| # | Check | Status | Evidence |
|---|---|---|---|
| 15, 16 | Checks on the server | PASS | Every limit is re-checked by the server; database CHECK rules too |
| 17 | SQL injection | PASS | `?` placeholders everywhere (Bandit's 3 notes reviewed) |
| 19 | Cross-site scripting | PASS | Escaped templates, `textContent` in scripts, CSP with a per-page nonce |
| 20 | CSRF | PASS | A token on every form, compared in constant time; log-out is POST-only |
| 22 | Path traversal | PASS | `/.git`, `/.env`, the database and the secret key all 404 (audit 4) |
| 52, 53 | Shell commands, unsafe loading | PASS | None |
| 57 | Impossible trades | PASS / FIXED | Over-selling, future and weekend dates refused; same-day order (93) and pre-1990 dates (95) fixed |
| 58 | Two requests at once | FIXED | Unique emails, transactions; double clicks (91) |
| 63 | Checks fail closed | PASS | A missing token or forged cookie means "no" |
| 69 | Open redirects | PASS | `auth.safe_next`; 12 tricks tried in audit 4 |
| 100 | Template injection | PASS | `{{7*7}}` in a note is shown as text (audit 4) |

### Outside services
| # | Check | Status | Evidence |
|---|---|---|---|
| 23 | SSRF | PASS / FIXED | Yahoo gets only SGX-shaped codes; news only from 4 fixed feeds; redirects checked (89) |
| 81 | Background price updates | PASS | Yahoo only, listed stocks only, one at a time under a lock |
| 83, 84 | News feeds and Market today | PASS / FIXED | DTDs refused, 2 MB and 600 KB caps, 10-second time-outs, plain-text titles; link hosts tightened (89) |
| 71 | Visitor data sent elsewhere | FIXED | Fonts and every code library are served by SGXray: a visitor's browser contacts no other site unless they open a news article |
| 98 | Outside scripts without a fingerprint | FIXED (25 Nov) | Three.js 0.186.1 and Lenis 1.3.26 copied from their npm packages (sha512 checked against the registry) into `static/vendor/`; each file's sha256 is tested (`test_vendor.py`); the CSP now allows scripts from SGXray only |
| 74 | Licence for price data | OPEN (w418), BLOCKS LAUNCH | Read 25 Nov: Yahoo's terms forbid redistributing its data and automated access, so it can't feed a public site. EODData is personal use only. Marketstack covers SGX (`D05.SI`) and its $9.99 plan says "Commercial Use", but its agreement doesn't say whether showing prices publicly is allowed: get that in writing, and whether SGX needs its own licence |
| 83b | News publishers' terms | OPEN (w422), BLOCKS LAUNCH | Read 25 Nov: SPH (Straits Times, Business Times) forbids showing its content, RSS included, on another site, even by linking or scraping, without written permission, and bans bots; CNA's RSS is personal, non-commercial and may not be passed to third parties; The Edge allows no use without written permission. Ask each in writing, or launch without the News page |
| 104 | Inline styles allowed by the CSP | FIXED (audit 4b) | `style-src 'self'`; no `style=""` or `<style>` in any template or script (`test_audit4.py`) |
| 105 | Cross-origin isolation headers | FIXED (audit 4b) | COOP, CORP and COEP set on every response (`test_audit4.py`) |
| 106 | Server software version shown | FIXED (w403) | gunicorn's `Server` header now just says "SGXray" (`gunicorn.conf.py`) |
| 107 | The live database (w408) | BUILT, LIVE (Week 4) | PostgreSQL via `DATABASE_URL`, kept only in Render's settings (never in code); the provider's URL must include `sslmode=require` so data is encrypted on the way. Same queries as SQLite, all with placeholders (client-side quoting by psycopg); the whole suite passes on PostgreSQL 17. psycopg 3.3.9 pinned; pip-audit clean. The copy script never moves sessions, failed log-ins, reset links or the security log |
| 108 | The container (w403) | BUILT | Python 3.14.7 image pinned by digest; libraries from the lock file; runs as an ordinary user (uid 10001), never root; `.dockerignore` lets in only the code, templates, static files and the demo CSV (no database, secret key, `.env` or Git history: checked, all 404 from the running container); gunicorn with no access log (one-time reset links would be written out); the live site refuses to start without `SGXRAY_SECRET_KEY`; a remote database must use TLS (a local one only with an explicit `sslmode=disable`). gunicorn 26.2.0 pinned; pip-audit clean |
| 109 | Checks on every push (w402) | BUILT | GitHub Actions (`.github/workflows/ci.yml`) runs every test on SQLite and on PostgreSQL 17, pip-audit on `requirements.lock`, and builds the image, starts it on an empty database and checks pages, 404s for private files, the `Server` header, the ordinary user, and the refusal to start without a secret key. Each outside action pinned to a commit; read-only token, no stored credentials, no secrets (`test_container.py`) |
| 110 | Two workers setting up a new database at once | FIXED (w402) | Found by the new container check: on an empty PostgreSQL database one gunicorn worker crashed ("users_id_seq already exists"), and a worker re-running the setup could deadlock with another deleting old rows. The workers now take turns (an advisory lock) and skip the setup once every table and index exists (`test_postgres.py`) |
| 111 | Watchlist (s14): one person's list seen or changed by another | BUILT | Every query has the session's user id in its WHERE; a stock code in the address only ever touches your own rows (another person's watched stock is a 404). Form token on every change, counted in the hourly change limit, 50 stocks at most, notes capped at 280 characters and shown escaped. In the privacy notice, in "Download my data", deleted with the account (`test_watchlist.py`) |
| 112 | "What if" calculator (s12): a public page that can start a download | BUILT | Read-only GET form, open to everyone, saves nothing about the visitor. Every input is checked: the stock must be in SGXray's list, numbers must be finite and in range, the month from 2010 to now; values are shown escaped. The only side effect, fetching a stock's older prices from Yahoo, happens once per stock, only for stocks in the list, only from Yahoo, and at most 10 times an hour per person or network address (over that, the daily update fetches it instead). Counted in the normal page-view limit too (`test_whatif.py`) |
| 113 | Goals (s16): one person's goals seen or changed by another | BUILT | Every query has the session's user id in its WHERE; a goal number in the address that isn't yours is a 404. Form token on every change, counted in the hourly change limit, 10 goals at most, amounts checked (finite, $1 to $100 million) and the month checked (after this one, up to 50 years ahead). In the privacy notice and in "Download my data", deleted with the account (`test_goals.py`) |
| 114 | Monthly check-in (s11): showing another person's month | BUILT | Read-only, logged in only, and only ever works out the logged-in person's own portfolio (no user id comes from the address). The `month` value is only used if it's one of your own months; anything else falls back to the default (`test_checkin.py`) |

### Server and data
| # | Check | Status | Evidence |
|---|---|---|---|
| 46 | Security headers | PASS / LIVE | CSP, frame-ancestors none, X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy, HSTS on HTTPS |
| 87 | Real visitor addresses behind the proxy | FIXED | Audit 4; set `SGXRAY_PROXIES=1` on Render |
| 88 | Private pages kept out of the browser cache | FIXED | Audit 4 |
| 64, 92 | Server load limits | PASS / FIXED / LIVE | 2 MB cap, rate limits, the demo page 3.3 s → 0.4 s; Week 4: a request time-out and a demo cache |
| 35 | Logs never hold secrets | PASS | `test_nothing_secret_is_written_to_the_security_log` |
| 42 | Audit trail | PASS | Sign-ups, log-ins, failures, pauses, log-outs, password changes, trades, plans (stopping too, since audit 4), data downloads, account deletions |
| 37, 38, 62 | Libraries | PASS | 29 pinned (`requirements.lock`); pip-audit clean 25 Nov 2026 |
| 97 | Privacy and deletion (PDPA) | FIXED | Download my data, Delete my account, privacy notice, terms. `test_legal.py` |
| 72 | Privacy notice reviewed | OPEN | Drafted from the code (25 Nov); contact set to sgxray.app@gmail.com (25 Nov; `SGXRAY_CONTACT_EMAIL` can override it); still needs a lawyer's read before launch |
| 75 | Trade marks | OPEN (w419) | "SGX" is Singapore Exchange's; the footer says "not affiliated" and names belong to their owners; ask a lawyer about the name |
| 77 | Advice wording | PASS | Re-read 25 Nov: lessons explain and warn, never recommend; terms say SGXray isn't MAS-licensed advice |
| 43, 44, 48 | Monitoring, backups, encryption | LIVE (Week 4) | Alerts on failed-log-in bursts and errors; daily backups with a tested restore; HTTPS + provider encryption |
| 99 | Automated scan of the live site | LIVE (Week 4) | Run OWASP ZAP against the deployed site; recheck the demo page's speed under real load |
| 101 | Rate limits at the right level (two reels, 25 Nov) | FIXED | Logged out: per network address, plus a lower limit on the open demo; logged in: per person, pages and saved changes (`src/ratelimit.py`, `test_ratelimit.py`) |
| 102 | Polling for nothing | FIXED | Open pages asked for new prices every 2 minutes all day; now they wait until a close is due (about 5:45pm on trading days), and the answer is reused for 30 seconds (`updater.seconds_to_next_close`, `test_updater.py`) |
| 103 | Dead code | FIXED | Vulture scan: 8 functions and constants nothing used (some only by their own tests) removed, including leftovers of the removed portfolio news |

Not applicable now (no such feature): NoSQL (18), file uploads (21: the CSV upload will cap size and never use
the file's name), JWT (26), CORS (27: no CORS headers at all), staging (29), webhooks (31, 59), payments (32),
AI (39, 40, 65-67: the "What is going on?" box will treat news as data and get no tools), dashboards (45),
OAuth (54), CI/CD (11, 60, 61: GitHub's own actions, pinned, read-only token), browser storage (68: only
animation, view and lessons-read choices) and GraphQL/WebSockets (70).

## Your to-do (things only you can do)

1. **Two-factor sign-in on GitHub:** github.com → your photo → Settings → Password and authentication. Save the recovery codes.
2. **Two-factor on your Google account** (where reset emails will go): myaccount.google.com → Security → 2-Step Verification.
3. **Week 4, on Render:** set `SGXRAY_SECRET_KEY`, `SGXRAY_HTTPS=1` and `SGXRAY_PROXIES=1` (the contact email is built in); two-factor on Render and the database host; then recheck checks 43, 44, 46, 47, 48, 92 and 99 on the live site.
4. **Week 4, for "Forgot your password?":** pick an email service with SMTP (Resend, Brevo or Postmark), verify your domain, and set `SGXRAY_BASE_URL`, `SGXRAY_SMTP_HOST`, `SGXRAY_SMTP_USER`, `SGXRAY_SMTP_PASSWORD` and `SGXRAY_MAIL_FROM` in Render's settings (never in code). Then reset your own password once.
5. **Before launch:** a lawyer's read of `/privacy`, `/terms` and the name (checks 72, 75); Yahoo's and the publishers' terms (74, 83b).
