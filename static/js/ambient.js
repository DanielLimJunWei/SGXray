// The background's soft pools of colour drift a little as you scroll, so the page isn't one flat
// colour and each part of it feels slightly different, quietly (the way Conoid and Doors do it).
// Only a CSS variable changes; with "reduce motion" on, the pools stay put.
// The variable is set on the .ambient layer itself, not on <html>: a variable on <html> is inherited by
// every element, so each scroll frame made the browser recheck the styles of the whole page (about 3 ms a
// frame on the dashboard, measured; on the layer alone it's 0.02 ms). See docs/performance.md.
(function () {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const root = document.documentElement;
  const layer = document.querySelector(".ambient");
  if (!layer) return;
  let queued = false;
  function update() {
    const max = root.scrollHeight - innerHeight;
    layer.style.setProperty("--scroll", max > 0 ? (scrollY / max).toFixed(4) : "0");
    queued = false;
  }
  addEventListener("scroll", () => { if (!queued) { queued = true; requestAnimationFrame(update); } }, { passive: true });
  update();
})();
