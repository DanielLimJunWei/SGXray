"""The home page's libraries are served by SGXray itself, unchanged from their npm packages (audit 4).

Each file's sha256 must match the table in static/vendor/README.md, no page may load a script or stylesheet from
another site, and the Content Security Policy allows scripts from SGXray only.
"""

import hashlib
import re
from pathlib import Path

from test_trades import app, db_path, downloads  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "static" / "vendor"


def test_every_library_file_is_exactly_as_published():
    table = re.findall(r"^\| `([^`]+)` \| [\d,]+ \| `([0-9a-f]{64})` \|$", (VENDOR / "README.md").read_text(encoding="utf-8"), re.M)
    assert len(table) >= 10
    for name, sha in table:
        assert hashlib.sha256((VENDOR / name).read_bytes()).hexdigest() == sha, name
    on_disk = {f.relative_to(VENDOR).as_posix() for f in VENDOR.rglob("*") if f.is_file() and f.name != "README.md"}
    assert on_disk == {name for name, _ in table}, "a library file isn't listed (or a listed one is missing)"


def test_no_page_loads_code_or_styles_from_another_site():
    for page in (ROOT / "templates").rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        outside = re.findall(r'<(?:script|link)[^>]+(?:src|href)="(https?:)?//', text)
        assert not outside, page.name
        assert "jsdelivr" not in text, page.name


def test_the_home_page_uses_the_libraries_served_here_and_scripts_only_from_here(app):
    r = app.test_client().get("/")
    page = r.get_data(as_text=True)
    assert "/static/vendor/three-0.186.1/build/three.module.js" in page
    assert "/static/vendor/lenis-1.3.26/lenis.min.js" in page
    csp = r.headers["Content-Security-Policy"]
    script_src = re.search(r"script-src ([^;]+)", csp).group(1)
    assert "http" not in script_src and "http" not in csp
    for path in ("/static/vendor/three-0.186.1/build/three.core.js", "/static/vendor/three-0.186.1/examples/jsm/lines/LineSegments2.js"):
        assert app.test_client().get(path).status_code == 200
