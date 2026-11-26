"""Copies an SGXray SQLite database into PostgreSQL (w408), for moving to the live site once.

    DATABASE_URL=postgresql://... python src/move_to_postgres.py data/sgxray.db            # shared data only
    DATABASE_URL=postgresql://... python src/move_to_postgres.py data/sgxray.db --accounts # and every account

By default it copies what everyone shares: the stock list, prices, dividends, splits and news, plus the demo
portfolio (its account and trades), so the live site starts with the demo working. With --accounts it also
copies every account with its trades, plans, notes and lessons read. Sessions, failed log-ins, reset links and
the security log are never copied: they are short-lived, and the security log holds network addresses.

It refuses to run if the PostgreSQL database already has any trades or accounts, so it can't mix two
databases together. Row ids are kept, so every trade still points at its owner.
"""

import argparse
import os
import sqlite3
import sys

import db
import lessons
from updater import JOB_SQL

SHARED = ["instruments", "prices", "dividends", "corporate_actions", "announced_dividends", "news", "news_tickers",
          "history_wanted"]
ACCOUNTS = ["users", "plans", "trades", "lesson_reads", "goals", "feedback"]   # in this order: each points at the one before
NEVER = {"sessions", "login_attempts", "password_resets", "security_log", "jobs"}


def copy(src_path, accounts=False):
    if not os.environ.get("DATABASE_URL"):
        sys.exit("Set DATABASE_URL to the PostgreSQL database first.")
    src = sqlite3.connect(src_path)
    src.row_factory = sqlite3.Row
    dst = db.get_connection()
    db.init_db(dst)
    dst.execute(JOB_SQL)
    if dst.execute("SELECT (SELECT COUNT(*) FROM users) + (SELECT COUNT(*) FROM trades)").fetchone()[0]:
        sys.exit("The PostgreSQL database already has accounts or trades: refusing to mix two databases.")

    demo = lessons.demo_user_id(src)
    users = None if accounts else ([demo] if demo else [])
    counts = {}
    with dst:                                                       # all of it, or none of it
        for table in SHARED + ACCOUNTS:
            cols = sorted(db.columns(dst, table) & {r["name"] for r in src.execute(f"PRAGMA table_info({table})")})
            if not cols:                                            # an older file without this table: nothing to copy
                counts[table] = 0
                continue
            sql = f"SELECT {', '.join(cols)} FROM {table}"
            args = ()
            if table in ACCOUNTS and users is not None:             # shared data only: just the demo's rows
                if not users:
                    continue
                sql += f" WHERE {'id' if table == 'users' else 'user_id'} IN ({', '.join('?' * len(users))})"
                args = users
            if "id" in cols:
                sql += " ORDER BY id"                               # an owner before its practice twin
            rows = src.execute(sql, args).fetchall()
            dst.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                            [tuple(r[c] for c in cols) for r in rows])
            counts[table] = len(rows)
        # New rows must get ids after the copied ones: move each auto-numbered id past the highest copied.
        for table in ("users", "trades", "plans", "news"):
            dst.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)")
    src.close()
    dst.close()
    return counts


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sqlite_file")
    ap.add_argument("--accounts", action="store_true", help="also copy every account and its data")
    args = ap.parse_args()
    for table, n in copy(args.sqlite_file, args.accounts).items():
        print(f"{table:<18} {n:>6}")
