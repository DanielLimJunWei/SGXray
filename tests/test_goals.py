"""Goals (s16): your own goals only, progress from the same numbers as the dashboard, every value a number or a
reason in words. Expected numbers are worked out by hand in the comments."""

import re
from datetime import date

import pytest

import db
import goals
from test_trades import app, db_path, downloads, signed_up, token  # noqa: F401  (fixtures)

TODAY = date(2026, 11, 26)


@pytest.fixture
def ann(conn):
    uid = db.create_user(conn, "g@example.com", "x")
    db.add_trade(conn, uid, "D05.SI", "2025-01-02", "BUY", 100, 30.0, 10.0)
    db.add_trade(conn, uid, "D05.SI", "2026-03-02", "SELL", 20, 35.0, 5.0)
    db.save_prices(conn, "D05.SI", [("2025-01-02", 30.0), ("2026-03-02", 35.0), ("2026-11-20", 40.0)])
    db.save_dividends(conn, "D05.SI", [("2025-12-01", 0.60)])           # dividends never count as money in
    return uid


def test_progress_by_hand(conn, ann):
    db.add_goal(conn, ann, "money_in", 10_000, "2027-12", "2026-11-01")
    db.add_goal(conn, ann, "worth", 10_000, "2030-12", "2026-11-01")
    db.add_goal(conn, ann, "worth", 3_000, None, "2026-11-01")
    put_in, worth, small = goals.progress(conn, ann, TODAY)
    # Money in: 100 x $30 + $10 fee = $3,010 in; 20 x $35 - $5 fee = $695 back. $3,010 - $695 = $2,315.
    assert put_in["now"] == pytest.approx(2315) and put_in["share"] == pytest.approx(0.2315)
    # $7,685 to go over 13 months (Nov 2026 -> Dec 2027) = $591.15 a month.
    assert put_in["months_left"] == 13 and put_in["per_month"] == pytest.approx(7685 / 13)
    # Worth: 80 x $40 = $3,200; $6,800 to go over 49 months (Nov 2026 -> Dec 2030).
    assert worth["now"] == 3200 and worth["months_left"] == 49
    assert worth["per_month"] == pytest.approx(6800 / 49)
    assert small["reached"] and small["gap"] == 0 and small["per_month"] is None


def test_money_in_matches_the_xray_charts_own_money(conn, ann):
    from history import value_history
    db.save_prices(conn, "ES3.SI", [("2025-01-02", 3.5), ("2026-03-02", 3.8), ("2026-11-20", 4.0)])   # the chart's STI line
    assert goals.money_in(conn, ann) == pytest.approx(value_history(conn, ann)["net_invested"].iloc[-1])


def test_money_in_never_goes_below_nothing(conn, user_id):
    db.save_prices(conn, "D05.SI", [("2025-01-02", 30.0), ("2026-01-02", 60.0)])
    db.add_trade(conn, user_id, "D05.SI", "2025-01-02", "BUY", 100, 30.0)
    db.add_trade(conn, user_id, "D05.SI", "2026-01-02", "SELL", 100, 60.0)     # $6,000 back for $3,000 in
    assert goals.money_in(conn, user_id) == 0.0


def test_a_missing_price_is_a_reason_not_a_blank(conn, ann):
    db.add_trade(conn, ann, "O39.SI", "2026-11-25", "BUY", 100, 15.0)    # no closing price for it yet
    db.add_goal(conn, ann, "worth", 10_000, None, "2026-11-01")
    db.add_goal(conn, ann, "money_in", 5_000, None, "2026-11-01")
    worth, put_in = goals.progress(conn, ann, TODAY)
    assert worth["now"] is None and worth["reason"] == "no-price"
    assert put_in["now"] == pytest.approx(3815)                              # money in needs no price: 2,315 + 1,500


def test_the_form_refuses_what_it_cant_use():
    assert goals.from_form({"kind": "cash", "target": "x"}, TODAY)[1] == [
        "Choose what the goal is: money you put in, or what your portfolio is worth.",
        "The goal must be an amount in dollars, like 300 or 50,000."]
    assert goals.from_form({"kind": "money_in", "target": "nan"}, TODAY)[1]
    assert goals.from_form({"kind": "dividends", "target": "300"}, TODAY)[1]                       # no longer offered
    assert goals.from_form({"kind": "worth", "target": "5000", "by_month": "2026-11"}, TODAY)[1]   # this month
    assert goals.from_form({"kind": "worth", "target": "5000", "by_month": "2080-01"}, TODAY)[1]   # over 50 years
    values, problems = goals.from_form({"kind": "worth", "target": "$50,000", "by_month": "2030-12"}, TODAY)
    assert problems == [] and values == {"kind": "worth", "target": 50000.0, "by_month": "2030-12"}
    values, problems = goals.from_form({"kind": "money_in", "target": "10000", "by_month": "2027-12"}, TODAY)
    assert problems == [] and values["by_month"] == "2027-12"                 # money-in goals can have a date too


def test_an_older_database_swaps_dividend_goals_for_money_in_once(conn, user_id):
    """Goals made before 26 Nov 2026 allowed 'dividends', not 'money_in'. Starting the app swaps that once, keeping
    every worth goal (and its id) and removing dividend goals, on SQLite and PostgreSQL alike."""
    dialect = "postgres" if db.is_postgres(conn) else "sqlite"
    create = re.search(r"CREATE TABLE IF NOT EXISTS goals \(.*?\n\);", db.schema_sql(dialect), re.S).group(0)
    with conn:
        conn.execute("DROP TABLE goals")
        conn.execute(create.replace("('money_in', 'worth')", "('dividends', 'worth')"))     # the table as it was
    db.add_goal(conn, user_id, "worth", 5000, "2030-12", "2026-11-01")
    db.add_goal(conn, user_id, "dividends", 300, None, "2026-11-02")
    [kept] = [g["id"] for g in db.get_goals(conn, user_id) if g["kind"] == "worth"]
    db.init_db(conn)
    db.init_db(conn)                                                          # a second start changes nothing more
    assert [tuple(g)[:4] for g in db.get_goals(conn, user_id)] == [(kept, "worth", 5000, "2030-12")]
    db.add_goal(conn, user_id, "money_in", 10_000, None, "2026-11-26")
    with pytest.raises(Exception):
        db.add_goal(conn, user_id, "dividends", 300, None, "2026-11-26")
    assert [g["kind"] for g in db.get_goals(conn, user_id)] == ["worth", "money_in"]


# ---------- The pages ----------

def test_adding_seeing_and_removing_a_goal(app, db_path):
    c = signed_up(app)
    r = c.post("/goals", data={"csrf": token(c, "/goals"), "kind": "money_in", "target": "10,000",
                               "by_month": "2040-01"})
    assert r.status_code == 302 and "done=added" in r.headers["Location"]
    html = c.get("/goals").get_data(as_text=True)
    assert "Put in $10,000.00 by" in html and "put in so far" in html
    assert "if prices didn" not in html                                       # money in doesn't depend on prices
    conn = db.get_connection(db_path)
    uid = db.get_user_by_email(conn, "ann@example.com")["id"]
    [g] = db.get_goals(conn, uid)
    r = c.post(f"/goals/{g['id']}/remove", data={"csrf": token(c, "/goals")})
    assert "done=removed" in r.headers["Location"] and db.get_goals(conn, uid) == []
    conn.close()


def test_nobody_else_can_remove_your_goal(app, db_path):
    ann = signed_up(app)
    ann.post("/goals", data={"csrf": token(ann, "/goals"), "kind": "worth", "target": "5000"})
    conn = db.get_connection(db_path)
    ann_id = db.get_user_by_email(conn, "ann@example.com")["id"]
    [g] = db.get_goals(conn, ann_id)
    bob = signed_up(app, "bob@example.com")
    assert "$5,000.00" not in bob.get("/goals").get_data(as_text=True)
    assert bob.post(f"/goals/{g['id']}/remove", data={"csrf": token(bob, "/goals")}).status_code == 404
    assert len(db.get_goals(conn, ann_id)) == 1
    conn.close()


def test_logged_out_and_forged_requests_change_nothing(app, db_path):
    assert app.test_client().get("/goals").status_code == 302
    c = signed_up(app)
    assert c.post("/goals", data={"kind": "worth", "target": "5000"}).status_code == 400        # no form token
    conn = db.get_connection(db_path)
    assert db.get_goals(conn, db.get_user_by_email(conn, "ann@example.com")["id"]) == []
    conn.close()


def test_at_most_ten_goals(app, db_path):
    c = signed_up(app)
    conn = db.get_connection(db_path)
    uid = db.get_user_by_email(conn, "ann@example.com")["id"]
    for i in range(db.GOALS_MAX):
        db.add_goal(conn, uid, "worth", 1000 + i, None, "2026-11-01")
    conn.close()
    r = c.post("/goals", data={"csrf": token(c, "/goals"), "kind": "worth", "target": "5000"})
    assert r.status_code == 422 and "the most SGXray keeps" in r.get_data(as_text=True)


def test_goals_are_in_your_data_download_and_go_when_you_delete(app, db_path):
    c = signed_up(app)
    c.post("/goals", data={"csrf": token(c, "/goals"), "kind": "worth", "target": "5000", "by_month": "2031-01"})
    assert [(g["kind"], g["target"], g["by_month"]) for g in c.get("/account/data").get_json()["goals"]] == [
        ("worth", 5000.0, "2031-01")]
    conn = db.get_connection(db_path)
    assert db.delete_user(conn, db.get_user_by_email(conn, "ann@example.com")["id"])
    assert conn.execute("SELECT COUNT(*) FROM goals").fetchone()[0] == 0
    conn.close()


def test_your_dashboard_shows_your_goals_and_the_demo_never_does(app):
    c = signed_up(app)
    c.post("/trades", data={"csrf": token(c), "ticker": "D05.SI", "date": "2025-01-02", "side": "BUY",
                            "quantity": "10", "price": "30", "fees": ""})
    page = c.get("/portfolio").get_data(as_text=True)
    assert "Set a goal" in page and "Your goals" not in page
    c.post("/goals", data={"csrf": token(c, "/goals"), "kind": "worth", "target": "5000"})
    page = c.get("/portfolio").get_data(as_text=True)
    assert 'id="dash-goals-title">Your goals' in page and "Set a goal" not in page
    assert "dash-goals-title" not in c.get("/demo").get_data(as_text=True)
