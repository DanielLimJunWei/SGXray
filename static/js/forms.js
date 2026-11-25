// One click, one save (audit 4). Clicking "Add trade" twice quickly sent the form twice, and the trade was saved
// twice: the holding doubled. Once a form is on its way, its buttons pause until the next page arrives.
// Forms that send themselves another way (the login lightbox, the stock lookup) cancel the normal send, and
// this leaves them alone. Without this script, forms still work; they just aren't protected from a double click.
(function () {
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (event.defaultPrevented || !(form instanceof HTMLFormElement) || form.method.toLowerCase() !== "post") return;
    if (form.dataset.sending === "1") {             // already on its way: this is the second click
      event.preventDefault();
      return;
    }
    form.dataset.sending = "1";
    form.querySelectorAll("button[type=submit], button:not([type]), input[type=submit]").forEach((b) => {
      b.setAttribute("aria-disabled", "true");    // not .disabled: a disabled button can't be the one that sent it
      b.classList.add("is-sending");
    });
    // If the page doesn't change (a slow network, or a download), the form is usable again after a while.
    setTimeout(() => release(form), 8000);
  });

  function release(form) {
    delete form.dataset.sending;
    form.querySelectorAll(".is-sending").forEach((b) => {
      b.removeAttribute("aria-disabled");
      b.classList.remove("is-sending");
    });
  }

  // Coming back with the browser's Back button shows the old page from memory: make its forms usable again.
  window.addEventListener("pageshow", () => document.querySelectorAll("form[data-sending]").forEach(release));
})();
