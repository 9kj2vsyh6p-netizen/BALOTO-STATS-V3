/* app.js — Arranque y navegación de BALOTO STATS V3. */
(function (global) {
  "use strict";

  const state = { game: "baloto", section: "dashboard" };

  const SECTIONS = {
    dashboard: (g, m) => global.BS.ui.renderDashboard(g, m),
    frecuencias: (g, m) => global.BS.ui.renderFrecuencias(g, m),
    analisis: (g, m) => global.BS.ui.renderAnalisis(g, m),
    generador: (g, m) => global.BS.ui.renderGenerador(g, m),
  };

  function $(sel) { return document.querySelector(sel); }
  function $all(sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); }

  function render() {
    const mount = $("#view");
    mount.innerHTML = '<div class="loading">Calculando…</div>';
    // dejar pintar el "Calculando" antes de trabajo síncrono pesado
    requestAnimationFrame(() => {
      try {
        SECTIONS[state.section](state.game, mount);
      } catch (err) {
        mount.innerHTML = `<div class="card error"><h3>Algo salió mal</h3>
          <p>${err.message}</p><p class="muted">Revisa la consola para más detalle.</p></div>`;
        console.error(err);
      }
    });
  }

  function setGame(game) {
    state.game = game;
    $all("[data-game]").forEach((b) => b.classList.toggle("is-active", b.dataset.game === game));
    document.documentElement.style.setProperty("--accent", cssAccent(game));
    var badge = document.getElementById("sampleBadge");
    if (badge) badge.hidden = !global.BS.data.isSample(game);
    render();
  }

  function setSection(section) {
    state.section = section;
    $all("[data-section]").forEach((b) => b.classList.toggle("is-active", b.dataset.section === section));
    render();
  }

  function cssAccent(game) {
    const map = { baloto: "--accent-baloto", revancha: "--accent-revancha", miloto: "--accent-miloto" };
    return getComputedStyle(document.documentElement).getPropertyValue(map[game]).trim();
  }

  function wire() {
    $all("[data-game]").forEach((b) => b.addEventListener("click", () => setGame(b.dataset.game)));
    $all("[data-section]").forEach((b) => b.addEventListener("click", () => setSection(b.dataset.section)));
  }

  async function boot() {
    wire();
    try {
      await global.BS.data.load();
    } catch (err) {
      $("#view").innerHTML = `<div class="card error"><h3>No se pudieron cargar los datos</h3>
        <p>${err.message}</p></div>`;
      return;
    }
    if (global.BS.data.isSample()) $("#sampleBadge").hidden = false;
    setGame("baloto");
    setSection("dashboard");    registerSW();
  }

  function registerSW() {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("sw.js").catch((e) => console.warn("SW:", e));
    }
  }

  document.addEventListener("DOMContentLoaded", boot);
})(window);
