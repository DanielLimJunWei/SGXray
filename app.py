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
import sys
from datetime import date, timedelta
from functools import wraps
from pathlib import Path

import pandas as pd
from flask import (Flask, abort, current_app, g, redirect, render_template, request, send_from_directory,
                   session, url_for)

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))      # let the app import db, portfolio, ... from src/

import auth  # noqa: E402
import db  # noqa: E402
import fmt  # noqa: E402
import glossary  # noqa: E402
from explain import (explain_forecast, explain_holdings, explain_income_by_year,  # noqa: E402
                     explain_performance, explain_periods, explain_sold, explain_stock_chart,
                     explain_total_return, explain_two_returns, explain_value_chart, explain_worth, explain_yields)
from history import period_returns, time_weighted, value_history  # noqa: E402
import insights  # noqa: E402
from importer import DEMO_EMAIL  # noqa: E402
from income import by_year, forecast, portfolio_yield, yields  # noqa: E402
from performance import compare, per_stock  # noqa: E402
from portfolio import positions, summary  # noqa: E402
from stocks import stock_history  # noqa: E402


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
    )

    conn = db.get_connection(db_path)       # make sure the tables exist once, at start-up
    db.init_db(conn)
    db.prune(conn)                          # and delete what's past its keep-by date
    conn.close()

    _add_filters(app)
    app.jinja_env.globals.update(glossary=glossary.TERMS, glossary_entry=glossary.entry)   # tap-a-term
    app.teardown_appcontext(_close_db)
    app.before_request(_load_user_and_check_csrf)
    app.after_request(_security_headers)
    app.context_processor(lambda: {"current_user": g.get("user"), "csrf_token": _csrf_token,
                                   "csp_nonce": g.get("csp_nonce", "")})

    @app.get("/")
    def home():
        return render_template("home.html")

    @app.get("/demo")
    def demo():
        """The sample portfolio: anyone can look, nobody can change it (GET only)."""
        user = db.get_user_by_email(get_db(), DEMO_EMAIL)
        return _portfolio_page(user["id"] if user else None, mode="demo")

    @app.get("/portfolio")
    @login_required
    def portfolio():
        """Your own portfolio. Only ever g.user's trades: the id comes from the signed session, never the URL."""
        return _portfolio_page(g.user["id"], mode="own")

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
        if not problem and db.get_user_by_email(conn, email):
            # Saying "that email is taken" would tell anyone who has an account. Instead, a calm message
            # that doesn't confirm either way. (With email sending, this would say "check your inbox".)
            problem = "We couldn't create an account with that email. If it's yours, log in instead."
        if problem:
            return render_template("signup.html", error=problem, email=email), 422
        auth.count(conn, "signup:" + (request.remote_addr or "?"))
        uid = db.create_user(conn, email, auth.hash_password(password))
        db.log_security_event(conn, "signup", uid, request.remote_addr)
        _start_session(db.get_user(conn, uid))
        return redirect(url_for("portfolio"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.get("user"):
            return redirect(url_for("portfolio"))
        next_url = auth.safe_next(request.values.get("next"))
        if request.method == "GET":
            return render_template("login.html", next=next_url)
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
        return redirect(url_for("home"))

    @app.route("/account", methods=["GET", "POST"])
    @login_required
    def account():
        if request.method == "GET":
            return render_template("account.html")
        conn = get_db()
        current = request.form.get("current", "")[:auth.MAX_LENGTH]
        new = request.form.get("password", "")
        key = f"pwchange:{g.user['id']}"
        if auth.limited(conn, key, auth.PASSWORD_TRIES, auth.WINDOW_MINUTES):
            return render_template("account.html", error=f"Too many tries. Wait {auth.WINDOW_MINUTES} minutes."), 429
        if auth.check_login(conn, g.user["email"], current) is None:
            auth.count(conn, key)
            db.log_security_event(conn, "password_change_failed", g.user["id"], request.remote_addr)
            return render_template("account.html", error="Your current password isn't right."), 401
        problem = auth.password_problem(new, g.user["email"])
        if not problem and request.form.get("password2", "") != new:
            problem = "The two new passwords don't match."
        if problem:
            return render_template("account.html", error=problem), 422
        db.set_password_hash(conn, g.user["id"], auth.hash_password(new))
        db.log_security_event(conn, "password_changed", g.user["id"], request.remote_addr)
        _start_session(db.get_user(conn, g.user["id"]))                      # a fresh session for this device
        db.end_other_sessions(conn, g.user["id"], session.get("sid"))        # every other device is logged out
        return render_template("account.html", done="Password changed. Any other devices have been logged out.")

    def _portfolio_page(uid, mode):
        conn = get_db()
        df = positions(conn, uid) if uid else None
        if df is None or df.empty:
            return render_template("dashboard.html", s=None, mode=mode)

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
        return render_template(
            "dashboard.html",
            mode=mode,
            s=s,
            vs=vs,
            twr=_or_none(time_weighted, conn, uid),
            twr_ex=_or_none(explain_two_returns, conn, uid),
            holdings=holdings,
            holdings_ex=explain_holdings(conn, uid),
            stocks=_records(_or_none(per_stock, conn, uid), names),
            vs_ex=_or_none(explain_performance, conn, uid),
            yields=_records(y, names),
            total_yield=portfolio_yield(y, df),
            income_12m=y["income_12m"].sum(),
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
        f"style-src 'self' 'unsafe-inline' https://fonts.googleapis.com {CDN}",
        "font-src https://fonts.gstatic.com",
        "img-src 'self' data: blob:",
        f"connect-src 'self' {CDN}",
        "object-src 'none'", "base-uri 'self'", "form-action 'self'", "frame-ancestors 'none'",
    ])
    if os.environ.get("SGXRAY_HTTPS") == "1":                    # the live site: always HTTPS from now on
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.endpoint in ("login", "signup", "account", "portfolio"):
        response.headers["Cache-Control"] = "no-store"            # private pages aren't kept in the browser cache
    return response


# ---------- Template filters: how numbers look, from fmt.py so every screen agrees ----------

def _add_filters(app):
    app.add_template_filter(fmt.money, "money")                   # {{ x|money }}, {{ x|money(signed=True) }}
    app.add_template_filter(fmt.pct, "pct")
    app.add_template_filter(fmt.num, "num")

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

    @app.template_filter("pct1")
    def pct1(x):
        """+75.7% (one decimal, for short labels) / n/a."""
        return "n/a" if fmt.missing(x) else f"{x:+.1%}"

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
