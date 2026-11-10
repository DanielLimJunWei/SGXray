import * as THREE from "three";
import { Line2 } from "three/addons/lines/Line2.js";
import { LineMaterial } from "three/addons/lines/LineMaterial.js";
import { LineGeometry } from "three/addons/lines/LineGeometry.js";

// ============================================================
// SGXray home scene: ONE stock chart, built as a 3D object.
// Like Conoid's single wire form, the chart keeps its shape;
// scrolling moves the camera: wide view -> zoom in while a scan
// line reveals the numbers -> the line splits into its three
// layers (the X-ray) -> pull back. Pure decoration: made-up data.
// ============================================================

const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const small = innerWidth < 720;
const N = small ? 150 : 220;            // trading days on the chart
const W = 16;                           // chart width in scene units (x from -8 to 8)
const BASE = -3.0;                      // floor of the price area
const xAt = j => (j / (N - 1) - 0.5) * W;

// Smooth scrolling. `anchors` makes the nav links (What it does, The X-ray, Learn, Back to top) glide
// there instead of jumping, so the 3D chart travels smoothly through each stage on the way, like Conoid.
// easeInOutCubic: starts gently, moves, then settles gently. Longer trips get a little more time.
const easeInOutCubic = t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
if (!reduceMotion && window.Lenis) {
  const lenis = new window.Lenis({ autoRaf: true });
  document.querySelectorAll('a[href^="#"]').forEach(link => link.addEventListener("click", e => {
    const target = document.querySelector(link.getAttribute("href"));
    if (!target) return;
    e.preventDefault();
    const distance = Math.abs(target.getBoundingClientRect().top) / innerHeight;    // in screen-heights
    lenis.scrollTo(target, {
      duration: Math.min(2.4, 1.1 + distance * 0.35), easing: easeInOutCubic,
      onComplete: () => {                                        // keyboard users continue from the section they chose
        if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
        target.focus({ preventScroll: true });
      },
    });
    history.replaceState(null, "", link.getAttribute("href"));                   // keep the address bar in step
  }));
}

// ---------- Renderer, scene, camera ----------
const canvas = document.getElementById("scene");
let renderer;
try {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "low-power" });
} catch (e) { canvas.remove(); throw e; }
renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
const scene = new THREE.Scene();
scene.fog = new THREE.Fog(0x0A0F1E, 12, 34);
const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
const chart = new THREE.Group();
scene.add(chart);

const C = { glow: 0x3A73FF, soft: 0x9CC4FF, lamp: 0xE3A35E, up: 0x7BC4A0, down: 0xD98282, text: 0xEEE7DC, slate: 0x7F93C2 };

// ---------- The made-up price history (same every visit) ----------
let seed = 11;
const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
const bump = (u, at, w) => Math.exp(-((u - at) ** 2) / (2 * w * w));
const price = [];
let noise = 0;
for (let j = 0; j < N; j++) {
  const u = j / (N - 1);
  noise = noise * 0.9 + (rand() - 0.5) * 0.2;
  // An uptrend with two pullbacks (a gentle one, then a sharp one) and a recovery.
  price.push(-1.9 + 3.5 * u - 0.75 * bump(u, 0.38, 0.045) - 1.35 * bump(u, 0.69, 0.03) + 0.25 * Math.sin(u * 11) + noise);
}
const ma = price.map((_, j) => { const a = price.slice(Math.max(0, j - 17), j + 1); return a.reduce((s, v) => s + v, 0) / a.length; });
const toPrice = y => 2.4 + y * 0.32;                       // scene height -> a dollar price, for the labels
const money = n => "$" + n.toFixed(2);

// ---------- Helpers ----------
const lineMats = [];
function fatLine(ys, color, width, opacity, z = 0) {
  const pts = [];
  ys.forEach((y, j) => pts.push(xAt(j), y, z));
  const g = new LineGeometry(); g.setPositions(pts);
  const m = new LineMaterial({ color, linewidth: width, transparent: true, opacity, depthWrite: false, blending: THREE.AdditiveBlending });
  lineMats.push(m);
  const l = new Line2(g, m); l.computeLineDistances(); return l;
}
function segments(pts, color, opacity) {
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
  return new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color, transparent: true, opacity, depthWrite: false, blending: THREE.AdditiveBlending }));
}
function area(ys, color, z) {                              // soft glass sheet under a line, fading downward
  const pos = [], col = [], idx = [], c = new THREE.Color(color);
  ys.forEach((y, j) => {
    pos.push(xAt(j), y, z, xAt(j), BASE, z);
    col.push(c.r, c.g, c.b, 0.22, c.r, c.g, c.b, 0);
    if (j) { const a = (j - 1) * 2; idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
  });
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("color", new THREE.Float32BufferAttribute(col, 4));
  g.setIndex(idx);
  return new THREE.Mesh(g, new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, opacity: 0, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending }));
}

// ---------- The chart itself ----------
// Grid: faint price levels and time columns.
const grid = [];
for (let y = -2.5; y <= 2.6; y += 1) grid.push(-W / 2, y, -0.4, W / 2, y, -0.4);
for (let x = -W / 2; x <= W / 2 + 0.01; x += 2) grid.push(x, BASE - 0.9, -0.4, x, 2.8, -0.4);
const gridLines = segments(grid, C.soft, 0.07);
chart.add(gridLines);

// Price bars: a high-low stick with small ticks for the open (left) and close (right), like a trading screen.
const bars = [], dx = W / N * 0.38;
for (let j = 1; j < N; j++) {
  const o = price[j - 1], c = price[j], x = xAt(j);
  const hi = Math.max(o, c) + rand() * 0.1, lo = Math.min(o, c) - rand() * 0.1;
  bars.push(x, lo, 0, x, hi, 0, x - dx, o, 0, x, o, 0, x, c, 0, x + dx, c, 0);
}
const barLines = segments(bars, C.glow, 0.6);
chart.add(barLines);

// Volume: thin bars along the bottom; taller on big price moves.
const vol = [];
for (let j = 1; j < N; j++) {
  const h = Math.min(0.85, 0.08 + rand() * 0.22 + Math.abs(price[j] - price[j - 1]) * 2.6);
  vol.push(xAt(j), BASE - 0.9, 0.2, xAt(j), BASE - 0.9 + h, 0.2);
}
const volLines = segments(vol, C.glow, 0.35);
chart.add(volLines);

const priceLine = fatLine(price, C.soft, 1.6, 0.9);      // the closing price
const maLine = fatLine(ma, C.lamp, 1.3, 0.75, 0.05);     // the moving average: the one warm line
chart.add(priceLine, maLine);

// ---------- The X-ray layers: the same line, split into what's inside ----------
const moneyIn = price.map((_, j) => { const u = j / (N - 1); return -2.5 + 0.5 * [0, 0.18, 0.42, 0.66].filter(s => u >= s).length; });
const divs = price.map((_, j) => price[j] + 0.32 * Math.floor((j / (N - 1)) * 6) / 6 + 0.06);
const layers = [
  { ys: moneyIn, color: C.slate, z: 1.8, name: "MONEY IN", fill: 0.3 },
  { ys: price, color: C.soft, z: 0, name: "+ PRICE GAINS" },
  { ys: divs, color: C.lamp, z: -1.8, name: "+ DIVIDENDS" },
].map(L => {
  L.line = fatLine(L.ys, L.color, 1.8, 0, 0); L.sheet = area(L.ys, L.color, 0);
  chart.add(L.line, L.sheet); return L;
});
const dollars = y => (y + 3.2) * 2400;
layers[0].value = "$" + Math.round(dollars(moneyIn[N - 1])).toLocaleString("en-SG");
layers[1].value = "+$" + Math.round(dollars(price[N - 1]) - dollars(moneyIn[N - 1])).toLocaleString("en-SG");
layers[2].value = "+$" + Math.round(dollars(divs[N - 1]) - dollars(price[N - 1])).toLocaleString("en-SG");

// ---------- Scan line: sweeps across as you zoom in, revealing the numbers ----------
const scanGeo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, BASE - 0.9, 0.3), new THREE.Vector3(0, 2.9, 0.3)]);
const scan = new THREE.Line(scanGeo, new THREE.LineBasicMaterial({ color: C.soft, transparent: true, opacity: 0, blending: THREE.AdditiveBlending }));
const scanBand = new THREE.Mesh(new THREE.PlaneGeometry(0.9, 6.7), new THREE.MeshBasicMaterial({ color: C.glow, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }));
scanBand.position.set(0, -0.45, 0.28);
chart.add(scan, scanBand);

// ---------- Text labels (drawn once into small canvases) ----------
function label(text, color, size = 0.24, weight = 500) {
  const cv = document.createElement("canvas"), g = cv.getContext("2d"), px = 40;
  g.font = `${weight} ${px}px "JetBrains Mono", monospace`;
  cv.width = Math.ceil(g.measureText(text).width) + 8; cv.height = px + 16;
  g.font = `${weight} ${px}px "JetBrains Mono", monospace`;
  g.fillStyle = "#" + new THREE.Color(color).getHexString(); g.textBaseline = "middle"; g.fillText(text, 4, cv.height / 2);
  const tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, opacity: 0, depthWrite: false, depthTest: false, fog: false }));
  s.scale.set(size * cv.width / cv.height, size, 1);
  return s;
}
function dot(color) {
  const cv = document.createElement("canvas"); cv.width = cv.height = 32;
  const g = cv.getContext("2d"); g.fillStyle = "#" + new THREE.Color(color).getHexString();
  g.beginPath(); g.arc(16, 16, 9, 0, Math.PI * 2); g.fill();
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(cv), transparent: true, opacity: 0, depthWrite: false, depthTest: false, fog: false }));
  s.scale.setScalar(0.11); return s;
}
const idxOf = (a, b, pick) => { let best = Math.round(a * (N - 1)); for (let j = Math.round(a * (N - 1)); j <= Math.round(b * (N - 1)); j++) if (pick(price[j], price[best])) best = j; return best; };
const notes = [];                                          // { sprite, dot, x }: revealed when the scan passes x
let axis = [], layerLabels = [];
document.fonts.load('500 40px "JetBrains Mono"').finally(() => {
  const pkA = idxOf(0.26, 0.37, (a, b) => a > b), trA = idxOf(0.36, 0.46, (a, b) => a < b);
  const pkC = idxOf(0.55, 0.68, (a, b) => a > b), trC = idxOf(0.66, 0.74, (a, b) => a < b), end = N - 1;
  const pct = (a, b) => ((toPrice(price[b]) / toPrice(price[a]) - 1) * 100);
  const sign = v => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(1) + "%";
  const add = (j, text, color, above, y = price[j]) => {
    const s = label(text, color), d = dot(color), x = xAt(j);
    s.position.set(x, y + (above ? 0.42 : -0.42), 0.3); d.position.set(x, y, 0.3);
    chart.add(s, d); notes.push({ sprite: s, dot: d, x });
  };
  add(pkA, money(toPrice(price[pkA])), C.text, true);
  add(trA, sign(pct(pkA, trA)), C.down, false);
  add(pkC, money(toPrice(price[pkC])) + "  " + sign(pct(trA, pkC)), C.up, true);
  add(trC, sign(pct(pkC, trC)), C.down, false);
  const ex = Math.round(0.52 * (N - 1)); add(ex, "EX-DATE · $0.06", C.lamp, false, BASE - 0.15);
  const mj = Math.round(0.86 * (N - 1)); add(mj, "MA 18", C.lamp, false, ma[mj]);
  add(end, "LAST " + money(toPrice(price[end])), C.text, true);
  add(Math.round(0.03 * (N - 1)), "VOL", C.soft, true, BASE - 0.75);
  // Price axis on the right: always there, faint.
  for (let y = -2.5; y <= 2.6; y += 1) { const s = label(toPrice(y).toFixed(2), C.soft, 0.2, 400); s.position.set(W / 2 + 0.75, y, -0.4); chart.add(s); axis.push(s); }
  // The X-ray layer names, shown when the layers split apart.
  layerLabels = layers.map(L => { const s = label(L.name + "  " + L.value, L.color, 0.26); chart.add(s); return s; });
});

// ---------- Up/down arrows that fade in and out on the price line ----------
function arrowTexture(up, color) {
  const c = document.createElement("canvas"); c.width = c.height = 64;
  const g = c.getContext("2d"); g.fillStyle = color; g.beginPath();
  if (up) { g.moveTo(32, 12); g.lineTo(54, 50); g.lineTo(10, 50); } else { g.moveTo(32, 52); g.lineTo(54, 14); g.lineTo(10, 14); }
  g.closePath(); g.fill();
  return new THREE.CanvasTexture(c);
}
const upTex = arrowTexture(true, "#7BC4A0"), downTex = arrowTexture(false, "#D98282");
const arrows = Array.from({ length: small ? 4 : 6 }, () => {
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: upTex, transparent: true, opacity: 0, depthWrite: false, fog: true }));
  s.scale.setScalar(0.3); s.userData = { born: -99, life: 2 }; chart.add(s); return s;
});
let nextArrow = 0;

// ---------- The "live" end of the line: the last few days ripple gently ----------
const liveFrom = N - 12;
function setPoint(line, j, y) {                            // move one point of a Line2 without rebuilding it
  const arr = line.geometry.attributes.instanceStart.data;
  if (j > 0) arr.array[(j - 1) * 6 + 4] = y;
  if (j < N - 1) arr.array[j * 6 + 1] = y;
  arr.needsUpdate = true;
}
const liveY = (j, t) => price[j] + Math.sin(t * 1.1 + j * 0.9) * 0.07 * ((j - liveFrom) / 11);

// ---------- Camera path: the chart stays put, the camera travels ----------
const KEYS = [
  { p: 0.00, pos: [-1.2, 1.6, 15.5], look: [0, -0.4, 0] },     // the whole chart, behind the headline
  { p: 0.28, pos: [1.6, 0.7, 7.2], look: [-0.4, -0.1, 0] },    // zoomed in: the scan reveals the numbers
  { p: 0.55, pos: [7, 0.6, 15.5], look: [2.6, 1.2, 0] },      // side view: the layers split apart (the X-ray)
  { p: 0.80, pos: [-8.5, 2.2, 10], look: [-2.4, -0.4, 0] },    // round the other side
  { p: 1.00, pos: [0, 0.8, 16.5], look: [0, -0.4, 0] },        // back to the whole chart, calm
];
const smooth = x => x * x * (3 - 2 * x);
const clamp01 = x => Math.min(1, Math.max(0, x));
const camPos = new THREE.Vector3(), camLook = new THREE.Vector3(), va = new THREE.Vector3(), vb = new THREE.Vector3();
let fit = 1;
function cameraAt(p) {
  let i = 0; while (i < KEYS.length - 2 && p > KEYS[i + 1].p) i++;
  const a = KEYS[i], b = KEYS[i + 1], s = smooth(clamp01((p - a.p) / (b.p - a.p)));
  camLook.fromArray(a.look).lerp(vb.fromArray(b.look), s);
  camPos.fromArray(a.pos).lerp(va.fromArray(b.pos), s);
  camPos.sub(camLook).multiplyScalar(fit).add(camLook);        // phones: stand further back
  turnAroundChart(camPos, camLook);                            // the visitor's own turn (drag), if any
  camera.position.copy(camPos); camera.lookAt(camLook);
}

// ---------- Drag to turn the chart, all the way round ----------
// Holding the left mouse button on an empty part of the page turns the chart. It's done by swinging
// the CAMERA around the chart's centre (with its aim point), so the chart keeps its shape and every
// scroll stage (the zoom, the scan, the X-ray layers) still lands on the same part of the chart,
// whichever way it's been turned. Left and right turn it a full 360 degrees and beyond; up and down
// tilt it a little (never upside down). Let go mid-swing and it keeps spinning, then slows to a stop:
// a hard flick spins far, a gentle push barely coasts. Double-click an empty spot to turn it back.
const PIVOT = new THREE.Vector3(0, -0.4, 0), UP = new THREE.Vector3(0, 1, 0);
const PITCH_MIN = -0.3, PITCH_MAX = 0.45;       // tilt limits, in radians (about -17 to +26 degrees)
const FRICTION = 1.6;                           // how quickly a spin slows: speed halves about every 0.4 s
const MAX_SPIN = 9;                             // the fastest spin, in radians a second (about 1.4 turns)
const turn = { yaw: 0, pitch: 0, toYaw: 0, toPitch: 0, vYaw: 0, vPitch: 0, dragging: false };
const samples = [];                             // the last fraction of a second of dragging, to measure the flick
const qYaw = new THREE.Quaternion(), qPitch = new THREE.Quaternion(), right = new THREE.Vector3(), fwd = new THREE.Vector3();
function turnAroundChart(pos, look) {
  if (!turn.yaw && !turn.pitch) return;
  fwd.subVectors(look, pos);
  right.crossVectors(fwd, UP).normalize();                     // "sideways" as the camera sees it
  qYaw.setFromAxisAngle(UP, turn.yaw);
  right.applyQuaternion(qYaw);
  qPitch.setFromAxisAngle(right, turn.pitch);
  qPitch.multiply(qYaw);
  for (const v of [pos, look]) v.sub(PIVOT).applyQuaternion(qPitch).add(PIVOT);
}
let lastTurnTime = null;
function easeTurn(now) {
  const dt = lastTurnTime === null ? 0 : Math.min(0.05, (now - lastTurnTime) / 1000);   // seconds since last frame
  lastTurnTime = now;
  if (!turn.dragging && !reduceMotion) {                       // coasting after a flick
    turn.toYaw += turn.vYaw * dt;
    turn.toPitch += turn.vPitch * dt;
    const keep = Math.exp(-FRICTION * dt);                     // the same slow-down whatever the frame rate
    turn.vYaw *= keep; turn.vPitch *= keep;
    if (Math.abs(turn.vYaw) < 0.01) turn.vYaw = 0;
  }
  if (turn.toPitch < PITCH_MIN || turn.toPitch > PITCH_MAX) {  // tilting stops softly at its limit
    turn.toPitch = Math.max(PITCH_MIN, Math.min(PITCH_MAX, turn.toPitch));
    turn.vPitch = 0;
  }
  const k = reduceMotion ? 1 : 1 - Math.exp(-20 * dt);         // the view follows the hand closely, without jitter
  turn.yaw += (turn.toYaw - turn.yaw) * k;
  turn.pitch += (turn.toPitch - turn.pitch) * k;
}
// Only empty space starts a drag: text, buttons, links and the panels keep working as normal.
// Only the letters themselves and clickable things stop a turn: the empty space beside a short line,
// or the padding inside a panel, still turns the chart. That makes turning smooth almost anywhere.
const CLICKABLE = "a, button, summary, input, textarea, select, label, nav, footer";
function onLetters(x, y) {
  // Find the character nearest the point, then check the point is really inside that character's box.
  let node, offset;
  if (document.caretPositionFromPoint) {
    const c = document.caretPositionFromPoint(x, y); if (!c) return false;
    node = c.offsetNode; offset = c.offset;
  } else if (document.caretRangeFromPoint) {
    const r = document.caretRangeFromPoint(x, y); if (!r) return false;
    node = r.startContainer; offset = r.startOffset;
  }
  if (!node || node.nodeType !== Node.TEXT_NODE || !node.textContent.trim()) return false;
  const range = document.createRange();
  for (const i of [offset - 1, offset]) {
    if (i < 0 || i >= node.length) continue;
    range.setStart(node, i); range.setEnd(node, i + 1);
    for (const b of range.getClientRects()) {
      if (x >= b.left - 2 && x <= b.right + 2 && y >= b.top - 2 && y <= b.bottom + 2) return true;
    }
  }
  return false;
}
// What's under the pointer: "click" (a link or button), "text" (letters), or "turn" (anything else).
function under(x, y, target) {
  if (target && target.closest && target.closest(CLICKABLE)) return "click";
  return onLetters(x, y) ? "text" : "turn";
}
const finePointer = matchMedia("(hover: hover) and (pointer: fine)").matches;   // mouse or trackpad, not touch
if (finePointer) {
  document.documentElement.classList.add("can-turn");
  let last = null;
  const speed = () => Math.PI / Math.max(innerWidth, 600);    // a full-width drag turns it half way round
  const startsTurn = e => e.button === 0 && e.pointerType !== "touch" && under(e.clientX, e.clientY, e.target) === "turn";
  // The cursor follows the same rule: open hand to turn, arrow on letters, pointing hand on clickable things.
  addEventListener("pointermove", e => {
    if (turn.dragging || e.pointerType === "touch") return;
    const over = under(e.clientX, e.clientY, e.target);
    if (document.documentElement.dataset.over !== over) document.documentElement.dataset.over = over;
  }, { passive: true });
  const clearSelection = () => { const sel = getSelection(); if (sel && sel.rangeCount) sel.removeAllRanges(); };
  // Text selection starts on mousedown, a separate event from pointerdown, so stop it there too.
  addEventListener("mousedown", e => { if (startsTurn(e)) e.preventDefault(); });
  addEventListener("selectstart", e => { if (turn.dragging) e.preventDefault(); });
  addEventListener("pointerdown", e => {
    if (!startsTurn(e)) return;
    e.preventDefault();
    clearSelection();                                          // a click on empty space clears any old highlight, as usual
    turn.dragging = true; turn.vYaw = turn.vPitch = 0;         // grabbing a spinning chart stops it, like a real object
    turn.toYaw = turn.yaw; turn.toPitch = turn.pitch;
    last = { x: e.clientX, y: e.clientY };
    samples.length = 0;
    samples.push({ t: e.timeStamp, yaw: turn.toYaw, pitch: turn.toPitch });
    document.documentElement.classList.add("turning");
  });
  addEventListener("pointermove", e => {
    if (!turn.dragging) return;
    const dx = e.clientX - last.x, dy = e.clientY - last.y;
    last = { x: e.clientX, y: e.clientY };
    turn.toYaw -= dx * speed();
    turn.toPitch = Math.max(PITCH_MIN, Math.min(PITCH_MAX, turn.toPitch + dy * speed()));
    samples.push({ t: e.timeStamp, yaw: turn.toYaw, pitch: turn.toPitch });
    while (samples.length > 2 && e.timeStamp - samples[0].t > 100) samples.shift();   // keep the last 0.1 s
    if (reduceMotion) requestAnimationFrame(frame);
  });
  const stop = e => {
    if (!turn.dragging) return;
    turn.dragging = false;
    document.documentElement.classList.remove("turning");
    clearSelection();
    // The flick: how fast the chart was turning over the last 0.1 s. Holding still before letting go = no spin.
    const now = e && e.timeStamp ? e.timeStamp : performance.now();
    const first = samples[0], newest = samples[samples.length - 1];
    const span = first && newest ? (newest.t - first.t) / 1000 : 0;
    const fresh = newest && now - newest.t < 60;
    if (!reduceMotion && fresh && span > 0.008) {
      const clampSpin = v => Math.max(-MAX_SPIN, Math.min(MAX_SPIN, v));
      turn.vYaw = clampSpin((newest.yaw - first.yaw) / span);
      turn.vPitch = clampSpin((newest.pitch - first.pitch) / span) * 0.5;   // tilting coasts less
    } else {
      turn.vYaw = turn.vPitch = 0;
    }
    if (reduceMotion) requestAnimationFrame(frame);
  };
  addEventListener("pointerup", stop);
  addEventListener("pointercancel", stop);
  addEventListener("blur", () => stop());
  addEventListener("dblclick", e => {
    if (under(e.clientX, e.clientY, e.target) !== "turn") return;
    // Back to the start the short way round (after three full spins, don't unwind all three).
    const full = Math.PI * 2;
    turn.yaw -= Math.round(turn.yaw / full) * full;
    turn.toYaw = turn.toPitch = turn.vYaw = turn.vPitch = 0;
    if (reduceMotion) { turn.yaw = turn.pitch = 0; requestAnimationFrame(frame); }
  });
}

function scrollProgress() {
  const max = document.documentElement.scrollHeight - innerHeight;
  return max > 0 ? clamp01(scrollY / max) : 0;
}
function resize() {
  const w = innerWidth, h = innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h; camera.updateProjectionMatrix();
  fit = camera.aspect < 1.2 ? 1 + (1.2 - camera.aspect) * 1.1 : 1;
  for (const m of lineMats) m.resolution.set(w, h);
}
addEventListener("resize", resize);
resize();

let pe = scrollProgress();                                      // eased scroll, so the camera glides
function frame(now) {
  const t = reduceMotion ? 0 : now / 1000;
  const p = scrollProgress();
  pe += (p - pe) * (reduceMotion ? 1 : 0.07);
  easeTurn(now);
  cameraAt(pe);

  // Gentle float: the chart breathes a little but never changes shape.
  chart.rotation.y = Math.sin(t * 0.12) * 0.035;
  chart.position.y = Math.sin(t * 0.3) * 0.05;

  // Zoom stage: the scan sweeps left to right; each number appears once the scan has passed it.
  const reveal = clamp01((pe - 0.06) / 0.1) * (1 - clamp01((pe - 0.86) / 0.1) * 0.7);
  const sweep = clamp01((pe - 0.08) / 0.22);
  const scanX = -W / 2 - 0.5 + sweep * (W + 1);
  const scanOn = Math.sin(Math.PI * sweep) * (sweep > 0 && sweep < 1 ? 1 : 0);
  scan.position.x = scanBand.position.x = scanX;
  scan.material.opacity = scanOn * 0.7; scanBand.material.opacity = scanOn * 0.08;
  const xr = smooth(clamp01((pe - 0.38) / 0.14)) * (1 - smooth(clamp01((pe - 0.72) / 0.12)));   // X-ray amount
  for (const n of notes) {
    const a = reveal * clamp01((scanX - n.x) / 0.8) * (1 - xr);
    n.sprite.material.opacity = a * 0.92; n.dot.material.opacity = a * 0.9;
  }
  for (const s of axis) s.material.opacity = 0.32 + reveal * 0.25;

  // X-ray stage: the price line splits into money in / gains / dividends, spread out in depth.
  layers.forEach((L, i) => {
    const z = L.z * xr;
    L.line.position.z = L.sheet.position.z = z;
    L.line.material.opacity = xr * 0.95; L.sheet.material.opacity = xr * (L.fill ?? 0.55);
    const s = layerLabels[i];
    if (s) { const j = Math.round([0.2, 0.04, 0.47][i] * (N - 1)); s.position.set(xAt(j) + s.scale.x / 2, L.ys[j] + [-0.4, 0.45, 0.5][i], z); s.material.opacity = xr * 0.95; }
  });
  barLines.material.opacity = 0.6 * (1 - xr * 0.7);
  volLines.material.opacity = 0.35 * (1 - xr * 0.6);
  priceLine.material.opacity = 0.9 * (1 - xr);
  maLine.material.opacity = 0.75 * (1 - xr * 0.8);

  // The live tail.
  if (!reduceMotion) for (let j = liveFrom; j < N; j++) setPoint(priceLine, j, liveY(j, t));

  // Arrows: green where the line is rising, red where it's falling; each fades in and out.
  if (!reduceMotion && t > nextArrow) {
    const m = arrows.find(s => t - s.userData.born > s.userData.life);
    if (m) {
      const j = 4 + Math.floor(rand() * (N - 8)), rising = price[j + 3] > price[j - 3];
      m.material.map = rising ? upTex : downTex;
      m.position.set(xAt(j), price[j] + (rising ? 0.38 : -0.38), 0.25);
      m.userData = { born: t, life: 1.6 + rand() * 0.8 };
    }
    nextArrow = t + 0.45 + rand() * 0.6;
  }
  for (const m of arrows) {
    const age = t - m.userData.born;
    m.material.opacity = age > m.userData.life ? 0 : Math.sin(Math.PI * age / m.userData.life) * 0.85 * (1 - xr);
  }

  renderer.render(scene, camera);
  if (!reduceMotion && !document.hidden) requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
document.addEventListener("visibilitychange", () => { if (!document.hidden && !reduceMotion) requestAnimationFrame(frame); });
if (reduceMotion) {
  addEventListener("scroll", () => requestAnimationFrame(frame), { passive: true });
  document.fonts.ready.then(() => requestAnimationFrame(frame));
}
