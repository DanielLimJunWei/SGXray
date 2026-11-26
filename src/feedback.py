"""Feedback (s06): a short form linked from every page's footer. What's confusing, what's wrong, what you'd like.

Saved in the `feedback` table with the page it came from and, if you were logged in, your account (so a reply can
go to your account's email). If you weren't, you can leave an email for a reply, or not. Nothing is emailed yet:
read it here.

    python src/feedback.py                 the newest 50
    python src/feedback.py delete 12       remove one you've dealt with
"""

import re
import sys

import db

EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{2,}$")
PER_HOUR = 5              # messages per person or network address in an hour


def clean_page(path):
    """The page the form was opened from: a path on this site only (never another address), or None."""
    path = str(path or "").strip()[:200]
    if not path.startswith("/") or path.startswith("//") or "\\" in path or any(c in path for c in "\r\n\t"):
        return None
    return path


def from_form(form, logged_in):
    """(values, problems) from the feedback form."""
    problems = []
    message = str(form.get("message", "")).replace("\r\n", "\n").strip()
    if not message:
        problems.append("Write a few words first.")
    elif len(message) > db.FEEDBACK_MAX:
        problems.append(f"That's longer than {db.FEEDBACK_MAX:,} characters. Shorten it a little.")
    reply_to = None
    if not logged_in:
        reply_to = str(form.get("reply_to", "")).strip()[:254] or None
        if reply_to and not EMAIL.match(reply_to):
            problems.append("That email address doesn't look right. Check it, or leave it empty.")
    return {"message": message, "reply_to": reply_to, "page": clean_page(form.get("page"))}, problems


def main(argv=None):
    from fmt import safe_console
    safe_console()
    argv = argv if argv is not None else sys.argv[1:]
    conn = db.get_connection()
    db.init_db(conn)
    if argv[:1] == ["delete"] and len(argv) == 2:
        print("Deleted." if db.delete_feedback(conn, int(argv[1])) else "No feedback with that number.")
        return 0
    rows = db.get_feedback(conn)
    if not rows:
        print("No feedback yet.")
    for r in rows:
        who = r["account"] or r["reply_to"] or "no reply address"
        print(f"#{r['id']}  {r['created_at']}  {r['page'] or '-'}  ({who})\n    {r['message']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
