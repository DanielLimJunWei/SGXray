"""SGXray web app (Flask).

Flask turns Python functions into web pages: each @app.route says "when someone opens this
address, run this function", and the function fills an HTML template (in templates/) with
numbers from the same src/ modules the command line uses. So the website and the tests
always agree.

Run it on your computer (debug mode reloads when you save a file):

    python -m flask --app app run --debug

then open http://127.0.0.1:5000
"""

import sys
from datetime import date
from pathlib import Path

from flask import Flask, abort, current_app, g, render_template, send_from_directory

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))      # let the app import db, portfolio, ... from src/

import db  # noqa: E402
import fmt  # noqa: E402
from explain import explain_holdings  # noqa: E402
from importer import DEMO_EMAIL  # noqa: E402
from performance import compare  # noqa: E402
from portfolio import positions, summary  # noqa: E402


def create_app(db_path=None):
    """Builds the app. Tests pass their own temporary database; normally it's data/sgxray.db."""
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path

    conn = db.get_connection(db_path)       # make sure the tables exist once, at start-up
    db.init_db(conn)
    conn.close()

    _add_filters(app)
    app.teardown_appcontext(_close_db)
    app.after_request(_security_headers)

    @app.get("/")
    def home():
        return render_template("home.html")

    @app.get("/demo")
    def demo():
        """The sample portfolio: anyone can look, nobody can change it (GET only)."""
        conn = get_db()
        user = db.get_user_by_email(conn, DEMO_EMAIL)
        df = positions(conn, user["id"]) if user else None
        if df is None or df.empty:
            return render_template("dashboard.html", s=None)

        names = {r["ticker"]: r["name"] for r in db.get_instruments(conn)}
        held = df[df["shares"] > 0].sort_values("value", ascending=False)
        holdings = [{**row, "name": names.get(row["ticker"], "")} for row in held.to_dict("records")]
        try:
            vs = compare(conn, user["id"])
        except ValueError:                  # no STI ETF prices saved yet: show n/a, don't crash the page
            vs = None
        return render_template(
            "dashboard.html",
            s=summary(df),
            vs=vs,
            holdings=holdings,
            holdings_ex=explain_holdings(conn, user["id"]),
        )

    @app.get("/design-system/<path:name>")
    def design_system(name):
        """The design preview page, for working on the look. Only in debug mode, never on the live site."""
        if not app.debug:
            abort(404)
        return send_from_directory(ROOT / "design-system", name)

    return app


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

def _security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"        # browsers must trust our file types
    response.headers["X-Frame-Options"] = "DENY"                  # no one can show SGXray inside their own page
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
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

    @app.template_filter("longdate")
    def longdate(iso):
        """'2026-11-07' -> '7 November 2026'."""
        if not iso:
            return "n/a"
        d = date.fromisoformat(str(iso)[:10])
        return f"{d.day} {d:%B %Y}"


app = create_app()
