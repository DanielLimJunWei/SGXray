"""Accounts, tested the way an attacker would try to break them.

Each test is an "abuse case": what a hacker would try, and proof that it fails.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import auth  # noqa: E402
import db  # noqa: E402
from app import create_app  # noqa: E402
from instruments import seed_instruments  # noqa: E402

GOOD = "correct horse battery staple"


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "auth.db"
    conn = db.get_connection(path)
    db.init_db(conn)
    seed_instruments(conn)
    conn.close()
    return path


@pytest.fixture
def app(db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SGXRAY_SECRET_KEY", "test-only-secret")
    return create_app(db_path)


def csrf(client, path):
    """The form token from a page, as a real browser would have it."""
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def signup(client, email="ann@example.com", password=GOOD):
    return client.post("/signup", data={"csrf": csrf(client, "/signup"), "email": email,
                                        "password": password, "password2": password})


def login(client, email="ann@example.com", password=GOOD):
    return client.post("/login", data={"csrf": csrf(client, "/login"), "email": email, "password": password})


# ---------- Passwords are salted, slow hashes ----------

def test_passwords_are_hashed_with_scrypt_and_a_unique_salt(app, db_path):
    a, b = app.test_client(), app.test_client()
    signup(a, "ann@example.com")
    signup(b, "bob@example.com")                       # the SAME password
    conn = db.get_connection(db_path)
    ha = db.get_user_by_email(conn, "ann@example.com")["password_hash"]
    hb = db.get_user_by_email(conn, "bob@example.com")["password_hash"]
    assert GOOD not in ha and ha.startswith("scrypt:")
    assert ha != hb                                     # different salts -> different hashes


def test_weak_passwords_are_refused(app):
    c = app.test_client()
    for bad in ["short", "password1234", "aaaaaaaaaaaaaaaa", "annexample-is-my-password"]:
        assert auth.password_problem(bad, "annexample@example.com")
        assert signup(c, "annexample@example.com", bad).status_code == 422


# ---------- Guessing passwords ----------

def test_wrong_password_and_unknown_email_look_identical(app):
    c = app.test_client()
    signup(c)
    c.post("/logout", data={"csrf": csrf(c, "/portfolio")})
    wrong = login(c, "ann@example.com", "not the password at all")
    nobody = login(c, "nobody@example.com", "not the password at all")
    assert wrong.status_code == nobody.status_code == 401
    msg = "That email and password don&#39;t match."
    assert msg in wrong.get_data(as_text=True) and msg in nobody.get_data(as_text=True)


def test_password_guessing_is_locked_out(app):
    c = app.test_client()
    signup(c)
    c.post("/logout", data={"csrf": csrf(c, "/portfolio")})
    for _ in range(auth.MAX_ATTEMPTS):
        assert login(c, password="wrong password guess").status_code == 401
    # Even the RIGHT password is refused while locked out, so guessing gains nothing.
    blocked = login(c)
    assert blocked.status_code == 429 and "Too many tries" in blocked.get_data(as_text=True)


def test_the_demo_account_cannot_be_logged_into(app, db_path):
    from importer import DEMO_EMAIL
    conn = db.get_connection(db_path)
    db.create_user(conn, DEMO_EMAIL, "!demo-no-login")
    conn.close()
    assert login(app.test_client(), DEMO_EMAIL, "!demo-no-login").status_code == 401


# ---------- Sessions ----------

def test_session_cookie_is_protected(app):
    r = signup(app.test_client())
    cookie = r.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_a_new_session_is_made_at_login(app):
    c = app.test_client()
    signup(c)
    c.post("/logout", data={"csrf": csrf(c, "/portfolio")})
    before = csrf(c, "/login")
    login(c)
    after = re.search(r'name="csrf" value="([^"]+)"', c.get("/account").get_data(as_text=True)).group(1)
    assert before != after                              # an old (possibly planted) session is thrown away


def test_changing_password_logs_out_other_devices(app):
    phone, laptop = app.test_client(), app.test_client()
    signup(phone)
    login(laptop)
    assert laptop.get("/portfolio").status_code == 200
    new = "a different long passphrase"
    r = phone.post("/account", data={"csrf": csrf(phone, "/account"), "current": GOOD,
                                     "password": new, "password2": new})
    assert "Password changed" in r.get_data(as_text=True)
    assert laptop.get("/portfolio").status_code == 302      # the laptop's old session no longer works
    assert phone.get("/portfolio").status_code == 200       # the phone that changed it stays in


def test_logout_needs_a_post_with_a_token(app):
    c = app.test_client()
    signup(c)
    assert c.get("/logout").status_code == 405          # a link or <img> can't log you out
    assert c.post("/logout").status_code == 400         # no token
    assert c.get("/portfolio").status_code == 200


# ---------- Forged forms (CSRF) ----------

def test_forms_without_the_token_are_rejected(app):
    c = app.test_client()
    assert c.post("/signup", data={"email": "x@example.com", "password": GOOD, "password2": GOOD}).status_code == 400
    assert c.post("/login", data={"csrf": "made-up", "email": "x@example.com", "password": GOOD}).status_code == 400


# ---------- Other people's data ----------

def test_portfolio_needs_login_and_shows_only_your_own(app, db_path):
    assert app.test_client().get("/portfolio").status_code == 302
    ann, bob = app.test_client(), app.test_client()
    signup(ann, "ann@example.com")
    signup(bob, "bob@example.com")
    conn = db.get_connection(db_path)
    ann_id = db.get_user_by_email(conn, "ann@example.com")["id"]
    db.add_trade(conn, ann_id, "D05.SI", "2025-01-06", "BUY", 100, 40.0, 10.0)
    db.save_prices(conn, "D05.SI", [("2025-01-06", 40.0), ("2025-06-30", 44.0)])
    conn.close()
    holding = 'data-chart="chart-D05-SI"'                # Ann's DBS row in the holdings table
    assert holding in ann.get("/portfolio").get_data(as_text=True)
    bob_page = bob.get("/portfolio").get_data(as_text=True)
    assert holding not in bob_page and "No trades yet" in bob_page
    assert bob.get(f"/portfolio?user={ann_id}").get_data(as_text=True) == bob_page   # no way to ask for Ann's


def test_sql_injection_in_the_login_form_does_nothing(app):
    c = app.test_client()
    signup(c)
    c.post("/logout", data={"csrf": csrf(c, "/portfolio")})
    for attack in ["' OR '1'='1", "ann@example.com' --", "x'; DROP TABLE users; --"]:
        assert login(c, attack, attack).status_code == 401
    assert login(c).status_code == 302                  # the users table is still there


# ---------- Redirects and headers ----------

@pytest.mark.parametrize("evil", ["https://evil.example/", "//evil.example", "/\\evil.example", "javascript:alert(1)"])
def test_login_never_redirects_to_another_site(app, evil):
    c = app.test_client()
    signup(c)
    c.post("/logout", data={"csrf": csrf(c, "/portfolio")})
    r = c.post("/login", data={"csrf": csrf(c, "/login"), "email": "ann@example.com", "password": GOOD, "next": evil})
    assert r.status_code == 302 and r.headers["Location"].endswith("/portfolio")


def test_security_headers_and_a_fresh_nonce_each_page(app):
    c = app.test_client()
    a, b = c.get("/"), c.get("/")
    csp = a.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    nonce_a = re.search(r"'nonce-([^']+)'", csp).group(1)
    assert f'nonce="{nonce_a}"' in a.get_data(as_text=True)          # the import map carries it
    assert nonce_a not in b.headers["Content-Security-Policy"]        # and it's new every time
    assert c.get("/login").headers["Cache-Control"] == "no-store"


def test_nothing_secret_is_written_to_the_security_log(app, db_path):
    c = app.test_client()
    signup(c)
    c.post("/logout", data={"csrf": csrf(c, "/portfolio")})
    login(c, password="a wrong password here")
    conn = db.get_connection(db_path)
    rows = [tuple(r) for r in conn.execute("SELECT * FROM security_log")]
    assert [r[2] for r in rows] == ["signup", "logout", "login_failed"]
    assert not any(GOOD in str(r) or "a wrong password here" in str(r) for r in rows)


# ---------- Added after the 54-check security audit ----------

def test_a_copied_cookie_stops_working_after_logout(app):
    """Check 25: logging out must end the session on the server, not just delete the browser's cookie."""
    victim = app.test_client()
    signup(victim)
    stolen = victim.get_cookie("session").value          # what an attacker could copy off the laptop
    victim.post("/logout", data={"csrf": csrf(victim, "/portfolio")})
    attacker = app.test_client()
    attacker.set_cookie("session", stolen)
    assert attacker.get("/portfolio").status_code == 302  # back to the login page


def test_only_a_hash_of_each_session_id_is_stored(app, db_path):
    c = app.test_client()
    signup(c)
    conn = db.get_connection(db_path)
    rows = conn.execute("SELECT id_hash FROM sessions").fetchall()
    assert len(rows) == 1 and len(rows[0]["id_hash"]) == 64          # a SHA-256, not the id itself


def test_signups_from_one_address_are_limited(app):
    c = app.test_client()
    for n in range(auth.SIGNUPS_PER_HOUR):
        assert signup(c, f"user{n}@example.com").status_code == 302
        c.post("/logout", data={"csrf": csrf(c, "/portfolio")})
    assert signup(c, "one-too-many@example.com").status_code == 429


def test_guessing_the_current_password_on_the_account_page_is_limited(app):
    c = app.test_client()
    signup(c)
    for _ in range(auth.PASSWORD_TRIES):
        r = c.post("/account", data={"csrf": csrf(c, "/account"), "current": "a wrong guess here",
                                     "password": "another long passphrase", "password2": "another long passphrase"})
        assert r.status_code == 401
    r = c.post("/account", data={"csrf": csrf(c, "/account"), "current": GOOD,
                                 "password": "another long passphrase", "password2": "another long passphrase"})
    assert r.status_code == 429


def test_old_security_records_are_deleted(app, db_path):
    conn = db.get_connection(db_path)
    conn.execute("INSERT INTO login_attempts (key, attempted_at) VALUES ('ip:1.2.3.4', '2020-01-01T00:00:00')")
    conn.execute("INSERT INTO security_log (event, ip, at) VALUES ('login_failed', '1.2.3.4', '2020-01-01T00:00:00')")
    conn.execute("INSERT INTO security_log (event, ip) VALUES ('login_failed', '5.6.7.8')")
    conn.commit()
    db.prune(conn)
    assert conn.execute("SELECT COUNT(*) FROM login_attempts").fetchone()[0] == 0
    assert [r["ip"] for r in conn.execute("SELECT ip FROM security_log")] == ["5.6.7.8"]


def test_errors_are_generic_and_debug_is_off(db_path, monkeypatch):
    monkeypatch.setenv("SGXRAY_SECRET_KEY", "test-only-secret")
    app = create_app(db_path)
    assert app.debug is False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail: /var/db/password")

    r = app.test_client().get("/boom")
    body = r.get_data(as_text=True)
    assert r.status_code == 500 and "Something went wrong on our side" in body
    assert "secret internal detail" not in body and "Traceback" not in body
    missing = app.test_client().get("/no-such-page")
    assert missing.status_code == 404 and "Page not found" in missing.get_data(as_text=True)


# ---------- Added after the Part 4 checks (55-70) ----------

def test_two_signups_for_one_email_at_the_same_moment(app, db_path, monkeypatch):
    """Check 58: if two requests race past the "is this email free?" check, the database's UNIQUE rule
    still allows only one account, and the loser gets the normal calm message, not a crash."""
    import app as web
    c = app.test_client()
    real = db.get_user_by_email
    monkeypatch.setattr(web.db, "get_user_by_email", lambda conn, email: None)   # both see "free"
    assert signup(c, "race@example.com").status_code == 302
    c.post("/logout", data={"csrf": csrf(c, "/portfolio")})
    loser = signup(c, "race@example.com")
    monkeypatch.setattr(web.db, "get_user_by_email", real)
    assert loser.status_code == 422 and "couldn&#39;t create an account" in loser.get_data(as_text=True)
    conn = db.get_connection(db_path)
    assert conn.execute("SELECT COUNT(*) FROM users WHERE email = 'race@example.com'").fetchone()[0] == 1


def test_a_forged_or_broken_cookie_means_logged_out(app):
    """Check 63 (fail closed): a cookie that doesn't verify gives no access, never an error or a guess."""
    c = app.test_client()
    signup(c)
    good = c.get_cookie("session").value
    for bad in [good[:-4] + "AAAA", "not-a-real-cookie", ""]:
        other = app.test_client()
        other.set_cookie("session", bad)
        assert other.get("/portfolio").status_code == 302
