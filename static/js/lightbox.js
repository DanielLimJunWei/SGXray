// The lightbox behind the film: it dims while you type a password (like covering the film, so the
// moment you type something private the screen goes quiet), and brightens as you log in, just before
// the page changes. With "reduce motion" on, it still dims and brightens, just without the fade.
(function () {
  const box = document.querySelector("[data-lightbox]");
  if (!box) return;
  document.querySelectorAll("[data-private]").forEach(field => {
    // The lightbox AND the desk lamp in the corner go down while you type something private.
    field.addEventListener("focus", () => { box.classList.add("dim"); document.documentElement.classList.add("lamp-off"); });
    field.addEventListener("blur", () => { box.classList.remove("dim"); document.documentElement.classList.remove("lamp-off"); });
  });
  const form = document.querySelector("[data-login-form]");
  if (!form) return;
  let sending = false;
  form.addEventListener("submit", e => {
    if (sending || !form.checkValidity()) return;
    e.preventDefault();
    sending = true;
    box.classList.remove("dim");
    document.documentElement.classList.remove("lamp-off");
    box.classList.add("lit");                          // the film lights up: it's yours now
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    setTimeout(() => form.submit(), reduce ? 0 : 380);
  });
})();
