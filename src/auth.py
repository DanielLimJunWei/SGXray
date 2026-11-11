"""Accounts: passwords, login limits, sessions and form protection.

PASSWORDS are never stored. Each one goes through scrypt (via Werkzeug, which comes with Flask)
with its own random SALT: a random string mixed in before hashing, so two people with the same
password still get different hashes, and pre-computed "rainbow tables" of common passwords are
useless. scrypt is deliberately slow and memory-hungry, so guessing millions of passwords
against a stolen hash is very expensive. Checking a login re-hashes the typed password with the
stored salt and compares the results.

LOGIN LIMITS: after MAX_ATTEMPTS failed logins for one email, or from one network address,
within WINDOW_MINUTES, logins are refused for a while. The counts live in the database, so the
limit still holds when several server processes are running.

CSRF: every form carries a random token that is also kept in the session. A form posted from
another website can't know it, so it's rejected. (CSRF = cross-site request forgery: a page
on another site quietly submitting a form to SGXray with your logged-in cookie.)
"""

import hmac
import re
import secrets
from urllib.parse import urlsplit

from werkzeug.security import check_password_hash, generate_password_hash

import db

MIN_LENGTH = 12
MAX_LENGTH = 128               # scrypt on a huge "password" is a cheap way to tie up the server
MAX_ATTEMPTS = 10
WINDOW_MINUTES = 15
SIGNUPS_PER_HOUR = 5           # new accounts from one network address in an hour
PASSWORD_TRIES = 5             # wrong "current password" tries on the account page, per 15 minutes
RESET_MINUTES = 30             # a "forgot your password?" link works this long, and once
RESETS_PER_HOUR_EMAIL = 3      # reset emails for one address in an hour (no inbox flooding)
RESETS_PER_HOUR_IP = 10        # reset requests from one network address in an hour
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")

# The most common passwords in public breach lists (12+ characters, since shorter ones are refused
# anyway), plus obvious patterns. Kept here so nothing is sent to an outside service.
COMMON = {
    "password1234", "password12345", "password123456", "passwordpassword", "123456789012",
    "1234567890123", "qwertyuiopas", "qwerty123456", "iloveyou1234", "welcome12345",
    "abc123456789", "aaaaaaaaaaaa", "111111111111", "000000000000", "letmein12345",
    "adminadmin123", "administrator", "sunshine1234", "football1234", "baseball1234",
    "princess1234", "superman1234", "trustno11234", "changeme1234", "1q2w3e4r5t6y",
    "qwertyqwerty", "asdfghjkl123", "zxcvbnm12345", "monkey123456", "dragon123456",
    "singapore123", "singapore1234", "sgxray123456", "investing123", "stocks123456",
}

# A real hash of a random password, checked when an email isn't found, so a login for an unknown
# email takes as long as one for a real account (otherwise the timing would reveal who has one).
_DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(16))


def hash_password(password):
    return generate_password_hash(password)              # scrypt, with a fresh random salt


def password_problem(password, email=""):
    """A plain-English reason the password isn't good enough, or None if it's fine."""
    if len(password) < MIN_LENGTH:
        return f"Use at least {MIN_LENGTH} characters. A short sentence you'll remember works well."
    if len(password) > MAX_LENGTH:
        return f"Use at most {MAX_LENGTH} characters."
    lowered = password.lower()
    if lowered in COMMON or len(set(lowered)) <= 3:
        return "That password is too common or too simple to be safe. Try a few unrelated words."
    name = email.split("@")[0].lower()
    if len(name) >= 4 and name in lowered:
        return "Don't use your email address in your password."
    return None


def email_problem(email):
    if not EMAIL.match(email) or len(email) > 254:
        return "Enter a valid email address."
    if email.strip().lower().endswith(".invalid"):     # reserved: practice twins use it, and it can't get email
        return "Enter a valid email address."
    return None


def check_login(conn, email, password):
    """The user if the email and password match, else None. Takes about the same time either way."""
    user = db.get_user_by_email(conn, email)
    if user is None or user["password_hash"].startswith("!"):     # no such user, or a no-login account (the demo)
        check_password_hash(_DUMMY_HASH, password)
        return None
    return user if check_password_hash(user["password_hash"], password) else None


def too_many_attempts(conn, email, ip):
    return (db.count_login_attempts(conn, "email:" + email.lower(), WINDOW_MINUTES) >= MAX_ATTEMPTS
            or db.count_login_attempts(conn, "ip:" + (ip or "?"), WINDOW_MINUTES) >= MAX_ATTEMPTS)


def record_failure(conn, email, ip):
    db.add_login_attempt(conn, "email:" + email.lower())
    db.add_login_attempt(conn, "ip:" + (ip or "?"))


def limited(conn, key, most, minutes):
    """True if `key` has already been counted `most` times in the last `minutes` minutes."""
    return db.count_login_attempts(conn, key, minutes) >= most


def count(conn, key):
    db.add_login_attempt(conn, key)


def new_csrf_token():
    return secrets.token_urlsafe(32)


def csrf_ok(session_token, form_token):
    """Constant-time compare, so the token can't be guessed one character at a time from timing."""
    return bool(session_token) and bool(form_token) and hmac.compare_digest(session_token, form_token)


def safe_next(url, default="/portfolio"):
    """Only allow redirects back into SGXray itself ('/portfolio'), never to another site.
    Otherwise a link like /login?next=https://evil.example could send you to a fake page after logging in."""
    if not url:
        return default
    parts = urlsplit(url)
    if parts.scheme or parts.netloc or not url.startswith("/") or url.startswith("//") or "\\" in url:
        return default
    return url
