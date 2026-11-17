// New closing prices, without refreshing (w410). Every couple of minutes, while the tab is open and visible,
// this asks /prices/latest for the newest close SGXray has. When it's newer than what the page shows:
//   1. it fetches the same page again in the background,
//   2. the key figures and the holdings' prices roll smoothly from the old close to the new one (up or
//      down, about a second, then they sit still),
//   3. then the rest of the page (tables, charts) is swapped for the new version and its charts redrawn,
//      and the "Prices as of" line glows faintly once.
// With "reduce motion" on, the numbers just change. Without JavaScript, a refresh shows the same thing.
(function () {
  const page = document.querySelector("[data-live-prices]");
  if (!page || !window.fetch) return;
  let shown = page.dataset.livePrices;
  const EVERY = 2 * 60 * 1000;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // "$22,695.20", "+$11,517.48", "▼ -$13.94", "69.720": the number inside some text, and how to write
  // another number the same way (same sign style, $ and decimals).
  function parts(text) {
    const m = text.match(/([▲▼]\s*)?([+-])?(\$)?([\d,]+(?:\.\d+)?)/);
    if (!m) return null;
    const decimals = (m[4].split(".")[1] || "").length;
    return { before: text.slice(0, m.index), after: text.slice(m.index + m[0].length), dollar: !!m[3], decimals,
             signed: !!m[2] };
  }
  function write(p, x, arrow) {
    const sign = x < 0 ? "-" : (p.signed && x > 0 ? "+" : "");
    const body = Math.abs(x).toLocaleString("en-SG", { minimumFractionDigits: p.decimals, maximumFractionDigits: p.decimals });
    return p.before.replace(/[▲▼]\s*$/, "") + (arrow ? arrow + " " : "") + sign + (p.dollar ? "$" : "") + body + p.after;
  }

  // Roll one number from its old value to the new one, then show the server's exact new text.
  function roll(el, from, to, finalHTML, finalClass) {
    const p = parts(el.textContent);
    if (reduce || !p || !isFinite(from) || !isFinite(to) || from === to) {
      el.innerHTML = finalHTML; if (finalClass !== null) el.className = finalClass; return Promise.resolve();
    }
    if (finalClass !== null) el.className = finalClass;               // the new colour (up / down) right away
    const arrow = to > 0 ? "▲" : to < 0 ? "▼" : "";
    const hasArrow = /[▲▼]/.test(el.textContent);
    const start = performance.now(), ms = 1100;
    return new Promise(done => {
      let finished = false;
      const finish = () => { if (!finished) { finished = true; el.innerHTML = finalHTML; done(); } };
      function step(now) {
        if (finished) return;
        const t = Math.min(1, (now - start) / ms), eased = 1 - Math.pow(1 - t, 3);
        el.textContent = write(p, from + (to - from) * eased, hasArrow ? arrow : "");
        if (t < 1) requestAnimationFrame(step); else finish();
      }
      requestAnimationFrame(step);
      // Browsers pause animation frames in a background tab: this makes sure the new number still lands.
      setTimeout(finish, ms + 400);
    });
  }

  // Scripts that draw charts and boxes: run again on the new page content. (count-up.js is left out, so
  // the numbers don't count up from zero again.)
  const REDRAW = ["reveal.js", "xray-chart.js", "stock-chart.js", "popups.js"];
  function redraw() {
    REDRAW.forEach(name => {
      const old = [...document.scripts].find(s => s.src.includes("/js/" + name));
      if (!old) return;
      const s = document.createElement("script");
      s.src = old.src.split("?")[0] + "?live=" + Date.now();
      document.body.appendChild(s);
    });
  }

  // Returns true once the page shows the new prices; false (try again later) if anything went wrong.
  async function update() {
    const r = await fetch(location.href, { credentials: "same-origin", cache: "no-store" });
    if (!r.ok || r.redirected) return false;                         // logged out meanwhile: leave the page alone
    const fresh = new DOMParser().parseFromString(await r.text(), "text/html");
    const next = fresh.querySelector("[data-live-prices]");
    if (!next) return false;
    // 1. Roll the figures and the holdings' prices and worth, matched in order.
    const pairs = [];
    const olds = [...page.querySelectorAll("[data-count], [data-roll]")];
    const news = [...next.querySelectorAll("[data-count], [data-roll]")];
    if (olds.length === news.length) {
      olds.forEach((el, i) => {
        const n = news[i], key = el.hasAttribute("data-count") ? "count" : "roll";
        pairs.push(roll(el, parseFloat(el.dataset[key]), parseFloat(n.dataset[key]), n.innerHTML, n.className));
      });
    }
    await Promise.all(pairs);
    // 2. Then the whole page content, so tables and charts show the new day too.
    page.innerHTML = next.innerHTML;
    page.dataset.livePrices = next.dataset.livePrices;
    const asOf = page.querySelector("[data-live-as-of]");
    if (asOf && !reduce) { asOf.classList.add("as-of-new"); setTimeout(() => asOf.classList.remove("as-of-new"), 2400); }
    redraw();
    return true;
  }

  // Only counts the new prices as shown once the page really shows them: if the page couldn't be fetched
  // (a dropped connection, a busy server), it tries again every 10 seconds, up to 3 times, and after that
  // at the next regular check.
  let busy = false, retries = 0;
  const later = () => { if (retries < 3) { retries++; setTimeout(check, 10000); } };
  async function check() {
    if (document.visibilityState !== "visible" || busy) return;
    busy = true;
    try {
      const r = await fetch("/prices/latest", { cache: "no-store" });
      if (r.ok) {
        const { version } = await r.json();
        if (version && version !== shown) {
          if (await update()) { shown = version; retries = 0; } else later();
        }
      }
    } catch (e) { later(); }                                          // offline for a moment
    busy = false;
  }
  setInterval(check, EVERY);
  document.addEventListener("visibilitychange", check);              // coming back to the tab checks straight away
})();
