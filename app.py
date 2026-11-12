"""SGXray web app (Flask).

Flask turns Python functions into web pages: each @app.route says "when someone opens this
address, run this function", and the function fills an HTML template (in templates/) with
numbers from the same src/ modules the command line uses. So the website and the tests
always agree.

Run it on your computer (debug mode reloads when you save a file):

    python -m flask --app app run --debug

then open http://127.0.0.1:5000
"""

import os
import secrets
import sqlite3
import sys
from datetime import date, timedelta
from functools import wraps
from pathlib import Path

import pandas as pd
from flask import (Flask, abort, jsonify, current_app, g, redirect, render_template, request, send_from_directory,
                   session, url_for)

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))      # let the app import db, portfolio, ... from src/

import allocation  # noqa: E402
import auth  # noqa: E402
import db  # noqa: E402
import fmt  # noqa: E402
import glossary  # noqa: E402
from explain import (Explanation, explain_allocation, explain_dividends_received, explain_news, explain_risk, explain_forecast, explain_holdings,  # noqa: E402
                     explain_income_by_year,
                     explain_performance, explain_periods, explain_sold, explain_stock_chart,
                     explain_total_return, explain_trades, explain_two_returns, explain_value_chart, explain_worth,
                     explain_yields)
from history import period_returns, time_weighted, value_history  # noqa: E402
import insights  # noqa: E402
from importer import DEMO_EMAIL  # noqa: E402
from income import by_year, forecast, portfolio_yield, yields  # noqa: E402
import lessons  # noqa: E402
import news  # noqa: E402
import plans  # noqa: E402
import practice  # noqa: E402
import readiness  # noqa: E402
import risk  # noqa: E402
import lookup  # noqa: E402
import mailer  # noqa: E402
from performance import compare, per_stock  # noqa: E402
from portfolio import positions, summary  # noqa: E402
from stocks import stock_history  # noqa: E402
import trades  # noqa: E402
import updater  # noqa: E402


def create_app(db_path=None):
    """Builds the app. Tests pass their own temporary database; normally it's data/sgxray.db."""
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path
    app.config.update(
        SECRET_KEY=_secret_key(app),                 # signs the session cookie so it can't be forged
        SESSION_COOKIE_HTTPONLY=True,                # page scripts can't read the cookie (stops script theft)
        SESSION_COOKIE_SAMESITE="Lax",               # other websites can't send it along with their forms
        SESSION_COOKIE_SECURE=os.environ.get("SGXRAY_HTTPS") == "1",   # HTTPS only, on the live site
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,          # refuse uploads over 2 MB
        MARKET_DOWNLOAD=trades.download_market_data, # tests swap in a fake, so they never use the internet
        TICKER_LOOKUP=lookup.yahoo_info,              # the same for looking up a new SGX code
        SEND_EMAIL=mailer.send,                       # tests swap in a fake inbox
        EMAIL_IN_BACKGROUND=True,                     # so a real account doesn't answer slower than a made-up one
    )

    conn = db.get_connection(db_path)       # make sure the tables exist once, at start-up
    db.init_db(conn)
    db.prune(conn)                          # and delete what's past its keep-by date
    conn.close()

    _add_filters(app)
    app.jinja_env.globals.update(glossary=glossary.TERMS, glossary_entry=glossary.entry,
                                 term_button=glossary.button)   # tap-a-term
    app.teardown_appcontext(_close_db)
    app.before_request(_load_user_and_check_csrf)
    app.after_request(_security_headers)
    app.context_processor(lambda: {"current_user": g.get("user"), "csrf_token": _csrf_token,
                                   "csp_nonce": g.get("csp_nonce", ""), "today": date.today().isoformat(),
                                   "minutes": auth.RESET_MINUTES})

    if updater.enabled():
        updater.start(db_path)          # new closing prices arrive by themselves after about 5:45pm (w410)

    @app.get("/prices/latest")
    def prices_latest():
        """A label that changes whenever new closing prices are saved, e.g. {"version": "2026-11-12/6043"}. Open portfolio pages
        ask this every couple of minutes (static/js/live.js) and update themselves when it changes. It
        carries no personal data, so it needs no login."""
        response = jsonify(version=updater.prices_version(get_db()))
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def home():
        return render_template("home.html")

    @app.get("/demo")
    def demo():
        """The sample portfolio: anyone can look, nobody can change it (GET only)."""
        user = db.get_user_by_email(get_db(), DEMO_EMAIL)
        return _portfolio_page(user["id"] if user else None, mode="demo")

    # ---------- Learn: the "Before you invest" lesson path (w313) ----------
    # Open to everyone, logged in or not. Logged in, finished lessons are saved to your account;
    # logged out, static/js/learn.js remembers them in this browser only.

    @app.get("/learn")
    def learn():
        done = db.lessons_read(get_db(), g.user["id"]) if g.get("user") else set()
        ready = [x for x in lessons.LESSONS if x.ready]
        first_unread = next((x for x in ready if x.slug not in done), None)
        return render_template("learn/index.html", lessons=lessons.LESSONS, done=done,
                               read_count=sum(1 for x in lessons.LESSONS if x.slug in done),
                               first_unread=first_unread)

    @app.get("/learn/<slug>")
    def lesson(slug):
        item = lessons.get(slug) or abort(404)
        conn = get_db()
        facts = lessons.facts_for(conn, item.slug)          # the demo's live numbers for its "In the demo" box
        done = db.lessons_read(conn, g.user["id"]) if g.get("user") else set()
        return render_template(f"learn/{item.slug}.html", lesson=item, total=len(lessons.LESSONS),
                               next=lessons.next_lesson(item), done=item.slug in done, **facts)

    @app.post("/learn/<slug>/done")
    def lesson_done(slug):
        """"Done, next lesson": saved to your account if you're logged in, then on to the next one."""
        item = lessons.get(slug) or abort(404)
        if g.get("user"):
            db.mark_lesson_read(get_db(), g.user["id"], item.slug)
        nxt = lessons.next_lesson(item)
        return redirect(url_for("lesson", slug=nxt.slug) if nxt else url_for("ready"))

    @app.route("/learn/ready", methods=["GET", "POST"])
    def ready():
        """"Am I ready to start?" (w321). The answers are personal, so nothing is saved: they arrive in the
        POST body (never the address, so not in history or server logs), the result is shown once, and they're
        gone. No database write, no security-log event."""
        conn = get_db()
        demo_uid = lessons.demo_user_id(conn)
        dip = lessons.biggest_dip(conn, demo_uid) if demo_uid else None     # the "a fall" question uses the demo's
        fall = "%.0f%%" % (-dip["fall_pct"] * 100) if dip else "15%"
        answers = readiness.answers_from(request.form) if request.method == "POST" else {}
        return render_template("learn/ready.html", questions=readiness.QUESTIONS, fall=fall, dip=dip,
                               result=readiness.check(answers) if request.method == "POST" else None,
                               chosen=answers)

    # ---------- Practice portfolio (w320) ----------
    # Pretend trades at real SGX prices. They belong to the account's hidden "practice twin", found from the
    # logged-in user's id in the session (never from the address), so nobody can reach anyone else's.

    def _twin():
        return db.practice_user(get_db(), g.user["id"])

    @app.get("/practice")
    @login_required
    def practice_page():
        twin = _twin()
        return _portfolio_page(twin["id"], mode="practice", cash=practice.cash(get_db(), twin["id"]),
                               start_cash=practice.START_CASH)

    @app.route("/practice/trades", methods=["GET", "POST"])
    @login_required
    def practice_trades():
        conn, twin = get_db(), _twin()
        problems, values = None, {"side": "BUY"}
        if request.method == "POST":
            tid, problems = practice.place(conn, twin, request.form, current_app.config["MARKET_DOWNLOAD"])
            if not problems:
                db.log_security_event(conn, "practice_trade", g.user["id"], request.remote_addr)
                return redirect(url_for("practice_trades", saved=tid))
            values = {"ticker": request.form.get("ticker", "")[:16], "side": request.form.get("side", "BUY")[:4],
                      "quantity": request.form.get("quantity", "")[:12], "note": request.form.get("note", "")[:300]}
        return _practice_trades_page(conn, twin, values, problems), (422 if problems else 200)

    @app.post("/practice/fees")
    @login_required
    def practice_fees():
        conn, twin = get_db(), _twin()
        if request.form.get("typical") == "1":
            db.set_practice_fees(conn, twin["id"], None, None)
            return redirect(url_for("practice_trades", fees="typical"))
        rate, minimum, problem = practice.fee_problem(request.form.get("rate", ""), request.form.get("minimum", ""))
        if problem:
            return _practice_trades_page(conn, twin, {"side": "BUY"}, None, fee_error=problem), 422
        db.set_practice_fees(conn, twin["id"], rate, minimum)
        return redirect(url_for("practice_trades", fees="saved"))

    @app.route("/practice/reset", methods=["GET", "POST"])
    @login_required
    def practice_reset():
        """GET asks "are you sure?"; only the POST from that page deletes the practice trades."""
        conn, twin = get_db(), _twin()
        if request.method == "GET":
            return render_template("practice_reset.html", count=db.count_trades(conn, twin["id"]))
        db.delete_all_trades(conn, twin["id"])
        db.log_security_event(conn, "practice_reset", g.user["id"], request.remote_addr)
        return redirect(url_for("practice_trades", reset=1))

    def _practice_trades_page(conn, twin, values, problems, fee_error=None, lookup_error=None, lookup_code=None):
        names = {r["ticker"]: r["name"] for r in db.get_instruments(conn)}
        rows = [{**dict(t), "name": names.get(t["ticker"], "")} for t in db.get_trades(conn, twin["id"])]
        rows.reverse()
        rate, minimum, typical = practice.fee_settings(twin)
        prices = {tk: db.latest_close(conn, tk) for tk in names}
        tickers = _tickers(conn)                      # every stock the real trade form has; prices come when you trade
        added = request.args.get("added", "")
        added = {"ticker": added, "name": names[added]} if added in names else None   # only a ticker that's really listed
        if added and request.method == "GET":
            values = {**values, "ticker": added["ticker"]}
        return render_template("practice_trades.html", trades=rows, values=values, problems=problems,
                               tickers=tickers, prices=prices, cash=practice.cash(conn, twin["id"]),
                               start_cash=practice.START_CASH, rate=rate, minimum=minimum, typical=typical,
                               example=practice.fee(1000, rate, minimum), fee_error=fee_error,
                               saved=request.args.get("saved", type=int), reset=request.args.get("reset") == "1",
                               fees_note=request.args.get("fees", ""), trades_ex=explain_trades(rows),
                               added=added, lookup_error=lookup_error, lookup_code=lookup_code)

    @app.get("/portfolio")
    @login_required
    def portfolio():
        """Your own portfolio. Only ever g.user's trades: the id comes from the signed session, never the URL."""
        return _portfolio_page(g.user["id"], mode="own")

    # ---------- Your trades: add, change, delete ----------
    # Every query below has the logged-in user's id in it, taken from the session. A trade id in the
    # address that isn't yours is treated exactly like one that doesn't exist (404), so nobody can
    # see or change someone else's trades by editing the number.

    @app.route("/trades", methods=["GET", "POST"])
    @login_required
    def trades_page():
        conn, uid = get_db(), g.user["id"]
        if request.method == "GET":
            return _trades_page(conn, uid, values={"side": "BUY", "date": date.today().isoformat()})
        values = trades.form_values(request.form)
        trade, problems = trades.check(conn, uid, values)
        if problems:
            return _trades_page(conn, uid, values=values, problems=problems), 422
        tid = db.add_trade(conn, uid, trade["ticker"], trade["trade_date"], trade["side"],
                           trade["quantity"], trade["price"], trade["fees"], trade["note"])
        db.log_security_event(conn, "trade_added", uid, request.remote_addr)
        return redirect(url_for("trades_page", saved=tid, **_market_note(conn, trade)))

    @app.route("/trades/<int:trade_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_trade(trade_id):
        conn, uid = get_db(), g.user["id"]
        old = db.get_trade(conn, uid, trade_id) or abort(404)
        if request.method == "GET":
            return render_template("trade_edit.html", trade=old, values=trades.trade_values(old), tickers=_tickers(conn))
        values = trades.form_values(request.form)
        trade, problems = trades.check(conn, uid, values, replacing=trade_id)
        if problems:
            return render_template("trade_edit.html", trade=old, values=values, tickers=_tickers(conn),
                                   problems=problems), 422
        db.update_trade(conn, uid, trade_id, trade)
        db.log_security_event(conn, "trade_edited", uid, request.remote_addr)
        return redirect(url_for("trades_page", saved=trade_id, **_market_note(conn, trade)))

    @app.route("/trades/<int:trade_id>/delete", methods=["GET", "POST"])
    @login_required
    def delete_trade(trade_id):
        """GET asks "are you sure?"; only the POST from that page deletes. No script needed."""
        conn, uid = get_db(), g.user["id"]
        trade = db.get_trade(conn, uid, trade_id) or abort(404)
        names = {r["ticker"]: r["name"] for r in db.get_instruments(conn)}
        problems = trades.check_delete(conn, uid, trade_id)
        if trade["plan_id"]:                          # deleting it alone would just be recorded again next update
            problems = ["This buy was recorded by your monthly plan, so deleting it on its own would bring it "
                        "back at the next price update. To match your bank's statement, change it instead; to "
                        "end the plan, stop or delete it under Monthly plans."]
        if request.method == "GET" or problems:
            return render_template("trade_delete.html", trade=trade, name=names.get(trade["ticker"], ""),
                                   problems=problems), (422 if problems and request.method == "POST" else 200)
        db.delete_trade(conn, uid, trade_id)
        db.log_security_event(conn, "trade_deleted", uid, request.remote_addr)
        return redirect(url_for("trades_page", deleted=1))

    # ---------- Regular savings plans (w314) ----------

    @app.post("/plans")
    @login_required
    def add_plan():
        conn, uid = get_db(), g.user["id"]
        v, problems = plans.from_form(conn, request.form)
        if problems:
            return _trades_page(conn, uid, values={"side": "BUY", "date": date.today().isoformat()},
                                plan_problems=problems, plan_values=request.form), 422
        needed = trades.needs_market_data(conn, v["ticker"], v["start_month"] + "-01")
        if needed:
            current_app.config["MARKET_DOWNLOAD"](conn, needed)      # its past prices, so past months can be filled in
        pid = plans.add(conn, uid, v)
        added = plans.catch_up(conn, plans.get(conn, uid, pid))
        db.log_security_event(conn, "plan_added", uid, request.remote_addr)
        return redirect(url_for("trades_page", plan_added=added) + "#plans")

    @app.post("/plans/<int:plan_id>/stop")
    @login_required
    def stop_plan(plan_id):
        conn, uid = get_db(), g.user["id"]
        plans.get(conn, uid, plan_id) or abort(404)
        plans.stop(conn, uid, plan_id)
        return redirect(url_for("trades_page", plan_stopped=1) + "#plans")

    @app.route("/plans/<int:plan_id>/delete", methods=["GET", "POST"])
    @login_required
    def delete_plan(plan_id):
        """GET asks "are you sure?"; only the POST from that page deletes the plan and its trades."""
        conn, uid = get_db(), g.user["id"]
        plan = plans.get(conn, uid, plan_id) or abort(404)
        if request.method == "GET":
            summary_ = next(p for p in plans.for_user(conn, uid) if p["id"] == plan_id)
            names = {r["ticker"]: r["name"] for r in db.get_instruments(conn)}
            return render_template("plan_delete.html", plan=summary_, name=names.get(plan["ticker"], ""))
        plans.delete(conn, uid, plan_id)
        db.log_security_event(conn, "plan_deleted", uid, request.remote_addr)
        return redirect(url_for("trades_page", plan_deleted=1) + "#plans")

    @app.post("/trades/lookup")
    @login_required
    def lookup_ticker():
        """Adds any SGX stock, REIT or ETF to the picker, after checking it on Yahoo (w309)."""
        conn, uid = get_db(), g.user["id"]
        typed = request.form.get("code", "")[:16]
        back = "practice_trades" if request.form.get("then") == "practice" else "trades_page"   # only these two
        ticker = lookup.normalise(typed)
        if ticker is None:
            return _lookup_failed(conn, uid, typed, "An SGX code is up to 6 letters and numbers, like C6L or D05.")
        if any(r["ticker"] == ticker for r in db.get_instruments(conn)):
            return redirect(url_for(back, added=ticker))                    # already listed: just pick it
        key = f"lookup:{uid}"
        if auth.limited(conn, key, lookup.LOOKUPS_PER_HOUR, 60):
            return _lookup_failed(conn, uid, typed, "That's a lot of lookups. Try again in an hour.", 429)
        auth.count(conn, key)
        info = current_app.config["TICKER_LOOKUP"](ticker)
        if info is None:
            return _lookup_failed(conn, uid, typed, "Yahoo Finance couldn't be reached just now. Try again in a minute.", 503)
        found = lookup.describe(info)
        if found is None:
            return _lookup_failed(conn, uid, typed, f"We couldn't find {ticker} on SGX. Check the code: "
                                  "it's the short one, like C6L, not the company name.")
        name, type_, sector = found
        db.save_instrument(conn, ticker, name, type_, sector)
        db.log_security_event(conn, "ticker_added", uid, request.remote_addr)
        return redirect(url_for(back, added=ticker))

    def _lookup_failed(conn, uid, typed, message, status=422):
        if request.form.get("then") == "practice":
            return _practice_trades_page(conn, _twin(), {"side": "BUY"}, None, lookup_error=message,
                                         lookup_code=typed), status
        return _trades_page(conn, uid, values={"side": "BUY", "date": date.today().isoformat()},
                            lookup_error=message, lookup_code=typed), status

    def _market_note(conn, trade):
        """Downloads prices first if this trade needs some (a new stock, or an earlier date).
        If the download fails the trade is still saved; the page says prices come with the next update."""
        needed = trades.needs_market_data(conn, trade["ticker"], trade["trade_date"])
        if not needed:
            return {}
        ok = current_app.config["MARKET_DOWNLOAD"](conn, needed)
        if db.get_latest_price_date(conn, trade["ticker"]) is None and trade["trade_date"] > _last_close_day():
            return {"prices": "tonight"}            # bought today: its first close doesn't exist until ~5:30pm
        return {} if ok else {"prices": "later"}

    def _trades_page(conn, uid, values, problems=None, lookup_error=None, lookup_code=None,
                     plan_problems=None, plan_values=None):
        names = {r["ticker"]: r["name"] for r in db.get_instruments(conn)}
        for p in conn.execute("SELECT * FROM plans WHERE user_id = ?", (uid,)).fetchall():
            plans.catch_up(conn, p)                    # any month whose close has arrived since
        rows = [{**dict(t), "name": names.get(t["ticker"], "")} for t in db.get_trades(conn, uid)]
        rows.reverse()                                          # newest first: the one you just added is on top
        saved = request.args.get("saved", type=int)
        added = request.args.get("added", "")
        added = {"ticker": added, "name": names[added]} if added in names else None   # only a ticker that's really listed
        if added and request.method == "GET":
            values = {**values, "ticker": added["ticker"]}      # pick the stock that was just added
        return render_template("trades.html", trades=rows, trades_ex=explain_trades(rows), values=values,
                               tickers=_tickers(conn), problems=problems,
                               saved=saved, deleted=request.args.get("deleted") == "1",
                               prices_later=request.args.get("prices") == "later",
                               prices_tonight=request.args.get("prices") == "tonight", added=added,
                               lookup_error=lookup_error, lookup_code=lookup_code,
                               plans=[{**p, "name": names.get(p["ticker"], "")} for p in plans.for_user(conn, uid)],
                               plan_problems=plan_problems, plan_values=plan_values or {},
                               plan_added=request.args.get("plan_added", type=int),
                               plan_stopped=request.args.get("plan_stopped") == "1",
                               plan_deleted=request.args.get("plan_deleted") == "1",
                               this_month=date.today().strftime("%Y-%m"))

    # ---------- Accounts ----------

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if g.get("user"):
            return redirect(url_for("portfolio"))
        if request.method == "GET":
            return render_template("signup.html")
        conn = get_db()
        if auth.limited(conn, "signup:" + (request.remote_addr or "?"), auth.SIGNUPS_PER_HOUR, 60):
            return render_template("signup.html", error="Too many new accounts from here. Try again in an hour."), 429
        email = request.form.get("email", "").strip().lower()[:254]
        password = request.form.get("password", "")
        problem = auth.email_problem(email) or auth.password_problem(password, email)
        if not problem and request.form.get("password2", "") != password:
            problem = "The two passwords don't match."
        if problem:
            return render_template("signup.html", error=problem, email=email), 422
        auth.count(conn, "signup:" + (request.remote_addr or "?"))
        hashed = auth.hash_password(password)          # always, so an existing email isn't answered faster
        taken = "We couldn't create an account with that email. If it's yours, log in instead."
        if db.get_user_by_email(conn, email):
            # Saying "that email is taken" would confirm who has an account. This calm message doesn't,
            # and the sign-up limit stops anyone checking many emails. (With email sending, the fully
            # private version is "check your inbox" for both cases.)
            return render_template("signup.html", error=taken, email=email), 422
        try:
            uid = db.create_user(conn, email, hashed)
        except sqlite3.IntegrityError:                 # the same email signed up a split second earlier
            return render_template("signup.html", error=taken, email=email), 422
        db.log_security_event(conn, "signup", uid, request.remote_addr)
        _start_session(db.get_user(conn, uid))
        return redirect(url_for("portfolio"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.get("user"):
            return redirect(url_for("portfolio"))
        next_url = auth.safe_next(request.values.get("next"))
        if request.method == "GET":
            return render_template("login.html", next=next_url, reset_done=session.pop("password_reset", False))
        email = request.form.get("email", "").strip().lower()[:254]
        password = request.form.get("password", "")[:auth.MAX_LENGTH]
        conn, ip = get_db(), request.remote_addr
        if auth.too_many_attempts(conn, email, ip):
            db.log_security_event(conn, "login_blocked", None, ip)
            return render_template("login.html", email=email, next=next_url,
                                   error=f"Too many tries. Wait {auth.WINDOW_MINUTES} minutes, then try again."), 429
        user = auth.check_login(conn, email, password)
        if user is None:
            auth.record_failure(conn, email, ip)
            db.log_security_event(conn, "login_failed", None, ip)
            # The same words whether the email exists or the password is wrong.
            return render_template("login.html", email=email, next=next_url,
                                   error="That email and password don't match."), 401
        db.clear_login_attempts(conn, "email:" + email)
        db.log_security_event(conn, "login", user["id"], ip)
        _start_session(user)
        return redirect(next_url)

    @app.post("/logout")
    def logout():
        if g.get("user"):
            db.log_security_event(get_db(), "logout", g.user["id"], request.remote_addr)
        db.end_session(get_db(), session.get("sid"))     # the server forgets it: a copied cookie stops working
        session.clear()
        if request.form.get("then") == "login":          # "Log in as someone else" on the account page.
            return redirect(url_for("login"))            # A fixed choice, never a web address from the form.
        return redirect(url_for("home"))

    # ---------- Forgot your password? ----------
    # You type your email; if it has an account, SGXray emails a one-time link that works for
    # RESET_MINUTES. The page says the same thing either way, so it can't be used to find out who
    # has an account. Opening the link moves its secret into your session and out of the address bar.

    @app.route("/forgot", methods=["GET", "POST"])
    def forgot():
        if g.get("user"):
            return redirect(url_for("account"))
        if request.method == "GET":
            return render_template("forgot.html")
        conn, ip = get_db(), request.remote_addr or "?"
        email = request.form.get("email", "").strip().lower()[:254]
        if auth.email_problem(email):
            return render_template("forgot.html", error=auth.email_problem(email), email=email), 422
        if (auth.limited(conn, "reset-ip:" + ip, auth.RESETS_PER_HOUR_IP, 60)
                or auth.limited(conn, "reset-email:" + email, auth.RESETS_PER_HOUR_EMAIL, 60)):
            # The same for every email, so it reveals nothing about which ones have accounts.
            return render_template("forgot.html", email=email,
                                   error="Too many reset requests. Try again in an hour."), 429
        auth.count(conn, "reset-ip:" + ip)
        auth.count(conn, "reset-email:" + email)
        user = db.get_user_by_email(conn, email)
        if user is not None and not user["password_hash"].startswith("!"):     # not the no-login demo
            base = _site_address()
            if base is None:
                db.log_security_event(conn, "reset_not_sent", user["id"], ip)
            else:
                token = db.create_password_reset(conn, user["id"], auth.RESET_MINUTES)
                db.log_security_event(conn, "reset_requested", user["id"], ip)   # never the link itself
                _email_later(email, "Reset your SGXray password", _reset_email(base + "/reset/" + token))
        return render_template("forgot.html", sent=True, email=email)

    @app.get("/reset/<token>")
    def reset_link(token):
        """The link from the email. Nothing is used up here (some email apps open links to scan them):
        the secret goes into this browser's session, and the address bar is cleaned of it."""
        session["reset_token"] = token[:100]
        return redirect(url_for("reset_password"))

    @app.route("/reset", methods=["GET", "POST"])
    def reset_password():
        conn, token = get_db(), session.get("reset_token")
        user = db.password_reset_user(conn, token) if token else None
        if user is None:
            session.pop("reset_token", None)
            return render_template("reset.html", expired=True), 410
        if request.method == "GET":
            return render_template("reset.html", email=user["email"])
        new = request.form.get("password", "")
        problem = auth.password_problem(new, user["email"])
        if not problem and request.form.get("password2", "") != new:
            problem = "The two passwords don't match."
        if problem:
            return render_template("reset.html", email=user["email"], error=problem), 422
        if not db.use_password_reset(conn, token, user["id"], auth.hash_password(new)):
            session.pop("reset_token", None)
            return render_template("reset.html", expired=True), 410
        db.clear_login_attempts(conn, "email:" + user["email"])
        db.log_security_event(conn, "password_reset", user["id"], request.remote_addr)
        session.clear()                                   # this browser too: log in with the new password
        session["password_reset"] = True
        return redirect(url_for("login"))

    @app.get("/account")
    @login_required
    def account():
        """The overview: your email, when you joined, and the way to change your password.
        Later rows (export my data, delete my account: w411) go in the same list."""
        return render_template("account.html", joined=_singapore_day(g.user["created_at"]),
                               changed=session.pop("password_changed", False))

    @app.route("/account/password", methods=["GET", "POST"])
    @login_required
    def account_password():
        if request.method == "GET":
            return render_template("account_password.html")
        conn = get_db()
        current = request.form.get("current", "")[:auth.MAX_LENGTH]
        new = request.form.get("password", "")
        key = f"pwchange:{g.user['id']}"
        if auth.limited(conn, key, auth.PASSWORD_TRIES, auth.WINDOW_MINUTES):
            return render_template("account_password.html", error=f"Too many tries. Wait {auth.WINDOW_MINUTES} minutes."), 429
        if auth.check_login(conn, g.user["email"], current) is None:
            auth.count(conn, key)
            db.log_security_event(conn, "password_change_failed", g.user["id"], request.remote_addr)
            return render_template("account_password.html", error="Your current password isn't right."), 401
        problem = auth.password_problem(new, g.user["email"])
        if not problem and request.form.get("password2", "") != new:
            problem = "The two new passwords don't match."
        if problem:
            return render_template("account_password.html", error=problem), 422
        db.set_password_hash(conn, g.user["id"], auth.hash_password(new))
        db.log_security_event(conn, "password_changed", g.user["id"], request.remote_addr)
        _start_session(db.get_user(conn, g.user["id"]))                      # a fresh session for this device
        db.end_other_sessions(conn, g.user["id"], session.get("sid"))        # every other device is logged out
        # Back to the overview (post, then redirect: refreshing can't send the form twice). The note is a
        # one-time flag in this device's signed session, so a link can't fake "Password changed".
        session["password_changed"] = True
        return redirect(url_for("account"))

    def _portfolio_page(uid, mode, **extra):
        """extra: anything else the page needs (the practice portfolio passes its pretend cash)."""
        conn = get_db()
        extra.setdefault("prices_version", updater.prices_version(conn))          # for live.js to notice new prices
        extra.setdefault("next_close", updater.last_trading_day().isoformat())  # the close it should have by now
        extra.setdefault("next_update", updater.next_update())                  # "about 5:45pm today"
        df = positions(conn, uid) if uid else None
        if df is None or df.empty:
            return render_template("dashboard.html", s=None, mode=mode, **extra)

        names = {r["ticker"]: r["name"] for r in db.get_instruments(conn)}
        held = df[df["shares"] > 0].sort_values("value", ascending=False)
        holdings = [{**row, "name": names.get(row["ticker"], "")} for row in held.to_dict("records")]
        # The STI comparisons need STI ETF prices; without them they raise ValueError -> None ("n/a").
        vs = _or_none(compare, conn, uid)
        y = yields(conn, uid)
        f = forecast(conn, uid)
        h = _or_none(value_history, conn, uid)
        s = summary(df)
        day = insights.day_change(conn, uid, h) if h is not None else None
        periods = _or_none(period_returns, conn, uid, None, h) if h is not None else None
        sold = _records(pd.DataFrame(insights.sold_out(conn, uid)), names) if insights.sold_out(conn, uid) else []
        w = insights.weights(df)
        for row in holdings:
            row["weight"] = w.get(row["ticker"], float("nan"))
        waiting = _waiting_for_close(conn, uid, s["missing_prices"])
        # Only when every missing price is a stock bought today: then unknown numbers read "pending".
        g.waiting_for_close = bool(waiting) and len(waiting) == len(s["missing_prices"])
        g.no_price = bool(s["missing_prices"]) and not g.waiting_for_close      # then they read "no price yet"
        no_price = {tk: names.get(tk, tk) for tk in s["missing_prices"] if tk not in waiting}
        return render_template(
            "dashboard.html",
            mode=mode,
            s=s,
            waiting=waiting,
            no_price=no_price,
            vs=vs,
            twr=_or_none(time_weighted, conn, uid),
            # Every figure gets a "What does this mean?" box, whatever state it's in (the page rule).
            twr_ex=_or_none(explain_two_returns, conn, uid) or Explanation(
                ["There's nothing to compare with yet: no STI ETF prices are saved. Run the price update."]),
            divs_ex=explain_dividends_received(conn, uid),
            holdings=holdings,
            holdings_ex=explain_holdings(conn, uid),
            why=_why_notes(conn, uid, holdings),
            alloc=(alloc := allocation.split(df, {r["ticker"]: dict(r) for r in db.get_instruments(conn)})),
            alloc_ex=explain_allocation(alloc),
            risk_view=(risk_view := risk.risk(conn, uid, h) if h is not None else None),
            risk_ex=explain_risk(risk_view),
            headlines=(headlines := news.for_tickers(conn, [r["ticker"] for r in holdings])),
            news_ex=explain_news(headlines),
            stocks=_records(_or_none(per_stock, conn, uid), names),
            vs_ex=_or_none(explain_performance, conn, uid),
            yields=_records(y, names),
            total_yield=portfolio_yield(y, df),
            income_12m=y["income_12m"].sum(),
            total_on_cost=_on_cost(y, df),
            bought_after_prices=y.empty and bool((df["shares"] > 0).any()),   # held now, but not at the latest close
            yields_ex=explain_yields(conn, uid),
            forecast=_records(f, names),
            forecast_total=f["total"].sum(),
            forecast_ex=explain_forecast(conn, uid),
            chart=_monthly_chart(h),
            years=_bar_layout(by_year(conn, uid)),
            years_ex=explain_income_by_year(conn, uid),
            stock_charts=_stock_charts(conn, uid, holdings, s["prices_as_of"]),
            day=day, worth_ex=explain_worth(conn, uid, day),
            simple=insights.simple_return(conn, uid), total_ex=explain_total_return(conn, uid),
            periods=periods, periods_ex=explain_periods(periods) if periods else None,
            sold=sold, sold_ex=explain_sold(sold) if sold else None,
            chart_ex=explain_value_chart(conn, uid, h) if h is not None else None,
            **extra,
        )

    # ---------- Errors: a calm, generic page; the details go to the server log only ----------
    messages = {
        400: "Something in that request wasn't right. If you were filling in a form, go back, refresh the page and try again.",
        404: "There's nothing at this address.",
        405: "That page can't be used that way.",
        413: "That file is too big.",
        429: "Too many tries. Please wait a few minutes.",
        500: "Something went wrong on our side. It's been noted; please try again later.",
    }
    for code, text in messages.items():
        app.register_error_handler(code, lambda e, code=code, text=text: (
            render_template("error.html", code=code, message=text), code))

    @app.get("/design-system/<path:name>")
    def design_system(name):
        """The design preview page, for working on the look. Only in debug mode, never on the live site."""
        if not app.debug:
            abort(404)
        return send_from_directory(ROOT / "design-system", name)

    return app


def _last_close_day():
    """The newest day whose SGX closing price is final ('YYYY-MM-DD'): today after ~5:30pm, else yesterday."""
    from market import last_complete_day
    return last_complete_day().isoformat()


def _waiting_for_close(conn, uid, missing):
    """Of the stocks with no price, the ones only bought today: they're waiting for tonight's close,
    not broken. Returns {ticker: name}."""
    if not missing:
        return {}
    last = _last_close_day()
    first = {}
    for t in db.get_trades(conn, uid):
        first.setdefault(t["ticker"], t["trade_date"])        # trades come oldest first
    names = {r["ticker"]: r["name"] for r in db.get_instruments(conn)}
    return {tk: names.get(tk, tk) for tk in missing if first.get(tk, "") > last}


def _why_notes(conn, uid, holdings):
    """Your "why I bought / sold" notes, shown again beside each stock on the portfolio (w317).

    Returns {ticker: {"id", "title", "link", "notes": [trades, oldest first], "now": price or None,
    "held": bool}}. Only stocks with at least one note are in it. "now" is None when there's no saved
    price yet, so the box says "no price yet" instead of a blank.
    """
    prices = {h["ticker"]: h["price"] for h in holdings}
    names = {r["ticker"]: r["name"] for r in db.get_instruments(conn)}
    out = {}
    for t in db.get_trades(conn, uid):
        if not t["note"]:
            continue
        tk = t["ticker"]
        entry = out.setdefault(tk, {"id": "why-" + tk.replace(".", "-"), "notes": [], "held": tk in prices})
        entry["notes"].append(dict(t))
    for tk, entry in out.items():
        only_buys = all(n["side"] == "BUY" for n in entry["notes"])
        entry["link"] = "Why you bought" if only_buys else "Your notes"
        entry["title"] = f"{entry['link']} {names.get(tk, tk)}" if only_buys else f"Your notes on {names.get(tk, tk)}"
        p = prices.get(tk)
        entry["now"] = p if p is not None and p == p else None          # NaN (no price saved) -> None
    return out


def _on_cost(y, positions_df):
    """The whole portfolio's yield on cost: a year's dividends / what you paid for what you hold."""
    held_cost = positions_df.loc[positions_df["shares"] > 0, "cost"].sum()
    return y["income_12m"].sum() / held_cost if len(y) and held_cost else float("nan")


def _tickers(conn):
    """The starter list for the form's stock picker, by name."""
    return sorted(({"ticker": r["ticker"], "name": r["name"], "type": r["type"]} for r in db.get_instruments(conn)),
                  key=lambda r: r["name"].lower())


def _or_none(fn, *args):
    """Runs fn; if it can't (ValueError, e.g. no STI ETF prices yet), the page shows n/a instead of crashing."""
    try:
        return fn(*args)
    except ValueError:
        return None


def _records(df, names):
    """A table as a list of dicts for the template, each with the stock's full name."""
    if df is None:
        return None
    return [{**row, "name": names.get(row["ticker"], "")} for row in df.to_dict("records")]


def _stock_charts(conn, uid, holdings, as_of):
    """One price chart per stock you hold: its data for the page's script, and its explanation."""
    charts = []
    for r in holdings:
        h = stock_history(conn, uid, r["ticker"])
        if h and h["prices"]:
            h["news"] = news.for_chart(conn, r["ticker"], h["prices"][0][0])        # markers along the top
            charts.append({"ticker": r["ticker"], "name": r["name"], "id": "chart-" + r["ticker"].replace(".", "-"),
                           "data": h, "ex": explain_stock_chart(conn, uid, r["ticker"], h),
                           "w52": insights.week52(conn, r["ticker"], as_of) if as_of else None})
    return charts


def _bar_layout(rows, left=64, right=760, top=28, bottom=196):
    """Positions for the dividends-by-year bars, worked out here so the chart is plain SVG (no script needed)."""
    if not rows or not any(r["total"] for r in rows):
        return []
    top_value = max(r["total"] for r in rows)
    slot = (right - left) / len(rows)
    width = min(120, slot * 0.5)
    out = []
    for i, r in enumerate(rows):
        h = (r["total"] / top_value) * (bottom - top) if top_value else 0
        x = left + slot * i + (slot - width) / 2
        out.append({**r, "x": round(x, 1), "w": round(width, 1), "y": round(bottom - h, 1), "h": round(h, 1),
                    "cx": round(x + width / 2, 1), "base": bottom})
    return out


def _monthly_chart(h):
    """The X-ray chart's data: the last trading day of each month, as plain numbers for the page's script.

    Layers stack from the bottom: your money, then price gains (worth - money in), then dividends.
    A month with an unknown value (a held stock had no price) is left out rather than drawn as a dip.
    """
    if h is None or h.empty:
        return []
    h = h.dropna(subset=["value"])
    months = h.groupby(h.index.to_period("M")).tail(1)
    return [{
        "date": day.strftime("%Y-%m-%d"),
        "label": day.strftime("%b %y"),
        "money": round(float(r.net_invested), 2),
        "gains": round(float(r.value - r.net_invested), 2),
        "divs": round(float(r.dividends), 2),
        "sti": round(float(r.sti_value + r.sti_dividends), 2) if r.sti_value == r.sti_value else None,
    } for day, r in months.iterrows()]


# ---------- Accounts: secret key, sessions, form protection ----------

def _secret_key(app):
    """The key that signs session cookies. On the live site it comes from the SGXRAY_SECRET_KEY setting.
    On your computer it's made once, at random, and kept in instance/secret_key (which Git ignores),
    so it's never in the code or on GitHub."""
    key = os.environ.get("SGXRAY_SECRET_KEY")
    if key:
        return key
    path = Path(app.instance_path) / "secret_key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip()


def _start_session(user):
    """A brand-new session for this user. The old one is thrown away (so a session id someone planted
    before you logged in is useless), and the new one is recorded on the server, so logging out or
    changing your password can really end it."""
    conn = get_db()
    db.end_session(conn, session.get("sid"))
    session.clear()
    session.permanent = True
    session["sid"] = db.create_session(conn, user["id"])
    session["csrf"] = auth.new_csrf_token()


def _csrf_token():
    if "csrf" not in session:
        session["csrf"] = auth.new_csrf_token()
    return session["csrf"]


def _load_user_and_check_csrf():
    g.csp_nonce = secrets.token_urlsafe(16)
    g.user = None
    if session.get("sid"):
        g.user = db.session_user(get_db(), session["sid"])
        if g.user is None:
            session.clear()                            # logged out, expired, or ended by a password change
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if not auth.csrf_ok(session.get("csrf"), request.form.get("csrf")):
            abort(400, "This form has expired. Go back, refresh the page and try again.")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


# ---------- Database: one connection per page view, closed afterwards ----------

def get_db():
    if "conn" not in g:
        g.conn = db.get_connection(current_app.config["DB_PATH"])
    return g.conn


def _close_db(_error=None):
    conn = g.pop("conn", None)
    if conn is not None:
        conn.close()


# ---------- Safety headers on every response ----------

CDN = "https://cdn.jsdelivr.net"


def _security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"        # browsers must trust our file types
    response.headers["X-Frame-Options"] = "DENY"                  # no one can show SGXray inside their own page
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    # Content Security Policy: the browser only runs scripts from SGXray itself, the one code CDN it uses,
    # or an inline script carrying this page's random nonce. An injected <script> has no nonce, so it won't run.
    nonce = g.get("csp_nonce", "")
    response.headers["Content-Security-Policy"] = "; ".join([
        "default-src 'self'",
        f"script-src 'self' {CDN} 'nonce-{nonce}'",
        f"style-src 'self' 'unsafe-inline' {CDN}",
        "font-src 'self'",                        # fonts are served by SGXray itself: no visitor data goes to Google
        "img-src 'self' data: blob:",
        f"connect-src 'self' {CDN}",
        "object-src 'none'", "base-uri 'self'", "form-action 'self'", "frame-ancestors 'none'",
    ])
    if os.environ.get("SGXRAY_HTTPS") == "1":                    # the live site: always HTTPS from now on
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.endpoint in ("reset_link", "reset_password", "forgot"):
        response.headers["Referrer-Policy"] = "no-referrer"       # the reset link's secret is never passed on
    if request.endpoint in ("login", "signup", "account", "account_password", "forgot", "reset_link",
                            "reset_password", "portfolio", "trades_page", "edit_trade", "delete_trade", "lookup_ticker",
                            "ready", "practice_page", "practice_trades", "practice_fees", "practice_reset"):
        response.headers["Cache-Control"] = "no-store"            # private pages aren't kept in the browser cache
    return response


def _site_address():
    """SGXray's own address for links in emails. On the live site it must come from SGXRAY_BASE_URL:
    building it from the visitor's request would let an attacker send a reset email whose link
    points at THEIR site (host-header poisoning). On your own computer, the address you're using."""
    base = os.environ.get("SGXRAY_BASE_URL", "").rstrip("/")
    if base:
        return base
    return None if mailer.live() else request.host_url.rstrip("/")


def _email_later(to, subject, text):
    """Sends in the background, so the page answers just as fast whether or not an email went out."""
    send = current_app.config["SEND_EMAIL"]
    if current_app.config["EMAIL_IN_BACKGROUND"]:
        import threading
        threading.Thread(target=send, args=(to, subject, text), daemon=True).start()
    else:
        send(to, subject, text)


def _reset_email(link):
    return (f"Someone (hopefully you) asked to reset the password for your SGXray account.\n\n"
            f"To choose a new password, open this link within {auth.RESET_MINUTES} minutes. It works once:\n\n"
            f"{link}\n\n"
            f"If it wasn't you, ignore this email: your password stays the same.\n\n"
            f"SGXray")


def _singapore_day(stamp):
    """'2026-11-10 17:30:00' (UTC, as SQLite saves it) -> '2026-11-11', the date in Singapore (UTC+8,
    no daylight saving), so someone who joined at 1am Singapore time sees the right day."""
    from datetime import datetime
    try:
        return (datetime.fromisoformat(str(stamp)[:19]) + timedelta(hours=8)).date().isoformat()
    except ValueError:
        return str(stamp)[:10]


# ---------- Template filters: how numbers look, from fmt.py so every screen agrees ----------

def _gap_word():
    """What an unknown number says instead of "n/a" (the page rule): "pending" while every missing
    price is a stock bought today, "no price yet" when a price is missing for any other reason.
    Both are tap-a-terms. None when the page has no missing price (then the formatter decides)."""
    if g.get("waiting_for_close"):
        return glossary.button("pending", "pending")
    if g.get("no_price"):
        return glossary.button("no-price", "no price yet")
    return None


def _pending_or(formatter):
    """Numbers that need a missing price say why ("pending" / "no price yet"), so the page reads as
    waiting, not broken."""
    def show(x, *args, **kwargs):
        if fmt.missing(x) and _gap_word():
            return _gap_word()
        return formatter(x, *args, **kwargs)
    return show


def _add_filters(app):
    app.add_template_filter(_pending_or(fmt.money), "money")      # {{ x|money }}, {{ x|money(signed=True) }}
    app.add_template_filter(_pending_or(fmt.pct), "pct")
    app.add_template_filter(_pending_or(fmt.num), "num")

    @app.template_filter("trend")
    def trend(x):
        """CSS class for colour: up / down / '' (never colour alone: the arrow filter adds a symbol)."""
        if fmt.missing(x) or round(x, 2) == 0:
            return ""
        return "up" if x > 0 else "down"

    @app.template_filter("arrow")
    def arrow(x):
        if fmt.missing(x) or round(x, 2) == 0:
            return ""
        return "▲" if x > 0 else "▼"

    @app.template_filter("rawnum")
    def rawnum(x):
        """A plain number for data attributes; empty when unknown, so a page never shows 'nan'."""
        return "" if fmt.missing(x) else repr(float(x))

    @app.template_filter("span")
    def span(days):
        """380 -> '1 year', 120 -> '4 months', 20 -> '20 days': how long, in words."""
        from explain import _span
        return _span(int(days))

    @app.template_filter("pct1")
    def pct1(x):
        """+75.7% (one decimal, for short labels) / n/a."""
        if fmt.missing(x):
            return _gap_word() or "n/a"
        return f"{x:+.1%}"

    @app.template_filter("shortdate")
    def shortdate(iso):
        """'2026-11-06' -> '6 Nov 2026'."""
        if not iso:
            return "n/a"
        d = date.fromisoformat(str(iso)[:10])
        return f"{d.day} {d:%b %Y}"

    @app.template_filter("longdate")
    def longdate(iso):
        """'2026-11-07' -> '7 November 2026'."""
        if not iso:
            return "n/a"
        d = date.fromisoformat(str(iso)[:10])
        return f"{d.day} {d:%B %Y}"


app = create_app()
