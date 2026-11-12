// Jump to a section (the "Sections" button): a smooth but quick scroll, up or down, instead of a long manual
// scroll or a sudden jump. Every trip takes about the same short time whatever the distance (0.35 to 0.7s),
// easing in and out. With "reduce motion" on, it goes straight there. Sections hidden in Simple view
// aren't listed while Simple is on.
(function () {
  const reduce = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const NAV_GAP = 96;                                   // land clear of the fixed top bar
  const ease = t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);   // ease in, then out

  function glide(toY) {
    const fromY = scrollY, dist = toY - fromY;
    if (reduce() || Math.abs(dist) < 4) { scrollTo(0, toY); return; }
    const ms = Math.min(700, Math.max(350, Math.abs(dist) * 0.12));
    const start = performance.now();
    let done = false;
    const stop = () => { done = true; };
    addEventListener("wheel", stop, { once: true, passive: true });            // the person scrolls: let go
    addEventListener("touchstart", stop, { once: true, passive: true });
    function step(now) {
      if (done) return;
      const t = Math.min(1, (now - start) / ms);
      scrollTo(0, fromY + dist * ease(t));
      if (t < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
    setTimeout(() => { if (!done) scrollTo(0, toY); }, ms + 300);              // lands even if frames are paused
  }

  document.addEventListener("click", e => {
    const link = e.target.closest("[data-jump]");
    if (!link) return;
    e.preventDefault();
    const menu = link.closest("[popover]");
    if (menu && menu.hidePopover) menu.hidePopover();
    const id = link.dataset.jump;
    if (id === "top") { glide(0); return; }
    const target = document.getElementById(id);
    if (!target) return;
    glide(Math.max(0, target.getBoundingClientRect().top + scrollY - NAV_GAP));
    history.replaceState(null, "", "#" + id);
    target.setAttribute("tabindex", "-1");
    target.focus({ preventScroll: true });                                     // keyboard users land there too
  });

  // Only list sections that are actually showing (Simple view hides some).
  const menu = document.getElementById("jump-menu");
  if (menu) menu.addEventListener("toggle", e => {
    if (e.newState !== "open") return;
    menu.querySelectorAll("[data-jump]").forEach(a => {
      const t = a.dataset.jump === "top" ? null : document.getElementById(a.dataset.jump);
      a.hidden = a.dataset.jump !== "top" && (!t || t.offsetParent === null);   // missing, or hidden in Simple
    });
  });
})();
