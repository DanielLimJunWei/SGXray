"""The container and the live-site server settings (w403): what goes into the image, who it runs as, and the
settings that keep secrets out of it."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_the_live_site_refuses_to_start_without_a_secret_key(monkeypatch, tmp_path):
    import app as app_module
    from flask import Flask
    monkeypatch.delenv("SGXRAY_SECRET_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example.com/sgxray")
    with pytest.raises(RuntimeError, match="SGXRAY_SECRET_KEY"):
        app_module._secret_key(Flask("t", instance_path=str(tmp_path)))
    monkeypatch.setenv("SGXRAY_SECRET_KEY", "set-in-render")
    assert app_module._secret_key(Flask("t", instance_path=str(tmp_path))) == "set-in-render"


def test_the_image_holds_only_what_the_site_needs():
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "*" in ignore                                                            # everything out, then allow-list
    allowed = {line[1:] for line in ignore if line.startswith("!")}
    assert allowed == {"app.py", "gunicorn.conf.py", "requirements.lock", "src/", "templates/", "static/",
                       "data/demo_trades.csv"}                                      # no database, secret key, .env


def test_the_container_runs_as_an_ordinary_user_from_a_pinned_image():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "@sha256:" in dockerfile.split("FROM", 1)[1].splitlines()[0]
    assert "\nUSER sgxray\n" in dockerfile and "requirements.lock" in dockerfile


def test_the_server_keeps_no_access_log_and_names_no_version():
    conf = (ROOT / "gunicorn.conf.py").read_text(encoding="utf-8")
    assert "accesslog = None" in conf                                               # reset links never logged
    assert 'gunicorn.http.wsgi.SERVER = "SGXray"' in conf
