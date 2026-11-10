// "What does this mean?" and "Watch out" boxes you can keep open beside a chart and move around.
// - They open in the bottom corner (out of the chart's way) and stay open until Close or Esc.
// - Drag them by the title bar, or focus the ⠿ handle and use the arrow keys (Shift = bigger steps).
// - A box you've moved reopens where you left it, for as long as the page is open.
(function () {
  const pops = [...document.querySelectorAll(".pop")];
  if (!pops.length) return;
  document.documentElement.classList.add("pops-js");
  const PAD = 12;

  function clamp(pop, left, top) {
    const w = pop.offsetWidth, h = pop.offsetHeight;
    left = Math.min(Math.max(PAD, left), innerWidth - w - PAD);
    top = Math.min(Math.max(PAD, top), innerHeight - Math.min(h, 56) - PAD);   // keep at least the title bar on screen
    pop.style.left = left + "px";
    pop.style.top = top + "px";
  }

  function openAtDefault(pop) {
    if (pop.dataset.moved) { clamp(pop, parseFloat(pop.style.left), parseFloat(pop.style.top)); return; }
    const w = pop.offsetWidth, h = pop.offsetHeight;
    // Bottom-right on wide screens; along the bottom on phones. A second open box sits a little higher.
    const others = pops.filter(p => p !== pop && p.matches(":popover-open")).length;
    clamp(pop, innerWidth - w - 24, innerHeight - h - 24 - others * 48);
  }

  pops.forEach(pop => {
    pop.addEventListener("toggle", e => { if (e.newState === "open") openAtDefault(pop); });   // it has its size by now

    // Drag by the title bar (mouse, pen or finger).
    const head = pop.querySelector("[data-drag]");
    head.addEventListener("pointerdown", e => {
      if (e.target.closest(".close")) return;
      e.preventDefault();
      const start = { x: e.clientX, y: e.clientY, left: pop.offsetLeft, top: pop.offsetTop };
      head.setPointerCapture(e.pointerId);
      head.classList.add("dragging");
      const move = ev => {
        clamp(pop, start.left + ev.clientX - start.x, start.top + ev.clientY - start.y);
        pop.dataset.moved = "1";
      };
      const up = () => {
        head.classList.remove("dragging");
        head.removeEventListener("pointermove", move);
        head.removeEventListener("pointerup", up);
        head.removeEventListener("pointercancel", up);
      };
      head.addEventListener("pointermove", move);
      head.addEventListener("pointerup", up);
      head.addEventListener("pointercancel", up);
    });

    // Move with the arrow keys from the ⠿ handle.
    pop.querySelector(".grip").addEventListener("keydown", e => {
      const step = e.shiftKey ? 80 : 20;
      const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
      if (!d) return;
      e.preventDefault();
      clamp(pop, pop.offsetLeft + d[0], pop.offsetTop + d[1]);
      pop.dataset.moved = "1";
    });
  });

  // Esc closes the most recently opened box (these boxes stay open otherwise).
  const order = [];
  pops.forEach(p => p.addEventListener("toggle", e => {
    const i = order.indexOf(p);
    if (i >= 0) order.splice(i, 1);
    if (e.newState === "open") order.push(p);
  }));
  document.addEventListener("keydown", e => {
    if (e.key !== "Escape" || !order.length) return;
    const pop = order[order.length - 1];
    pop.hidePopover();
    const opener = document.querySelector(`[popovertarget="${pop.id}"]:not(.close)`);
    if (opener) opener.focus();                        // put focus back where the person was
  });

  // Keep open boxes on screen if the window is resized or a phone is rotated.
  addEventListener("resize", () => pops.filter(p => p.matches(":popover-open"))
    .forEach(p => clamp(p, p.offsetLeft, p.offsetTop)));
})();
