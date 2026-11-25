"""Privacy notice, terms of use, "Download my data" and "Delete my account" (audit 4, Singapore's PDPA).

What the privacy notice promises is what the code does: the download holds your data and only yours (never a
password hash or session secret), and deleting really removes every table's rows for you, practice twin included.
"""

import json

import db
from test_trades import GOOD, add, app, db_path, downloads, signed_up, token  # noqa: F401  (fixtures)


def _uid(db_path, email="ann@example.com"):
    conn = db.get_connection(db_path)
    row = db.get_user_by_email(conn, email)
    conn.close()
    return row["id"] if row else None


def _rows_for(db_path, uid):
    """How many rows in every per-person table still point at this user (or their practice twin)."""
    conn = db.get_connection(db_path)
    twin = conn.execute("SELECT id FROM users WHERE practice_of = ?", (uid,)).fetchone()
    ids = [uid] + ([twin["id"]] if twin else [])
    marks = ",".join("?" * len(ids))
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t} WHERE user_id IN ({marks})", ids).fetchone()[0]
              for t in ("trades", "plans", "sessions", "password_resets", "security_log", "lesson_reads")}
    counts["users"] = conn.execute(f"SELECT COUNT(*) FROM users WHERE id IN ({marks}) OR practice_of = ?",
                                   (*ids, uid)).fetchone()[0]
    conn.close()
    return counts


def _full_account(app):
    c = signed_up(app)
    add(c, note="my reason")
    c.post("/practice/trades", data={"csrf": token(c, "/practice/trades"), "ticker": "D05.SI", "side": "BUY",
                                     "quantity": "10", "note": ""})
    c.post("/learn/first-dollar/done", data={"csrf": token(c, "/learn/first-dollar")})
    c.post("/plans", data={"csrf": token(c), "ticker": "ES3.SI", "amount": "100", "day": "15", "start": "2025-01",
                           "fee_rate": "0", "fee_min": "0"})
    return c


# ---------- The pages ----------

def test_the_privacy_notice_and_terms_are_open_to_everyone_and_linked_from_every_page(app):
    c = app.test_client()
    for path in ("/privacy", "/terms"):
        assert c.get(path).status_code == 200
    for path in ("/", "/demo", "/learn", "/login", "/news"):
        page = c.get(path).get_data(as_text=True)
        assert 'href="/privacy"' in page and 'href="/terms"' in page, path


def test_sign_up_says_what_you_agree_to(app):
    page = app.test_client().get("/signup").get_data(as_text=True)
    assert "terms of use" in page and 'href="/privacy"' in page


def test_the_notice_names_sgxrays_contact_and_the_setting_can_change_it(app, monkeypatch):
    monkeypatch.delenv("SGXRAY_CONTACT_EMAIL", raising=False)
    c = app.test_client()
    for path in ("/privacy", "/terms"):
        assert "mailto:sgxray.app@gmail.com" in c.get(path).get_data(as_text=True), path
    assert "added here before launch" not in c.get("/privacy").get_data(as_text=True)
    monkeypatch.setenv("SGXRAY_CONTACT_EMAIL", "privacy@example.com")
    assert "mailto:privacy@example.com" in c.get("/privacy").get_data(as_text=True)


def test_the_terms_say_education_not_advice(app):
    page = app.test_client().get("/terms").get_data(as_text=True)
    assert "financial advice" in page and "Monetary Authority of Singapore" in page


# ---------- Download my data ----------

def test_download_needs_a_login(app):
    r = app.test_client().get("/account/data")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_download_holds_your_data_and_only_yours(app, db_path):
    other = signed_up(app, "bob@example.com")
    add(other, note="bob's secret reason")
    c = _full_account(app)
    r = c.get("/account/data")
    assert r.status_code == 200 and "attachment" in r.headers["Content-Disposition"]
    assert "no-store" in r.headers["Cache-Control"]
    data = json.loads(r.get_data(as_text=True))
    assert data["account"]["email"] == "ann@example.com"
    assert data["trades"][0]["note"] == "my reason" and len(data["practice"]["trades"]) == 1
    assert data["lessons_read"][0]["lesson"] == "first-dollar" and len(data["monthly_plans"]) == 1
    assert any(e["event"] == "signup" for e in data["security_log"])
    text = r.get_data(as_text=True)
    assert "bob" not in text and "scrypt" not in text and "password_hash" not in text


# ---------- Delete my account ----------

def test_deleting_needs_your_password_and_the_form_token(app, db_path):
    c = _full_account(app)
    assert c.get("/account/delete").status_code == 200
    assert c.post("/account/delete", data={"current": GOOD}).status_code == 400            # no token
    r = c.post("/account/delete", data={"csrf": token(c, "/account/delete"), "current": "not my password"})
    assert r.status_code == 401
    assert _uid(db_path) is not None


def test_password_guessing_on_the_delete_page_is_limited(app, db_path):
    c = _full_account(app)
    for _ in range(5):
        c.post("/account/delete", data={"csrf": token(c, "/account/delete"), "current": "wrong guess"})
    r = c.post("/account/delete", data={"csrf": token(c, "/account/delete"), "current": GOOD})
    assert r.status_code == 429 and _uid(db_path) is not None


def test_deleting_removes_everything_and_ends_every_session(app, db_path):
    c = _full_account(app)
    other_device = app.test_client()
    other_device.post("/login", data={"csrf": token(other_device, "/login"), "email": "ann@example.com", "password": GOOD})
    uid = _uid(db_path)
    before = _rows_for(db_path, uid)
    assert before["trades"] == 2 and before["plans"] == 1 and before["lesson_reads"] == 1 and before["sessions"] == 2
    r = c.post("/account/delete", data={"csrf": token(c, "/account/delete"), "current": GOOD})
    assert r.status_code == 302 and r.headers["Location"].endswith("/")
    assert "have been deleted" in c.get("/").get_data(as_text=True)
    assert all(n == 0 for n in _rows_for(db_path, uid).values()), _rows_for(db_path, uid)
    for client in (c, other_device):
        assert client.get("/portfolio").status_code == 302                     # logged out everywhere
    again = signed_up(app)                                                       # the email is free again
    assert again.get("/portfolio").status_code == 200


def test_nobody_else_is_touched(app, db_path):
    other = signed_up(app, "bob@example.com")
    add(other)
    c = _full_account(app)
    c.post("/account/delete", data={"csrf": token(c, "/account/delete"), "current": GOOD})
    bob = _uid(db_path, "bob@example.com")
    assert _rows_for(db_path, bob)["trades"] == 1 and other.get("/portfolio").status_code == 200
