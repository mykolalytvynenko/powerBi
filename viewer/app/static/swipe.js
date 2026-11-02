// Гортання фото: свайп на телефоні, стрілки на клавіатурі
(function () {
  function go(id) { var a = document.getElementById(id); if (a) location.href = a.href; }
  document.addEventListener("keydown", function (e) {
    if (e.key === "ArrowLeft") go("prev");
    if (e.key === "ArrowRight") go("next");
  });
  var x0 = null;
  document.addEventListener("touchstart", function (e) { x0 = e.touches[0].clientX; }, { passive: true });
  document.addEventListener("touchend", function (e) {
    if (x0 === null) return;
    var dx = e.changedTouches[0].clientX - x0; x0 = null;
    if (Math.abs(dx) > 60) go(dx > 0 ? "prev" : "next");
  }, { passive: true });
})();
