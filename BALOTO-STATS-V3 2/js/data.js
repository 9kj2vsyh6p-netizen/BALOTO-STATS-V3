/* data.js — Capa de acceso a datos de BALOTO STATS V3
   Carga data/resultados.json y expone helpers por juego. */
(function (global) {
  "use strict";

  const GAMES = {
    baloto:   { key: "baloto",   label: "Baloto",   max: 43, sb: 16,   accent: "--accent-baloto" },
    revancha: { key: "revancha", label: "Revancha", max: 43, sb: 16,   accent: "--accent-revancha" },
    miloto:   { key: "miloto",   label: "MiLoto",   max: 39, sb: null, accent: "--accent-miloto" },
  };

  const WINDOWS = [25, 50, 100, 200, 500, 1000];

  const state = {
    raw: null,
    meta: {},
    loaded: false,
  };

  async function load() {
    const res = await fetch("data/resultados.json", { cache: "no-cache" });
    if (!res.ok) throw new Error("No se pudo cargar resultados.json (HTTP " + res.status + ")");
    const json = await res.json();
    state.raw = json;
    state.meta = json._meta || {};
    // Orden ascendente por fecha y sorteo (defensivo)
    Object.keys(GAMES).forEach((g) => {
      (json[g] || []).sort((a, b) =>
        a.fecha === b.fecha ? (a.sorteo || 0) - (b.sorteo || 0) : a.fecha.localeCompare(b.fecha));
    });
    state.loaded = true;
    return json;
  }

  /** Todos los sorteos de un juego, orden ascendente (antiguo -> reciente). */
  function all(game) {
    return (state.raw && state.raw[game]) || [];
  }

  /** Los n sorteos más recientes (orden descendente: el más reciente primero). */
  function lastN(game, n) {
    const rows = all(game);
    return rows.slice(Math.max(0, rows.length - n)).reverse();
  }

  function latest(game) {
    const rows = all(game);
    return rows.length ? rows[rows.length - 1] : null;
  }

  function coverage(game) {
    const rows = all(game);
    if (!rows.length) return { desde: null, hasta: null, total: 0 };
    return { desde: rows[0].fecha, hasta: rows[rows.length - 1].fecha, total: rows.length };
  }

  function isSample(game) {
    var sg = state.meta && state.meta.sample_games;
    if (Array.isArray(sg)) return game ? sg.indexOf(game) >= 0 : sg.length > 0;
    return (state.meta.source || "") === "sample";
  }

  global.BS = global.BS || {};
  global.BS.data = { GAMES, WINDOWS, state, load, all, lastN, latest, coverage, isSample };
})(window);
