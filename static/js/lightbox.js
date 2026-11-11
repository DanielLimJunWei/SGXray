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
  // "Show" / "Hide" on every password box, like other sites have, so you can check what you typed.
  // The button is added here (not in the page) so it only appears when it works. Before the form is
  // sent, every box goes back to hidden, so the browser never treats a password as ordinary text.
  document.querySelectorAll('input[type="password"]').forEach(field => {
    const wrap = document.createElement("span");
    wrap.className = "pw-field";
    field.before(wrap);
    wrap.append(field);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "pw-toggle";
    btn.textContent = "Show";
    btn.setAttribute("aria-controls", field.id);
    btn.setAttribute("aria-label", "Show password");
    btn.setAttribute("aria-pressed", "false");
    wrap.append(btn);
    const set = shown => {
      field.type = shown ? "text" : "password";
      btn.textContent = shown ? "Hide" : "Show";
      btn.setAttribute("aria-label", shown ? "Hide password" : "Show password");
      btn.setAttribute("aria-pressed", String(shown));
    };
    btn.addEventListener("mousedown", e => e.preventDefault());   // keep the cursor in the box
    btn.addEventListener("click", () => set(field.type === "password"));
    if (field.form) field.form.addEventListener("submit", () => set(false));
  });
  // On the log-in film the patient is "unidentified" until you start typing your email, when the
  // label quietly fills in with it, like a name being written on the film. Empty again: unidentified.
  document.querySelectorAll("[data-patient-from]").forEach(label => {
    const field = document.getElementById(label.dataset.patientFrom);
    if (!field) return;
    const show = () => { label.textContent = field.value.trim() || label.dataset.unknown; };
    field.addEventListener("input", show);
    show();
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
