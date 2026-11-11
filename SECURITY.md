# SGXray security

SGXray holds people's portfolios, so security is built in, tested, and written down here.

**Reporting a problem:** please don't open a public issue. Use GitHub's "Report a vulnerability"
(Security tab → Advisories) so it can be fixed before anyone else sees it.

## How it's protected

The full list, with what each protection stops, is in [NOTES.md → Accounts and security](NOTES.md).
In short: salted scrypt password hashes, login/sign-up/password-change rate limits, server-side
sessions that end on logout, CSRF tokens on every form, a strict Content Security Policy, users
only ever reaching their own data, generic error pages, and a security log that never holds secrets.
Every protection has an attack test in `tests/test_auth.py`.

## Security audit: 70-point launch checklist (10 November 2026)

Checked against a 70-point web application security checklist covering secrets, authentication, input handling, sessions, APIs, dependencies, data, infrastructure, CI/CD and AI risks, which draws on the [OWASP Application Security Verification Standard](https://owasp.org/www-project-application-security-verification-standard/), the [OWASP API Security Top 10](https://owasp.org/www-project-api-security/) and the [OWASP Top 10 for LLM Applications](https://genai.owasp.org/llm-top-10/). Rule used: **no PASS without
evidence** (a file, setting or test). FAIL items found in this audit were fixed the same day (marked FIXED).
UNKNOWN = can only be checked on the live site; each has a Week 4 task.

| # | Check | Result | Evidence or plan |
|---|---|---|---|
| 01 | Exposed database credentials | PASS | SQLite file on the server, no credentials. Postgres (Week 4): URL from Render's secret settings only |
| 02 | Public .env files | PASS | `.gitignore` has `.env` and `instance/`; `git log --name-only` shows no env, key or database file ever committed |
| 03 | Hardcoded secrets | PASS | Secret key from `SGXRAY_SECRET_KEY` or a random `instance/secret_key` (`app._secret_key`); history searched for key patterns: none |
| 04 | Weak or missing authentication | PASS | Werkzeug scrypt hashing, `login_required` on `/portfolio`, `/account` and `/account/password` (`test_portfolio_needs_login...`) |
| 05 | Missing server-side authorization | PASS | Every private action checks the session's user on the server; password change re-checks the current password |
| 06 | Cross-user data access | PASS | User id only from the session; `test_portfolio_needs_login_and_shows_only_your_own` (with `?user=` tampering) |
| 07 | Open database permissions | PASS / Week 4 | The database file isn't reachable over the web (Flask only serves `static/`). Week 4: a Postgres role with only the rights SGXray needs |
| 08 | Firebase / Supabase / S3 rules | N/A | Not used |
| 09 | Unprotected admin routes | PASS | No admin routes; the design preview route returns 404 unless debug mode (`test_design_preview_is_hidden...`) |
| 10 | Production debug tools | PASS | Debug only with `--debug` locally; `test_errors_are_generic_and_debug_is_off` checks `app.debug is False` |
| 11 | Build logs leaking secrets | N/A / Week 4 | No CI yet. When added (w402): secrets only as masked CI secrets, never echoed |
| 12 | Verbose production errors | FIXED | Generic pages for 400/404/405/413/429/500 (`templates/error.html`); test raises an error with a "secret" message and checks it never reaches the page |
| 13 | Secrets in Git history | PASS | `git log -p --all` searched for keys, tokens, private keys and password assignments: none |
| 14 | Secrets in frontend JavaScript | PASS | `static/js` holds no keys; nothing secret is sent to the browser |
| 15 | Client-side-only checks | PASS | Form `minlength`/`required` are only hints; the server repeats every check (`auth.password_problem`, `email_problem`) |
| 16 | Missing input validation | PASS | Length caps on every field, email format, password 12-128, 2 MB request cap (`MAX_CONTENT_LENGTH`). Trade forms reuse the importer's checks (`importer.check_fields`), each field is cut to 32 characters first, and quantity, price and fees have upper limits (`test_trades.py`) |
| 17 | SQL injection | PASS | Every query uses `?` placeholders; the one f-string (`PRAGMA table_info`) uses fixed table names from code; `test_sql_injection_in_the_login_form_does_nothing` |
| 18 | NoSQL injection | N/A | No NoSQL database |
| 19 | Cross-site scripting | PASS | Jinja escapes everything; scripts build the page with `textContent`; CSP with a per-page nonce (`test_security_headers_and_a_fresh_nonce...`) |
| 20 | CSRF | PASS | Token in every form, constant-time check, SameSite=Lax, logout POST-only (`test_forms_without_the_token...`, `test_logout_needs_a_post...`) |
| 21 | Insecure file uploads | N/A now | No uploads yet. CSV import in the app (w308) will cap size, accept only CSV text, never save the file or use its name |
| 22 | Path traversal | PASS | The only file route uses `send_from_directory` (safe join) and is debug-only |
| 23 | SSRF | PASS | SGXray never fetches a user-supplied URL. Ticker lookup only sends a code matching `^[A-Z0-9]{1,6}$` (+ `.SI`), only through yfinance to Yahoo, logged in only, 20 lookups an hour each; Yahoo's answer must say SGX and a share or ETF before anything is saved (`test_lookup.py`) |
| 24 | Password-reset flows | PASS (11 Nov 2026) / Week 4 | Built: 256-bit random link, only its SHA-256 hash stored, 30 minutes, works once (marked used in the same transaction as the new password), a new request cancels the old link, the same reply and status whether or not the email exists, 3 emails an hour per address and 10 requests an hour per network address, every session ended on reset, `Referrer-Policy: no-referrer` and the secret moved out of the address bar, link address only from `SGXRAY_BASE_URL` on the live site (no host-header poisoning), nothing secret in logs. All in `tests/test_reset.py`. Small gap: a real account does a few extra milliseconds of database writes, so the reply is not perfectly timing-equal (the email itself is sent in the background). Week 4: set the email service settings and send a real reset |
| 25 | Weak session management | FIXED | Was: logging out only cleared the browser cookie, so a copied cookie still worked for 7 days. Now: server-side `sessions` table (only SHA-256 hashes stored), ended on logout and on password change, 7-day limit (`test_a_copied_cookie_stops_working_after_logout`) |
| 26 | JWTs | N/A | Not used (signed Flask session + server-side session id) |
| 27 | Permissive CORS | PASS | No CORS headers at all: browsers only allow SGXray's own pages to read its responses |
| 28 | Missing rate limits | FIXED | Login already limited; added sign-up (5 an hour per address) and current-password tries on the account page (5 per 15 minutes). Tests for all three |
| 29 | Unprotected staging | N/A / Week 4 | No staging yet. If one is made: login required, no real user data, its own secret key |
| 30 | Default credentials | PASS | No default accounts; the demo account can't be logged into (`test_the_demo_account_cannot_be_logged_into`); the secret key is random per install |
| 31 | Webhook signatures | N/A | No webhooks |
| 32 | Frontend-only payment checks | N/A | No payments |
| 33 | IDOR / BOLA | PASS | Same as 06. Trade view/edit/delete query `WHERE id = ? AND user_id = ?`, so someone else's trade id gives 404, exactly like one that doesn't exist (`test_someone_elses_trade_is_invisible_and_untouchable`) |
| 34 | Trusting user-sent roles or IDs | PASS | Identity only from the server-side session, never from form fields or the URL |
| 35 | Sensitive data in logs | FIXED | `security_log` never stores passwords (`test_nothing_secret...`); added retention: security events 180 days, failed-login counts 1 day, expired sessions removed (`db.prune`, `test_old_security_records_are_deleted`) |
| 36 | Source maps / build artifacts | PASS | No build step; `static/` holds only the site's own CSS and JS |
| 37 | Vulnerable dependencies | FIXED | Added `requirements.txt` with exact versions (and `requirements.lock`, see 62). `pip-audit -r requirements-dev.txt` on 10 Nov 2026 (every direct and indirect dependency): **no known vulnerabilities**. Re-run before each release and in CI (w402) |
| 38 | Malicious packages | PASS / ongoing | 7 well-known direct dependencies, pinned; no install scripts of our own. Review any new one before adding |
| 39 | Prompt injection | N/A now | No AI yet. "What is going on?" (w412) will treat news text as data and enforce limits in code |
| 40 | AI tools bypassing permissions | N/A now | Same: the AI feature will get no tools that touch user data |
| 41 | Excess database privileges | N/A / Week 4 | See 07 |
| 42 | Missing audit logs | PASS | `security_log` records actor, event, time and address for sign-up, login, failures, blocks, logout and password changes. Trade added / edited / deleted are logged too |
| 43 | Security monitoring and alerts | UNKNOWN / Week 4 | Plan: alert on bursts of failed logins and on server errors (Render logs + an uptime check) |
| 44 | Backup and restore | UNKNOWN / Week 4 | Plan: Render Postgres daily backups, and a restore actually tested before launch |
| 45 | Public internal dashboards | N/A | None |
| 46 | Security headers | PASS / verify live | CSP, X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy, HSTS on HTTPS, no-store on private pages. Re-check the deployed responses in Week 4 |
| 47 | Cookie settings | PASS / verify live | HttpOnly and SameSite=Lax tested; Secure is on when `SGXRAY_HTTPS=1`, which the live site must set |
| 48 | Data in transit / at rest | UNKNOWN / Week 4 | HTTPS + HSTS on Render; Postgres at-rest encryption from the provider; passwords are hashed regardless |
| 49 | Tenant isolation | PASS | One user = one scope; every query filters by the session's user id |
| 50 | Over-trusting AI-generated code | PASS / ongoing | 186 tests incl. 24 attack tests; every change reviewed before commit. Also worth running the built-in `/security-review` before launch, and Strix in Week 4 |
| 51 | Mass assignment | PASS | Forms read only named fields (email, password); nothing copies a whole form into the database |
| 52 | Command / OS injection | PASS | No shell commands anywhere in the app (searched for `subprocess`, `os.system`, `eval`, `exec`) |
| 53 | Unsafe deserialization | PASS | No `pickle` or `yaml.load`; the session cookie is signed JSON |
| 54 | OAuth / social login | N/A | Not used |

| 55 | No MFA on privileged accounts | UNKNOWN: your action | Can't be seen from the code (your GitHub token can't read the setting). Turn on two-factor sign-in for **GitHub**, the **Google account** for your email, and later **Render** and any database host. See "Your to-do" below |
| 56 | Account enumeration | PASS (login) / MITIGATED (sign-up) | Login: same words, status and timing whether or not the email exists (`test_wrong_password_and_unknown_email_look_identical`). Sign-up: the reply doesn't say "taken", every valid sign-up is hashed so timing matches, and 5 sign-ups an hour per address stops mass checking. Full fix comes with email verification ("check your inbox" either way) |
| 57 | Business-logic abuse | PASS | The importer refuses impossible trades on the server: selling more than you hold (including after bonus issues), future or weekend dates, zero or negative amounts (`importer._check_row`, `_check_sells`, the importer tests). The trade forms reuse exactly these checks, and also refuse an edit or delete that would leave a later sale with too few shares |
| 58 | Race conditions | FIXED | `users.email` is UNIQUE in the database; two sign-ups for one email at the same instant now give the calm message instead of a crash (`test_two_signups_for_one_email_at_the_same_moment`). Each write runs inside a transaction (`with conn:`) |
| 59 | Webhook replay | N/A | No webhooks |
| 60 | Overpowered CI/CD credentials | N/A now / w402 | No CI yet. When added: the workflow's token limited to `contents: read`, no deploy keys in CI, Render deploys from its own GitHub link |
| 61 | Untrusted build actions or scripts | N/A now / w402 | Only GitHub's own actions (checkout, setup-python), reviewed before use |
| 62 | Unpinned build dependencies | FIXED | `requirements.lock` lists all 29 libraries (direct and indirect) at exact versions, built from a clean environment; the app was checked to run with only those; `pip-audit -r requirements.lock`: no known vulnerabilities. CI actions will be pinned to exact commit IDs |
| 63 | Security checks fail open | PASS | Every check defaults to "no": a missing or wrong form token is refused, an unknown or forged session cookie means logged out, an unsafe `next=` falls back to your portfolio, a database error gives a 500, never access (`test_a_forged_or_broken_cookie_means_logged_out`, `test_forms_without_the_token...`) |
| 64 | Missing resource limits | PASS / Week 4 | 2 MB request cap, 128-character password cap (scrypt is deliberately slow), rate limits, yfinance downloads use their 10-second timeout. Week 4: a request timeout on the live server (gunicorn) and caching the demo page so visitors can't make it recompute every time |
| 65 | AI sensitive-information disclosure | N/A now / w412 | No AI yet. The "What is going on?" box will send only public news and the stock's public prices, never anyone's portfolio |
| 66 | Unsafe use of AI output | N/A now / w412 | Its answer will be shown as plain text (escaped), never used as HTML, SQL, a link target or a command |
| 67 | AI agents with excessive agency | N/A | SGXray's AI will have no tools: it can't trade, delete or spend |
| 68 | Sensitive browser storage | PASS | The only thing in browser storage is the animation on/off choice (`sgxray-motion`); the login cookie is HttpOnly and holds only a random session id |
| 69 | Open redirects | PASS | `auth.safe_next` allows only paths inside SGXray; 4 attack forms tested (`test_login_never_redirects_to_another_site`) |
| 70 | GraphQL / WebSocket / realtime endpoints | N/A | None |

**Totals (70 checks):** 37 PASS (some to re-check on the live site; check 56 passes for login and is mitigated for sign-up until email verification), 7 FIXED in this audit, 22 N/A (features SGXray doesn't have, or doesn't have yet), 4 UNKNOWN (3 need the live site, 1 needs you).

## Your to-do (things only you can do)

1. **Two-factor sign-in on GitHub** (check 55): github.com → your photo → Settings → Password and authentication → Enable two-factor authentication. Use an authenticator app, and save the recovery codes somewhere safe. Your code is only as safe as this account.
2. **Two-factor on your Google account** (the email password resets will go to): myaccount.google.com → Security → 2-Step Verification.
3. **Week 4:** the same for Render and the database host, set `SGXRAY_SECRET_KEY` and `SGXRAY_HTTPS=1`, then re-check checks 43, 44, 46, 47 and 48 on the live site.
4. **Week 4, for "Forgot your password?":** pick an email service with SMTP (Resend, Brevo or Postmark; free tiers are enough), verify your domain with it (so emails don't land in spam), and set `SGXRAY_BASE_URL`, `SGXRAY_SMTP_HOST`, `SGXRAY_SMTP_USER`, `SGXRAY_SMTP_PASSWORD` and `SGXRAY_MAIL_FROM` in Render's settings. Never in code. Then reset your own password on the live site once.
