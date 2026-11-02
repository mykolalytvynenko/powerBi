// Пошук і перемикач A–Z / А–Я без перезавантаження сторінки
(function () {
  var q = document.getElementById("q");
  var items = document.querySelectorAll("#items [data-search]");
  var script = "";
  function apply() {
    var text = (q && q.value || "").trim().toLowerCase();
    items.forEach(function (el) {
      var ok = (!text || el.dataset.search.indexOf(text) !== -1) &&
               (text || !script || el.dataset.script === script);
      el.hidden = !ok;
    });
  }
  if (q) q.addEventListener("input", apply);
  document.querySelectorAll("#scripts button").forEach(function (btn) {
    btn.addEventListener("click", function () {
      script = btn.dataset.script;
      document.querySelectorAll("#scripts button").forEach(function (b) { b.classList.toggle("on", b === btn); });
      apply();
    });
  });
})();
