"""Sending email (for now, only password-reset links).

No new library: Python's own smtplib talks to any email service that offers SMTP (Resend, Brevo,
Postmark, Amazon SES and Gmail all do). It's switched on by settings, never by code:

    SGXRAY_SMTP_HOST      the service's SMTP server, e.g. smtp.resend.com
    SGXRAY_SMTP_PORT      587 (the default): the connection is upgraded to encrypted (STARTTLS)
    SGXRAY_SMTP_USER      the login the service gives you
    SGXRAY_SMTP_PASSWORD  its password or API key: a secret, so only ever in Render's settings
    SGXRAY_MAIL_FROM      who the email is from, e.g. "SGXray <no-reply@your-domain>"

Without SGXRAY_SMTP_HOST:
- on your own computer, the email is printed in the server's terminal instead of sent (a "dev outbox"),
  so you can click the link while testing;
- on the live site (SGXRAY_HTTPS=1) nothing is sent and nothing secret is printed: the link would
  end up in the host's logs, which other people can read.
"""

import os
import smtplib
import ssl
import sys
from email.message import EmailMessage


def configured():
    return bool(os.environ.get("SGXRAY_SMTP_HOST"))


def live():
    return os.environ.get("SGXRAY_HTTPS") == "1"


def send(to, subject, text):
    """Sends a plain-text email. Returns True if it was handed to the email service (or printed in
    development), False if it couldn't be. Never raises: a failed email mustn't crash a page."""
    if not configured():
        if live():
            print("SGXray: email isn't set up (SGXRAY_SMTP_HOST), so a message was not sent.", file=sys.stderr)
            return False
        print(f"\n----- SGXray dev outbox (not sent) -----\nTo: {to}\nSubject: {subject}\n\n{text}\n"
              f"----------------------------------------\n", flush=True)
        return True
    msg = EmailMessage()
    msg["From"] = os.environ.get("SGXRAY_MAIL_FROM", "SGXray <no-reply@localhost>")
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    try:
        with smtplib.SMTP(os.environ["SGXRAY_SMTP_HOST"], int(os.environ.get("SGXRAY_SMTP_PORT", "587")),
                          timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())     # encrypted, and the server's certificate checked
            if os.environ.get("SGXRAY_SMTP_USER"):
                smtp.login(os.environ["SGXRAY_SMTP_USER"], os.environ.get("SGXRAY_SMTP_PASSWORD", ""))
            smtp.send_message(msg)
        return True
    except (OSError, smtplib.SMTPException) as e:                    # never print the message: it holds the link
        print(f"SGXray: sending an email failed ({type(e).__name__}).", file=sys.stderr)
        return False
