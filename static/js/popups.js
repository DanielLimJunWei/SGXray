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
    const left = parseFloat(pop.style.left), top = parseFloat(pop.style.top);
    if (pop.dataset.moved && !isNaN(left) && !isNaN(top)) { clamp(pop, left, top); return; }
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
      try { head.setPointerCapture(e.pointerId); } catch (err) { /* keep dragging without capture */ }
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

    // Resize from the bottom-right corner: drag it, or use the arrow keys on it.
    const grip = pop.querySelector("[data-resize]");
    const MIN_W = 240, MIN_H = 140;
    function size(w, h) {
      w = Math.min(Math.max(MIN_W, w), innerWidth - pop.offsetLeft - PAD);
      h = Math.min(Math.max(MIN_H, h), innerHeight - pop.offsetTop - PAD);
      pop.style.width = w + "px";
      pop.style.height = h + "px";
      pop.style.maxHeight = "none";                    // the size you chose wins over the default cap
      pop.dataset.moved = "1";                         // keep this spot and size when it reopens
    }
    if (grip) {
      grip.addEventListener("pointerdown", e => {
        e.preventDefault();
        const start = { x: e.clientX, y: e.clientY, w: pop.offsetWidth, h: pop.offsetHeight };
        try { grip.setPointerCapture(e.pointerId); } catch (err) { /* keep resizing without capture */ }
        const move = ev => size(start.w + ev.clientX - start.x, start.h + ev.clientY - start.y);
        const up = () => { grip.removeEventListener("pointermove", move); grip.removeEventListener("pointerup", up); grip.removeEventListener("pointercancel", up); };
        grip.addEventListener("pointermove", move);
        grip.addEventListener("pointerup", up);
        grip.addEventListener("pointercancel", up);
      });
      grip.addEventListener("keydown", e => {
        const step = e.shiftKey ? 80 : 20;
        const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
        if (!d) return;
        e.preventDefault();
        size(pop.offsetWidth + d[0], pop.offsetHeight + d[1]);
      });
    }

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
