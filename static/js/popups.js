// "What does this mean?" and "Watch out" boxes you can keep open beside a chart and move around.
// - They open in the bottom corner (out of the chart's way) and stay open until Close or Esc.
// - Drag them by the title bar, or focus the ⠿ handle and use the arrow keys (Shift = bigger steps).
// - A box you've moved reopens where you left it, for as long as the page is open.
// - Word-meaning boxes (tap a term) are the same boxes, but open centred under the word you tapped,
//   and only one is open at a time.
// - Every box always stays fully inside the visible page (the scrollbar doesn't count as space).
(function () {
  const pops = [...document.querySelectorAll(".pop")];
  if (!pops.length) return;
  document.documentElement.classList.add("pops-js");
  const PAD = 12;
  const viewW = () => document.documentElement.clientWidth;    // the page's width WITHOUT the scrollbar
  const viewH = () => document.documentElement.clientHeight;
  const openers = new Map();                                   // which button opened which box
  document.addEventListener("click", e => {
    const b = e.target.closest("[popovertarget]:not(.close)");
    if (b) openers.set(b.getAttribute("popovertarget"), b);
  }, true);

  function clamp(pop, left, top) {
    const w = pop.offsetWidth, h = pop.offsetHeight;
    left = Math.min(Math.max(PAD, left), viewW() - w - PAD);
    top = Math.min(Math.max(PAD, top), viewH() - Math.min(h, 56) - PAD);   // keep at least the title bar on screen
    pop.style.left = left + "px";
    pop.style.top = top + "px";
  }

  function openAtDefault(pop) {
    if (pop.classList.contains("term-pop")) { openUnderWord(pop); return; }
    const left = parseFloat(pop.style.left), top = parseFloat(pop.style.top);
    if (pop.dataset.moved && !isNaN(left) && !isNaN(top)) { clamp(pop, left, top); return; }
    const w = pop.offsetWidth, h = pop.offsetHeight;
    // Bottom-right on wide screens; along the bottom on phones. A second open box sits a little higher.
    const others = pops.filter(p => p !== pop && p.matches(":popover-open")).length;
    clamp(pop, viewW() - w - 24, viewH() - h - 24 - others * 48);
  }

  // A word's meaning opens centred under the word (or above it if there's no room below), fully on screen.
  function openUnderWord(pop) {
    pops.filter(p => p !== pop && p.classList.contains("term-pop") && p.matches(":popover-open")).forEach(p => p.hidePopover());
    const word = openers.get(pop.id);
    const w = pop.offsetWidth, h = pop.offsetHeight;
    if (!word) { clamp(pop, (viewW() - w) / 2, (viewH() - h) / 2); return; }
    const r = word.getBoundingClientRect();
    let top = r.bottom + 8;
    if (top + h > viewH() - PAD) top = r.top - 8 - h;          // no room below: open above
    if (top < PAD) top = PAD;
    clamp(pop, r.left + r.width / 2 - w / 2, top);
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
      w = Math.min(Math.max(MIN_W, w), viewW() - pop.offsetLeft - PAD);
      h = Math.min(Math.max(MIN_H, h), viewH() - pop.offsetTop - PAD);
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
