/* stats.js — Frecuencias, ventanas móviles, números calientes y fríos. */
(function (global) {
  "use strict";

  /** Conteo de apariciones por número. Devuelve {counts[1..max], draws, total}. */
  function frequency(rows, max) {
    const counts = new Array(max + 1).fill(0);
    rows.forEach((r) => r.numeros.forEach((n) => { if (n >= 1 && n <= max) counts[n]++; }));
    return { counts, draws: rows.length, total: rows.length * 5 };
  }

  /** Frecuencia relativa: proporción de sorteos en los que sale cada número. */
  function relative(freq) {
    const { counts, draws } = freq;
    return counts.map((c) => (draws ? c / draws : 0));
  }

  /** Frecuencia sobre los últimos n sorteos. */
  function windowFrequency(rows, max, n) {
    const slice = rows.slice(Math.max(0, rows.length - n));
    return frequency(slice, max);
  }

  /** Ranking [{n, count, rel}] ordenado por frecuencia descendente. */
  function ranking(freq, max) {
    const { counts, draws } = freq;
    const out = [];
    for (let n = 1; n <= max; n++) out.push({ n, count: counts[n], rel: draws ? counts[n] / draws : 0 });
    out.sort((a, b) => b.count - a.count || a.n - b.n);
    return out;
  }

  function hot(freq, max, topN) {
    return ranking(freq, max).slice(0, topN);
  }

  /** Fríos por menor frecuencia. */
  function coldByFrequency(freq, max, topN) {
    const r = ranking(freq, max).slice().sort((a, b) => a.count - b.count || a.n - b.n);
    return r.slice(0, topN);
  }

  /** Ausencia: sorteos transcurridos desde la última aparición de cada número.
      Devuelve [{n, ausencia, ultima}] ordenado por ausencia descendente. */
  function absence(rows, max) {
    const lastIndex = new Array(max + 1).fill(-1);
    rows.forEach((r, i) => r.numeros.forEach((n) => { if (n >= 1 && n <= max) lastIndex[n] = i; }));
    const total = rows.length;
    const out = [];
    for (let n = 1; n <= max; n++) {
      const idx = lastIndex[n];
      out.push({
        n,
        ausencia: idx === -1 ? total : total - 1 - idx,
        ultima: idx === -1 ? null : rows[idx].fecha,
      });
    }
    out.sort((a, b) => b.ausencia - a.ausencia || a.n - b.n);
    return out;
  }

  /** Mapa número -> frecuencia relativa en cada ventana, para gráficos de líneas. */
  function windowsMatrix(rows, max, windows) {
    return windows.map((w) => ({ window: w, rel: relative(windowFrequency(rows, max, w)) }));
  }

  global.BS = global.BS || {};
  global.BS.stats = {
    frequency, relative, windowFrequency, ranking, hot, coldByFrequency, absence, windowsMatrix,
  };
})(window);
