"""Every page script must at least parse. A syntax error stops the WHOLE file from running (found 12 Nov
2026: a variable named twice broke every price chart, and the Python tests couldn't see it)."""

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = sorted((Path(__file__).resolve().parent.parent / "static" / "js").glob("*.js"))


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js isn't installed, so scripts can't be checked")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_the_script_parses(script):
    r = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
