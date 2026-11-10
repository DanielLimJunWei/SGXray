// The background's soft pools of colour drift a little as you scroll, so the page isn't one flat
// colour and each part of it feels slightly different, quietly (the way Conoid and Doors do it).
// Only a CSS variable changes; with "reduce motion" on, the pools stay put.
(function () {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const root = document.documentElement;
  let queued = false;
  function update() {
    const max = root.scrollHeight - innerHeight;
    root.style.setProperty("--scroll", max > 0 ? (scrollY / max).toFixed(4) : "0");
    queued = false;
  }
  addEventListener("scroll", () => { if (!queued) { queued = true; requestAnimationFrame(update); } }, { passive: true });
  update();
})();
