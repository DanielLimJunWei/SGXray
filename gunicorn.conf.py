"""Gunicorn, the web server that runs SGXray on the live site (w403). `flask run` is only for your own computer.

Render tells the app which port to use in PORT. Two worker processes, each answering up to 4 requests at
once, fit Render's free and starter servers (512 MB). Each worker starts the price checker, and the lock in the
`jobs` table makes sure only one of them downloads at a time.
"""

import os

import gunicorn.http.wsgi

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = 4
timeout = 60                      # a request taking longer than this is stuck: the worker is restarted
graceful_timeout = 20
max_requests = 1000               # each worker is renewed now and then, so a slow memory leak can't build up
max_requests_jitter = 100

# No access log: every visited address would be written out, including one-time "reset your password" links.
accesslog = None
errorlog = "-"

# Gunicorn 25+ opens a control socket for its `gunicornc` tool in the user's home folder. SGXray doesn't use it,
# and the container's user has no home folder, so it's switched off.
control_socket_disable = True

# The Server header names the software but not its version; call it SGXray, so it says nothing (audit 4b, check 106).
gunicorn.http.wsgi.SERVER = "SGXray"
