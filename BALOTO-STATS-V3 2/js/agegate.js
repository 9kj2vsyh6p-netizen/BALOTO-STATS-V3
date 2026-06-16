/* agegate.js — Verificación de mayoría de edad (+18).
   Cumple el requisito de no dirigir contenido de juego a menores.
   Recuerda la confirmación 30 días en este dispositivo. */
(function () {
  "use strict";
  var KEY = "bs3_age_ok";
  var DAYS = 30;

  function confirmed() {
    try {
      var v = localStorage.getItem(KEY);
      if (!v) return false;
      return Date.now() < parseInt(v, 10);
    } catch (e) { return false; }
  }

  function remember() {
    try { localStorage.setItem(KEY, String(Date.now() + DAYS * 864e5)); } catch (e) {}
  }

  function build() {
    var gate = document.createElement("div");
    gate.className = "agegate";
    gate.setAttribute("role", "dialog");
    gate.setAttribute("aria-modal", "true");
    gate.setAttribute("aria-label", "Verificación de edad");
    gate.innerHTML =
      '<div class="box">' +
        '<div class="mark">+18</div>' +
        '<h2>¿Eres mayor de edad?</h2>' +
        '<p>Esta herramienta presenta estadísticas sobre juegos de suerte y azar y es solo para mayores de 18 años. El juego puede causar adicción; juega con responsabilidad.</p>' +
        '<div class="actions">' +
          '<button class="btn" id="ageNo">Soy menor</button>' +
          '<button class="btn btn-primary" id="ageYes">Soy mayor de 18</button>' +
        '</div>' +
        '<p class="deny">Al continuar aceptas los <a href="terminos.html">Términos</a> y la ' +
          '<a href="privacidad.html">Política de privacidad</a>.</p>' +
      '</div>';
    document.body.appendChild(gate);

    gate.querySelector("#ageYes").addEventListener("click", function () {
      remember();
      gate.remove();
    });
    gate.querySelector("#ageNo").addEventListener("click", function () {
      gate.querySelector(".box").innerHTML =
        '<div class="mark">18</div><h2>Acceso restringido</h2>' +
        '<p>Esta herramienta es solo para mayores de edad. Si necesitas apoyo por temas de juego, ' +
        'visita <a href="https://tomaelcontrol.coljuegos.gov.co/" target="_blank" rel="noopener">Toma el Control</a> ' +
        'o la página de <a href="juego-responsable.html">Juego responsable</a>.</p>';
    });
  }

  function init() { if (!confirmed()) build(); }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else { init(); }
})();
