# SGXray as a container (w403): the same build on your computer and on Render.
#
#   docker build -t sgxray .
#   docker compose up        (SGXray + a PostgreSQL database, like the live site; see docker-compose.yml)
#
# The base image is pinned by its digest, not just its name, so a rebuild can't silently pick up a changed image.
FROM python:3.14.7-slim@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# The libraries first, from the lock file (exact versions), so code changes don't reinstall them.
COPY requirements.lock .
RUN pip install -r requirements.lock

# Only what the site needs to run: no tests, docs, databases, secrets or Git history (see .dockerignore).
COPY app.py gunicorn.conf.py ./
COPY src/ src/
COPY templates/ templates/
COPY static/ static/
COPY data/demo_trades.csv data/

# Run as an ordinary user, never root: a bug in the app then can't change the system inside the container.
RUN useradd --system --uid 10001 --no-create-home sgxray \
    && mkdir -p /app/instance \
    && chown sgxray /app/instance /app/data
USER sgxray

EXPOSE 8000
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
