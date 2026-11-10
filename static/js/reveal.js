// Charts drawn on the server (like dividends by year) grow in ONCE when they first come into view.
// The same "Animation: on/off" choice as the X-ray chart applies (saved on this device), and
// "reduce motion" turns it off. Without this script, or with animation off, charts just show, finished.
(function () {
  const root = document.documentElement;
  // Keep text inside server-drawn charts about 12px on screen, however small the chart is shrunk.
  const fit = () => document.querySelectorAll("svg.bars-chart").forEach(svg => {
    const scale = svg.clientWidth / svg.viewBox.baseVal.width;
    if (scale) svg.style.setProperty("--svg-text", `${Math.min(30, 12 / scale)}px`);
  });
  addEventListener("resize", fit);
  fit();
  let saved = null;
  try { saved = localStorage.getItem("sgxray-motion"); } catch (e) { /* private mode */ }
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const on = saved ? saved === "on" : !reduce;
  root.classList.toggle("motion-off", !on);
  if (!on || !("IntersectionObserver" in window)) return;
  root.classList.add("reveal-js");
  const io = new IntersectionObserver(entries => entries.forEach(e => {
    if (e.isIntersecting) { e.target.classList.add("in-view"); io.unobserve(e.target); }
  }), { threshold: 0.4 });
  document.querySelectorAll("[data-reveal]").forEach(el => io.observe(el));
})();
