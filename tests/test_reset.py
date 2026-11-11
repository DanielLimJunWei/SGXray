"""'Forgot your password?', tested the way an attacker (or a confused person) would try to break it.

Each test is an abuse case: finding out who has an account, guessing or reusing a link, a link that
outlives its time, flooding someone's inbox, poisoning the link's address, leaking the secret.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import auth  # noqa: E402
import db  # noqa: E402
import mailer  # noqa: E402
from app import create_app  # noqa: E402
from importer import DEMO_EMAIL  # noqa: E402
from instruments import seed_instruments  # noqa: E402

GOOD = "correct horse battery staple"
NEW = "a brand new long passphrase"


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "reset.db"
    conn = db.get_connection(path)
    db.init_db(conn)
    seed_instruments(conn)
    conn.close()
    return path


@pytest.fixture
def inbox():
    return []


@pytest.fixture
def app(db_path, inbox, monkeypatch):
    monkeypatch.setenv("SGXRAY_SECRET_KEY", "test-only-secret")
    monkeypatch.delenv("SGXRAY_BASE_URL", raising=False)
    monkeypatch.delenv("SGXRAY_HTTPS", raising=False)
    a = create_app(db_path)
    a.config["SEND_EMAIL"] = lambda to, subject, text: inbox.append((to, subject, text)) or True
    a.config["EMAIL_IN_BACKGROUND"] = False
    return a


def csrf(client, path):
    return re.search(r'name="csrf" value="([^"]+)"', client.get(path).get_data(as_text=True)).group(1)


def signup(client, email="ann@example.com"):
    return client.post("/signup", data={"csrf": csrf(client, "/signup"), "email": email,
                                        "password": GOOD, "password2": GOOD})


def ask(client, email="ann@example.com"):
    return client.post("/forgot", data={"csrf": csrf(client, "/forgot"), "email": email})


def link_in(inbox):
    return re.search(r"(http://\S+/reset/\S+)", inbox[-1][2]).group(1)


def path_of(link):
    return link.split("localhost", 1)[1]


def set_new(client, password=NEW, password2=None):
    return client.post("/reset", data={"csrf": csrf(client, "/forgot"), "password": password,
                                       "password2": password2 or password})


def login(client, password):
    return client.post("/login", data={"csrf": csrf(client, "/login"), "email": "ann@example.com", "password": password})


def account_holder(app):
    c = app.test_client()
    signup(c)
    c.post("/logout", data={"csrf": csrf(c, "/portfolio")})
    return c


# ---------- The happy path ----------

def test_a_reset_link_lets_you_choose_a_new_password(app, inbox):
    c = account_holder(app)
    r = ask(c)
    assert r.status_code == 200 and "Check your email" in r.get_data(as_text=True)
    assert inbox[0][0] == "ann@example.com" and "30 minutes" in inbox[0][2]
    r = c.get(path_of(link_in(inbox)))
    assert r.status_code == 302 and r.headers["Location"].endswith("/reset")    # the secret leaves the address bar
    assert "Choose a new password" in c.get("/reset").get_data(as_text=True)
    r = set_new(c)
    assert r.status_code == 302 and r.headers["Location"].endswith("/login")
    assert "Password reset" in c.get("/login").get_data(as_text=True)
    assert login(c, GOOD).status_code == 401                                   # the old one is gone
    assert login(c, NEW).status_code == 302


# ---------- Finding out who has an account ----------

def test_the_answer_is_the_same_for_real_and_made_up_emails(app, inbox):
    c = account_holder(app)
    real, fake = ask(c, "ann@example.com"), ask(c, "nobody@example.com")
    assert real.status_code == fake.status_code == 200
    strip = lambda r, e: re.sub(r'name="csrf" value="[^"]+"', "", r.get_data(as_text=True)).replace(e, "EMAIL")
    assert strip(real, "ann@example.com") == strip(fake, "nobody@example.com")
    assert len(inbox) == 1 and inbox[0][0] == "ann@example.com"              # only the real one gets mail


def test_the_demo_account_gets_no_reset_email(app, inbox, db_path):
    conn = db.get_connection(db_path)
    db.create_user(conn, DEMO_EMAIL, "!no-login")
    conn.close()
    assert ask(app.test_client(), DEMO_EMAIL).status_code == 200
    assert inbox == []


# ---------- Guessing, reusing and keeping links ----------

def test_a_link_works_only_once(app, inbox):
    c = account_holder(app)
    ask(c)
    link = path_of(link_in(inbox))
    c.get(link)
    set_new(c)
    other = app.test_client()
    other.get(link)
    assert other.get("/reset").status_code == 410
    assert set_new(other, "yet another long passphrase").status_code == 410
    assert login(other, "yet another long passphrase").status_code == 401


def test_an_old_link_expires(app, inbox, db_path):
    c = account_holder(app)
    ask(c)
    conn = db.get_connection(db_path)
    conn.execute("UPDATE password_resets SET expires_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', '-1 minute')")
    conn.commit()
    conn.close()
    c.get(path_of(link_in(inbox)))
    r = c.get("/reset")
    assert r.status_code == 410 and "expired" in r.get_data(as_text=True)


def test_asking_again_turns_off_the_earlier_link(app, inbox):
    c = account_holder(app)
    ask(c)
    first = path_of(link_in(inbox))
    ask(c)
    c.get(first)
    assert c.get("/reset").status_code == 410
    c.get(path_of(link_in(inbox)))
    assert c.get("/reset").status_code == 200


def test_made_up_links_do_nothing(app):
    c = account_holder(app)
    for guess in ("abc", "x" * 43, "../../etc/passwd", "' OR 1=1 --"):
        c.get("/reset/" + guess)
        assert c.get("/reset").status_code == 410
    assert app.test_client().get("/reset").status_code == 410                # no link at all


def test_only_a_hash_of_the_link_is_stored(app, inbox, db_path):
    c = account_holder(app)
    ask(c)
    secret = link_in(inbox).rsplit("/", 1)[1]
    conn = db.get_connection(db_path)
    rows = [tuple(r) for r in conn.execute("SELECT * FROM password_resets")]
    log = [tuple(r) for r in conn.execute("SELECT * FROM security_log")]
    conn.close()
    assert rows and secret not in repr(rows)
    assert secret not in repr(log) and any("reset_requested" in repr(e) for e in log)


# ---------- What a reset does ----------

def test_a_reset_logs_out_every_device(app, inbox):
    laptop = app.test_client()
    signup(laptop)                                          # still logged in on the laptop
    phone = app.test_client()
    ask(phone)
    phone.get(path_of(link_in(inbox)))
    set_new(phone)
    assert laptop.get("/portfolio").status_code == 302      # the laptop's session no longer works


def test_the_new_password_must_be_good(app, inbox):
    c = account_holder(app)
    ask(c)
    c.get(path_of(link_in(inbox)))
    assert set_new(c, "short").status_code == 422
    assert set_new(c, NEW, "a different long passphrase").status_code == 422
    assert c.get("/reset").status_code == 200               # a mistake doesn't use the link up


def test_forms_need_their_token(app, inbox):
    c = account_holder(app)
    assert c.post("/forgot", data={"email": "ann@example.com"}).status_code == 400
    ask(c)
    c.get(path_of(link_in(inbox)))
    assert c.post("/reset", data={"password": NEW, "password2": NEW}).status_code == 400


# ---------- Flooding ----------

def test_one_inbox_cant_be_flooded(app, inbox):
    c = account_holder(app)
    for _ in range(auth.RESETS_PER_HOUR_EMAIL):
        assert ask(c).status_code == 200
    r = ask(c)
    assert r.status_code == 429 and "Too many" in r.get_data(as_text=True)
    assert len(inbox) == auth.RESETS_PER_HOUR_EMAIL


def test_the_limit_looks_the_same_for_made_up_emails(app):
    c = app.test_client()
    for _ in range(auth.RESETS_PER_HOUR_EMAIL):
        ask(c, "nobody@example.com")
    assert ask(c, "nobody@example.com").status_code == 429


def test_one_network_address_cant_try_many_emails(app):
    c = app.test_client()
    for i in range(auth.RESETS_PER_HOUR_IP):
        assert ask(c, f"person{i}@example.com").status_code == 200
    assert ask(c, "one-more@example.com").status_code == 429


# ---------- The link's address ----------

def test_the_live_site_never_builds_links_from_the_visitors_request(app, inbox, monkeypatch):
    """Host-header poisoning: an attacker asks for Ann's reset with a fake Host header, hoping her
    email links to their site. Live, links only ever use SGXRAY_BASE_URL."""
    c = account_holder(app)
    c.environ_base["HTTP_HOST"] = "evil.example"            # every request now claims to be for evil.example
    monkeypatch.setenv("SGXRAY_HTTPS", "1")
    assert ask(c).status_code == 200                        # accepted, same answer as ever...
    assert inbox == []                                      # ...but with no base address set, nothing is sent
    monkeypatch.setenv("SGXRAY_BASE_URL", "https://sgxray.example")
    assert ask(c).status_code == 200
    assert inbox and "https://sgxray.example/reset/" in inbox[-1][2] and "evil" not in inbox[-1][2]


def test_reset_pages_pass_on_no_referrer_and_are_not_cached(app, inbox):
    c = account_holder(app)
    ask(c)
    r = c.get(path_of(link_in(inbox)))
    assert r.headers["Referrer-Policy"] == "no-referrer" and r.headers["Cache-Control"] == "no-store"
    r = c.get("/reset")
    assert r.headers["Referrer-Policy"] == "no-referrer" and r.headers["Cache-Control"] == "no-store"


# ---------- The email sender ----------

def test_without_email_set_up_the_dev_outbox_prints_it(monkeypatch, capsys):
    monkeypatch.delenv("SGXRAY_SMTP_HOST", raising=False)
    monkeypatch.delenv("SGXRAY_HTTPS", raising=False)
    assert mailer.send("ann@example.com", "Hi", "the link")
    assert "dev outbox" in capsys.readouterr().out


def test_the_live_site_without_email_set_up_prints_no_link(monkeypatch, capsys):
    monkeypatch.delenv("SGXRAY_SMTP_HOST", raising=False)
    monkeypatch.setenv("SGXRAY_HTTPS", "1")
    assert not mailer.send("ann@example.com", "Hi", "https://x/reset/SECRET")
    out = capsys.readouterr()
    assert "SECRET" not in out.out + out.err


def test_a_failing_email_service_doesnt_crash_or_leak(monkeypatch, capsys):
    monkeypatch.setenv("SGXRAY_SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SGXRAY_SMTP_PORT", "1")              # nothing listens there
    assert not mailer.send("ann@example.com", "Hi", "https://x/reset/SECRET")
    out = capsys.readouterr()
    assert "SECRET" not in out.out + out.err


# ---------- Switching account ----------

def test_log_in_as_someone_else_goes_to_the_login_page(app):
    c = app.test_client()
    signup(c)
    r = c.post("/logout", data={"csrf": csrf(c, "/account"), "then": "login"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/login")
    assert c.get("/portfolio").status_code == 302           # really logged out


def test_switching_account_cant_redirect_elsewhere(app):
    c = app.test_client()
    signup(c)
    r = c.post("/logout", data={"csrf": csrf(c, "/account"), "then": "https://evil.example"})
    assert "evil" not in r.headers["Location"]
