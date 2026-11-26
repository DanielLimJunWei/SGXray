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


def test_scrolling_never_restyles_the_whole_page():
    """A CSS variable set on <html> is inherited by every element, so setting one on each scroll frame made the
    browser recheck the whole page's styles every frame (3.3 ms a frame on the dashboard, measured 26 Nov 2026;
    0.02 ms on the glow layer alone). Scroll-driven values go on the one element that uses them."""
    for script in SCRIPTS:
        src = script.read_text(encoding="utf-8")
        assert "documentElement.style.setProperty" not in src, script.name
        assert "root.style.setProperty" not in src, script.name


def test_the_home_scene_never_runs_two_drawing_loops():
    """Every request to draw goes through drawSoon(), which books at most one frame. Calling
    requestAnimationFrame(frame) directly let each return to the tab start another loop on top of the one the
    browser was holding (measured 26 Nov 2026: 60 draws a second became 90, then 120, and frames dropped)."""
    src = (SCRIPTS[0].parent / "home-scene.js").read_text(encoding="utf-8")
    assert src.count("requestAnimationFrame(") == 1
    assert "function drawSoon() { if (!booked) booked = requestAnimationFrame(frame); }" in src
