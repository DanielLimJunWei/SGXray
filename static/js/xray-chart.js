// The X-ray chart: your portfolio's line, split into your money, price gains and dividends,
// with the STI ETF (same money, same days) as a dashed line.
//
// Motion rules: the reveal plays ONCE when the chart first comes into view, then everything
// stays still (these are real daily closes, not live prices). People can replay it, or turn the
// animation off; that choice is remembered on this device. "Reduce motion" turns it off by default.
(function () {
  const dataEl = document.getElementById("xray-data");
  if (!dataEl) return;
  const DATA = JSON.parse(dataEl.textContent);
  if (!DATA.length) return;
  const $ = id => document.getElementById(id);
  const svg = $("xray-chart"), card = svg.closest(".chart-card"), tip = $("xray-tip");
  const idle = () => { tip.textContent = ""; const i = document.createElement("span"); i.className = "idle"; i.textContent = 'Point at any month (or tap it) to see its numbers here. Double-click up to 3 months to compare them.'; tip.append(i); };
  const NS = "http://www.w3.org/2000/svg";
  const el = (tag, attrs, text) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (text) e.textContent = text;
    return e;
  };

  // ---------- Geometry ----------
  const H = 300, LEFT = 64, RIGHT = 690;
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
  ticks.forEach(i => axis.append(el("text", { x: x(i), y: H + 22, "text-anchor": "middle" }, DATA[i].label)));
  // Axis titles: what the numbers up the side and along the bottom are.
  axis.append(el("text", { class: "axis-title", x: LEFT - 8, y: -2, "text-anchor": "end" }, "S$"));
  axis.append(el("text", { class: "axis-title", x: (LEFT + RIGHT) / 2, y: H + 40, "text-anchor": "middle" }, "Month end"));

  // Layer names at the right edge, pushed apart so they never overlap.
  const last = DATA.length - 1, mid = (a, b) => y((a + b) / 2) + 4;
  const LABELS = [
    { at: 0.62, text: "dividends", color: "#E3A35E", y: y(total[last]) - 6 },
    hasSti && { at: 0.85, text: "STI ETF ---", color: "#EEE7DC", y: y(sti[last]) + 4 },
    { at: 0.5, text: "price gains", color: "#9CC4FF", y: mid(money[last], gainsTop[last]) },
    { at: 0.3, text: "your money", color: "#9AA3B5", y: mid(0, money[last]) },
  ].filter(Boolean).sort((a, b) => a.y - b.y);
  LABELS.forEach((l, i) => { if (i && l.y < LABELS[i - 1].y + 16) l.y = LABELS[i - 1].y + 16; });
  LABELS.forEach(l => { l.node = el("text", { x: RIGHT + 10, y: l.y, fill: l.color, opacity: 0 }, l.text); $("xray-labels").append(l.node); });

  // Keep chart text about 12px on screen however small the chart gets; on phones the steps act as the key.
  function fitText() {
    const scale = svg.clientWidth / 800;
    svg.style.setProperty("--svg-text", `${Math.min(20, 12 / scale)}px`);
    card.classList.toggle("narrow", scale < 0.6);
  }
  addEventListener("resize", fitText);
  fitText();

  // ---------- The reveal: p goes 0 -> 1 ----------
  const steps = [...document.querySelectorAll("#xray-steps .step")];
  function render(p) {
    const reveal = Math.min(1, Math.max(0, (p - 0.12) / 0.6));      // the scan sweeps from 12% to 72%
    const sx = LEFT + (RIGHT - LEFT + 10) * reveal;
    $("xray-reveal-rect").setAttribute("width", reveal >= 1 ? 800 : sx);
    $("xray-scanline").setAttribute("transform", `translate(${sx} 0)`);
    $("xray-scanline").setAttribute("opacity", reveal > 0 && reveal < 1 ? 1 : 0);
    $("xray-plain").setAttribute("opacity", 1 - reveal * 0.85);
    const stiOn = hasSti ? Math.min(1, Math.max(0, (p - 0.78) / 0.12)) : 0;
    $("xray-sti").setAttribute("opacity", stiOn);
    $("xray-sti-halo").setAttribute("opacity", stiOn * 0.8);
    LABELS.forEach(l => l.node.setAttribute("opacity", p >= l.at ? 1 : 0));
    steps.forEach(s => s.classList.toggle("on", p >= +s.dataset.at));
  }

  // ---------- Animation on/off, remembered on this device ----------
  const KEY = "sgxray-motion";
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) { /* private mode: just use the default */ }
  let motionOn = saved ? saved === "on" : !reduce;
  const motionBtn = $("xray-motion"), replayBtn = $("xray-replay");
  let frame = null;

  function play() {
    cancelAnimationFrame(frame);
    if (!motionOn) { render(1); return; }
    const start = performance.now(), ms = 4200;
    const tick = now => {
      const p = Math.min(1, (now - start) / ms);
      render(p);
      if (p < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
  }
  function showMotionState() {
    motionBtn.setAttribute("aria-pressed", String(motionOn));
    motionBtn.textContent = "Animation: " + (motionOn ? "on" : "off");
    replayBtn.hidden = !motionOn;
  }
  motionBtn.hidden = false;
  showMotionState();
  motionBtn.addEventListener("click", () => {
    motionOn = !motionOn;
    try { localStorage.setItem(KEY, motionOn ? "on" : "off"); } catch (e) { /* not saved; still works now */ }
    document.documentElement.classList.toggle("motion-off", !motionOn);    // other charts follow the same choice
    showMotionState();
    if (!motionOn) { cancelAnimationFrame(frame); render(1); }
  });
  replayBtn.addEventListener("click", play);

  // Play once, the first time at least 40% of the chart is on screen.
  if (motionOn && "IntersectionObserver" in window) {
    render(0);
    const io = new IntersectionObserver(entries => {
      if (entries.some(e => e.isIntersecting)) { io.disconnect(); play(); }
    }, { threshold: 0.4 });
    io.observe(svg);
  } else {
    render(1);
  }

  // ---------- Point at a month (mouse, touch or arrow keys) to see its numbers ----------
  const cursor = $("xray-cursor"), fmt = v => (v < 0 ? "-" : "") + "$" + Math.abs(v).toLocaleString("en-SG", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const signed = v => (v > 0 ? "+" : "") + fmt(v);
  const longDate = iso => new Date(iso + "T00:00:00").toLocaleDateString("en-SG", { day: "numeric", month: "long", year: "numeric" });
  let current = null;

  function show(i) {
    current = Math.max(0, Math.min(last, i));
    svg.dataset.cursor = current;
    const d = DATA[current], cx = x(current);
    cursor.setAttribute("opacity", 1);
    $("xray-cursor-line").setAttribute("x1", cx); $("xray-cursor-line").setAttribute("x2", cx);
    $("xray-cursor-dot").setAttribute("cx", cx); $("xray-cursor-dot").setAttribute("cy", y(total[current]));
    const rows = [["Your money", fmt(d.money)], ["Price gains", signed(d.gains)], ["Dividends", fmt(d.divs)],
                  ["All together", fmt(total[current])]];
    if (hasSti) rows.push(["STI ETF", fmt(d.sti)]);
    tip.textContent = "";                                 // built with text nodes only: never HTML from data
    const head = document.createElement("b"); head.textContent = longDate(d.date); tip.append(head);
    rows.forEach(([k, v]) => {
      const r = document.createElement("div"), a = document.createElement("span"), b = document.createElement("span");
      a.textContent = k; b.textContent = v; r.append(a, b); tip.append(r);
    });
  }
  function hide() { cursor.setAttribute("opacity", 0); idle(); current = null; delete svg.dataset.cursor; }

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
