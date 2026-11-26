# Speed log

Every speed change tried on SGXray, kept or not, so a dead idea isn't tried twice. Each was measured before and
after the same way; a change that didn't beat the run-to-run wobble was undone, even if it seemed obvious.

How the server time was measured: `/demo` (the demo dashboard) through Flask's test client on a copy of the
database, 10 views after one warm-up, the median taken, old and new code run in turn three times.

| Change | Before → after | Kept? | Why |
|---|---|---|---|
| Work out holdings and dividends once per page view (`portfolio.shared_results`) | 427–511 ms → 203–216 ms per dashboard | kept | One dashboard was working out your holdings 24 times and your dividends 37 times. Same page, byte for byte (apart from the one-time security tokens). |
| Scroll glow: set `--scroll` on the `.ambient` layer, not on `<html>` (`static/js/ambient.js`) | 3.2–3.7 ms → 0.02–0.03 ms of style work per scroll frame on the dashboard (2,572 elements) | kept | A variable on `<html>` is inherited by every element, so every scroll frame rechecked the whole page. A smooth frame has 16.7 ms in all. The glows drift exactly as before. Measured in the browser by setting the value 200 times and forcing the styles to be worked out each time. |
| Home page 3D scene: one drawing loop only (`drawSoon()` in `static/js/home-scene.js`) | 60 → 90 → 120 draw requests a second after each return to the tab → 60 every time | kept | A bug, not a tweak. The browser keeps a hidden tab's booked frame, and coming back booked another, so each tab switch added a loop that drew the whole scene again. With 2 or more loops frames were dropped. Tested by sending the "tab visible again" signal while the first loop was still running. |
| Only write the glossary popups a page uses | 0.6 ms of the dashboard's ~210 ms server time; 33 of 84 popups unused, about 4 KB after compression | not done | Too small to matter. Closed popups cost the browser nothing to lay out or draw, and live price updates would then need to add popups the fresh page brings. |
| Minified Three.js | 2.1 MB uncompressed locally | not done | three 0.186.1's official package has no minified build, and minifying it ourselves would break the "official files, unchanged" check (`tests/test_vendor.py`). Render compresses every response with Brotli or gzip, which shrinks it most of the way. |
| Nav bar without its background blur | not measured | not done | The browser pane draws at most 30 frames a second while it isn't in front, so frame times from it mean nothing. Re-measure with Chrome's Performance panel before changing anything. |
