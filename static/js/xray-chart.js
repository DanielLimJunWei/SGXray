// The X-ray chart: your portfolio's line, split into your money, price gains and dividends,
// with the STI ETF (same money, same days) as a dashed line.
//
// The chart shows as it is, finished. The X-ray (the plain line splitting into your money, gains and dividends)
// runs only when you press Scan: the "X-ray in use" lamp lights, the chart tilts back a little in 3D like a film laid
// on a lightbox, a glowing light tube sweeps across, and the chart settles flat as the layers' names come in. With "reduce motion" on there's nothing to animate, so Scan stays hidden.
// (Before 26 Nov 2026 it played by itself on first view, with Animation on/off and Replay buttons.)
(function () {
  const dataEl = document.getElementById("xray-data");
  if (!dataEl) return;
  const DATA = JSON.parse(dataEl.textContent);
  if (!DATA.length) return;
  const $ = id => document.getElementById(id);
  const svg = $("xray-chart"), card = svg.closest(".chart-card"), tip = $("xray-tip");
  // Under 3 months of history the chart has a point for every trading day (one month end alone would be a
  // single dot); after that, one point per month.
  const unit = DATA[0].unit === "day" ? "day" : "month";
  const NS = "http://www.w3.org/2000/svg";
  const el = (tag, attrs, text) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (text) e.textContent = text;
    return e;
  };

  // ---------- Size ----------
  // The drawing is 340 units tall and normally 800 wide. On a short window (a laptop at 150% scaling is 1280 x 665)
  // its height is capped so the whole card fits on screen; instead of shrinking the drawing and leaving empty space
  // either side, the drawing gets wider: longer lines, the same text size, nothing stretched. Worked out once, on load.
  // RESERVED is the rest of what must fit, measured: the top bar (64), the section title and lead (78), the numbers
  // row and the card's padding (138), and a little air.
  const BASE_W = 800, BASE_H = 340, RESERVED = 296;
  const boxW = svg.getBoundingClientRect().width || BASE_W;
  const capH = Math.max(240, innerHeight - RESERVED);
  const W = boxW * BASE_H / BASE_W > capH ? Math.round(BASE_H * boxW / capH) : BASE_W;
  svg.setAttribute("viewBox", `0 0 ${W} ${BASE_H}`);

  // ---------- Geometry ----------
  const H = 300, LEFT = 64, RIGHT = W - 110;            // 110 on the right for the layers' names
  const money = DATA.map(d => d.money);
  const gainsTop = DATA.map(d => d.money + d.gains);
  const total = DATA.map(d => d.money + d.gains + d.divs);
  const sti = DATA.map(d => d.sti);
  const hasSti = sti.every(v => v !== null);
  const all = [0, ...money, ...gainsTop, ...total, ...(hasSti ? sti : [])];

  // Round the axis to a "nice" step (1, 2, 2.5 or 5 x a power of ten) so the labels read cleanly.
  function niceStep(range) {
    const raw = range / 4, mag = Math.pow(10, Math.floor(Math.log10(raw || 1)));
    return [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw);
  }
  const step = niceStep(Math.max(...all) - Math.min(...all));
  const minY = Math.floor(Math.min(...all) / step) * step, maxY = Math.ceil(Math.max(...all) / step) * step;
  const x = i => DATA.length === 1 ? (LEFT + RIGHT) / 2 : LEFT + (RIGHT - LEFT) * i / (DATA.length - 1);
  const y = v => H - ((v - minY) / (maxY - minY || 1)) * (H - 16);
  const line = vals => vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
  const band = (lo, hi) => line(hi) + " " + lo.map((v, i) => [i, v]).reverse()
    .map(([i, v]) => `L${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ") + " Z";

  $("xray-plain").setAttribute("d", line(total));
  $("xray-money").setAttribute("d", band(DATA.map(() => 0), money));
  $("xray-gains").setAttribute("d", band(money, gainsTop));
  $("xray-divs").setAttribute("d", band(gainsTop, total));
  $("xray-top").setAttribute("d", line(total));
  if (hasSti) {
    $("xray-sti").setAttribute("d", line(sti));
    $("xray-sti-halo").setAttribute("d", line(sti));     // a dark outline so the dashed line reads over the dots
  }

  // Axis: horizontal rules with dollar labels, and a few month labels along the bottom.
  const short = v => v === 0 ? "$0" : (v < 0 ? "-" : "") + "$" + (Math.abs(v) >= 1000 ? Math.abs(v) / 1000 + "k" : Math.abs(v));
  const axis = $("xray-axis");
  for (let v = minY; v <= maxY + step / 2; v += step) {
    axis.append(el("line", { x1: LEFT, x2: RIGHT, y1: y(v), y2: y(v) }));
    axis.append(el("text", { x: LEFT - 8, y: y(v) + 4, "text-anchor": "end" }, short(v)));
  }
  const ticks = DATA.length <= 4 ? DATA.map((_, i) => i)
    : [0, 1, 2, 3].map(k => Math.round(k * (DATA.length - 1) / 3));
  const shown = new Set();
  ticks.forEach(i => { if (shown.has(DATA[i].label)) return; shown.add(DATA[i].label);
    axis.append(el("text", { x: x(i), y: H + 22, "text-anchor": "middle" }, DATA[i].label)); });
  // Axis titles: what the numbers up the side and along the bottom are.
  axis.append(el("text", { class: "axis-title", x: LEFT - 8, y: -2, "text-anchor": "end" }, "S$"));
  axis.append(el("text", { class: "axis-title", x: (LEFT + RIGHT) / 2, y: H + 40, "text-anchor": "middle" }, unit === "day" ? "Each trading day" : "Month end"));
  // From a lesson (spotlight.js): shade the demo's biggest fall, and/or make the line itself stand out.
  const spot = document.querySelector("[data-spot-bar]");
  if (spot && spot.dataset.spotBand && DATA.length > 1) {
    const [from, to] = spot.dataset.spotBand.split(",");
    const t = iso => new Date(iso + "T00:00:00").getTime();
    const xAt = iso => {                                   // between two points: in proportion to the date
      const v = t(iso), ts = DATA.map(d => t(d.date));
      if (v <= ts[0]) return x(0);
      for (let i = 1; i < ts.length; i++) if (v <= ts[i]) return x(i - 1) + (x(i) - x(i - 1)) * (v - ts[i - 1]) / (ts[i] - ts[i - 1]);
      return x(last);
    };
    const mid = (xAt(from) + xAt(to)) / 2, half = Math.max((xAt(to) - xAt(from)) / 2, 7);   // at least 14px wide
    const x0 = mid - half, x1 = mid + half;
    const shade = el("rect", { class: "spot-band", x: x0, y: 0, width: x1 - x0, height: H });
    axis.after(shade);
    $("xray-labels").before(el("text", { class: "spot-band-label", x: (x0 + x1) / 2, y: 12, "text-anchor": "middle" }, "the fall"));
  }
  if (spot && spot.hasAttribute("data-spot-line")) svg.classList.add("spot-line");
  // A single point: a line needs two, so it shows as a dot (inside the reveal, so it scans in like the rest).
  if (DATA.length === 1) $("xray-top").after(el("circle", { cx: x(0), cy: y(total[0]), r: 4, fill: "#9CC4FF" }));

  // Layer names at the right edge, pushed apart so they never overlap.
  const last = DATA.length - 1, mid = (a, b) => y((a + b) / 2) + 4;
  const LABELS = [
    { at: 0.82, text: "dividends", color: "#E3A35E", y: y(total[last]) - 6 },
    hasSti && { at: 0.9, text: "STI ETF ---", color: "#EEE7DC", y: y(sti[last]) + 4 },
    { at: 0.78, text: "price gains", color: "#9CC4FF", y: mid(money[last], gainsTop[last]) },
    { at: 0.74, text: "your money", color: "#9AA3B5", y: mid(0, money[last]) },
  ].filter(Boolean).sort((a, b) => a.y - b.y);
  LABELS.forEach((l, i) => { if (i && l.y < LABELS[i - 1].y + 16) l.y = LABELS[i - 1].y + 16; });
  LABELS.forEach(l => { l.node = el("text", { x: RIGHT + 10, y: l.y, fill: l.color, opacity: 0 }, l.text); $("xray-labels").append(l.node); });

  // Keep chart text about 12px on screen however small the chart gets; on phones the steps act as the key.
  function fitText() {
    const scale = svg.clientWidth / W;
    svg.style.setProperty("--svg-text", `${Math.min(20, 12 / scale)}px`);
    card.classList.toggle("narrow", scale < 0.6);
  }
  addEventListener("resize", fitText);
  fitText();

  // ---------- The reveal: p goes 0 -> 1 ----------
  const steps = [...document.querySelectorAll("#xray-steps .step")];
  const lamp = $("xray-lamp");
  function render(p) {
    // The beam sweeps from 12% to 72% of the time, easing in and out (like a scanner arm starting and stopping)
    // rather than jumping to full speed.
    const t = Math.min(1, Math.max(0, (p - 0.12) / 0.6));
    const reveal = 0.5 - Math.cos(Math.PI * t) / 2;
    const sx = LEFT + (RIGHT - LEFT + 10) * reveal;
    $("xray-reveal-rect").setAttribute("width", t >= 1 ? W : sx);
    $("xray-scanline").setAttribute("transform", `translate(${sx} 0)`);
    $("xray-scanline").setAttribute("opacity", reveal > 0 && reveal < 1 ? 1 : 0);
    if (lamp) lamp.classList.toggle("on", p > 0.02 && p < 0.8);
    $("xray-plain").setAttribute("opacity", 1 - reveal * 0.85);
    const stiOn = hasSti ? Math.min(1, Math.max(0, (p - 0.84) / 0.1)) : 0;       // the market comes in last
    $("xray-sti").setAttribute("opacity", stiOn);
    $("xray-sti-halo").setAttribute("opacity", stiOn * 0.8);
    LABELS.forEach(l => l.node.setAttribute("opacity", Math.min(1, Math.max(0, (p - l.at) / 0.05))));   // fade in
    steps.forEach(s => s.classList.toggle("on", p >= +s.dataset.at));
  }

  // ---------- Scan: the sweep, on demand ----------
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const scanBtn = $("xray-scan");
  let frame = null;

  const scanLabel = scanBtn && scanBtn.querySelector("[data-scan-label]");
  function play() {
    cancelAnimationFrame(frame);
    const start = performance.now(), ms = 5200;
    scanBtn.disabled = true;
    if (scanLabel) scanLabel.textContent = "Scanning";
    // If any of the chart is off screen, bring it into view first, so the whole scan can be seen.
    const box = card.getBoundingClientRect();
    if (box.top < 56 || box.bottom > innerHeight) card.scrollIntoView({ block: "center", behavior: "smooth" });
    card.classList.remove("scanning");
    void card.offsetWidth;                          // restart the tilt if Scan is pressed again
    card.classList.add("scanning");
    const tick = now => {
      const p = Math.min(1, (now - start) / ms);
      render(p);
      if (p < 1) frame = requestAnimationFrame(tick);
      else { scanBtn.disabled = false; card.classList.remove("scanning"); if (scanLabel) scanLabel.textContent = "Scan"; }
    };
    frame = requestAnimationFrame(tick);
  }
  render(1);                                  // as it is
  if (scanBtn && !reduce) {
    scanBtn.hidden = false;
    scanBtn.addEventListener("click", play);
  }

  // ---------- Point at a month (mouse, touch or arrow keys) to see its numbers ----------
  const cursor = $("xray-cursor"), fmt = v => (v < 0 ? "-" : "") + "$" + Math.abs(v).toLocaleString("en-SG", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const signed = v => (v > 0 ? "+" : "") + fmt(v);
  const longDate = iso => new Date(iso + "T00:00:00").toLocaleDateString("en-SG", { day: "numeric", month: "long", year: "numeric" });
  let current = null;

  function show(i, resting) {
    current = Math.max(0, Math.min(last, i));
    svg.dataset.cursor = current;
    const d = DATA[current], cx = x(current);
    cursor.setAttribute("opacity", 1);
    $("xray-cursor-line").setAttribute("opacity", resting ? 0 : 1);     // resting on the latest point: just its dot
    $("xray-cursor-line").setAttribute("x1", cx); $("xray-cursor-line").setAttribute("x2", cx);
    $("xray-cursor-dot").setAttribute("cx", cx); $("xray-cursor-dot").setAttribute("cy", y(total[current]));
    const rows = [["Your money", fmt(d.money)], ["Price gains", signed(d.gains)], ["Dividends", fmt(d.divs)],
                  ["All together", fmt(total[current])]];
    if (hasSti) rows.push(["STI ETF", fmt(d.sti)]);
    tip.textContent = "";                                 // built with text nodes only: never HTML from data
    const head = document.createElement("b"); head.textContent = (resting ? "Latest: " : "") + longDate(d.date); tip.append(head);
    rows.forEach(([k, v]) => {
      const r = document.createElement("div"), a = document.createElement("span"), b = document.createElement("span");
      a.textContent = k; b.textContent = v; r.append(a, b); tip.append(r);
    });
    if (resting) {
      const hint = document.createElement("span"); hint.className = "idle";
      hint.textContent = `Point at any ${unit} (or tap it) to see its numbers. Double-click up to 3 ${unit}s to compare them.`;
      tip.append(hint);
    }
  }
  // Back to the latest point whenever the pointer leaves: the numbers never disappear.
  function hide() { show(last, true); current = null; delete svg.dataset.cursor; }
  hide();

  svg.addEventListener("pointermove", e => {
    const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(svg.getScreenCTM().inverse());
    show(Math.round((pt.x - LEFT) / ((RIGHT - LEFT) / Math.max(1, last))));
  });
  svg.addEventListener("pointerleave", e => { if (e.pointerType === "mouse") hide(); });
  svg.addEventListener("focus", () => show(current ?? last));
  svg.addEventListener("blur", hide);
  svg.addEventListener("keydown", e => {
    const moves = { ArrowLeft: -1, ArrowRight: 1, Home: -Infinity, End: Infinity };
    if (!(e.key in moves)) return;
    e.preventDefault();
    const m = moves[e.key];
    show(isFinite(m) ? (current ?? last) + m : (m < 0 ? 0 : last));
  });

  // ---------- Compare up to 3 months: what grew, and how much of it was your own money ----------
  const C = window.SGXrayCompare;
  if (C) C({
    svg, panel: $("xray-compare"), count: DATA.length, title: "X-ray chart", baseY: H,
    xy: i => [x(i), y(total[i])],
    indexAt: e => {
      const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(svg.getScreenCTM().inverse());
      return Math.max(0, Math.min(last, Math.round((pt.x - LEFT) / ((RIGHT - LEFT) / Math.max(1, last)))));
    },
    describe: (a, b) => {
      const A = DATA[a], B = DATA[b];
      const grew = total[b] - total[a], money = B.money - A.money, earned = grew - money;
      const parts = [
        { text: `${C.short(A.date)} to ${C.short(B.date)}` },
        { text: `All together ${C.money(total[a])} → ${C.money(total[b])} (${C.signed(grew)})` },
        { text: `your own money ${C.signed(money)}` },
        { text: `earned ${C.signed(earned)}: price gains ${C.signed(B.gains - A.gains)}, dividends ${C.signed(B.divs - A.divs)}`, cls: C.trend(earned) },
      ];
      if (hasSti) parts.push({ text: `STI ETF version ${C.signed(B.sti - A.sti)}` });
      return parts;
    },
  });
})();
