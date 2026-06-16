/* analysis.js — Análisis avanzado de patrones. */
(function (global) {
  "use strict";

  function combinations(arr, k) {
    const res = [];
    (function rec(start, combo) {
      if (combo.length === k) { res.push(combo.slice()); return; }
      for (let i = start; i < arr.length; i++) { combo.push(arr[i]); rec(i + 1, combo); combo.pop(); }
    })(0, []);
    return res;
  }

  /** Distribución de cantidad de números impares por sorteo (0..5). */
  function oddEven(rows) {
    const dist = new Array(6).fill(0);
    let odd = 0, even = 0;
    rows.forEach((r) => {
      const o = r.numeros.filter((n) => n % 2 === 1).length;
      dist[o]++; odd += o; even += (5 - o);
    });
    return { dist, odd, even };
  }

  /** Bajos (<= mitad) vs altos. */
  function lowHigh(rows, max) {
    const mid = Math.floor(max / 2);
    const dist = new Array(6).fill(0);
    let low = 0, high = 0;
    rows.forEach((r) => {
      const l = r.numeros.filter((n) => n <= mid).length;
      dist[l]++; low += l; high += (5 - l);
    });
    return { mid, dist, low, high };
  }

  /** Conteo por décadas: 1-9,10-19,20-29,30-39,40-49 (recortado a max). */
  function decades(rows, max) {
    const bands = [[1, 9], [10, 19], [20, 29], [30, 39], [40, 49]].filter((b) => b[0] <= max);
    const counts = new Array(bands.length).fill(0);
    rows.forEach((r) => r.numeros.forEach((n) => {
      for (let i = 0; i < bands.length; i++) if (n >= bands[i][0] && n <= bands[i][1]) { counts[i]++; break; }
    }));
    return { bands, counts };
  }

  /** Histograma de la suma de los 5 números. */
  function sumDistribution(rows) {
    const sums = rows.map((r) => r.numeros.reduce((a, b) => a + b, 0));
    if (!sums.length) return { hist: {}, min: 0, max: 0, avg: 0, sums: [] };
    const min = Math.min(...sums), max = Math.max(...sums);
    const avg = sums.reduce((a, b) => a + b, 0) / sums.length;
    const hist = {};
    sums.forEach((s) => { hist[s] = (hist[s] || 0) + 1; });
    return { hist, min, max, avg, sums };
  }

  /** Consecutivos. Frecuencia de cada par adyacente (n,n+1) presente en un sorteo,
      pares específicos solicitados y % de sorteos con al menos un consecutivo. */
  function consecutive(rows, max, highlight) {
    const pairCount = {};            // "n-n+1" -> veces que ambos salieron juntos
    let drawsWithConsecutive = 0;
    rows.forEach((r) => {
      const set = new Set(r.numeros);
      let has = false;
      for (let n = 1; n < max; n++) {
        if (set.has(n) && set.has(n + 1)) { pairCount[`${n}-${n + 1}`] = (pairCount[`${n}-${n + 1}`] || 0) + 1; has = true; }
      }
      if (has) drawsWithConsecutive++;
    });
    const ranked = Object.entries(pairCount)
      .map(([k, c]) => ({ pair: k, count: c }))
      .sort((a, b) => b.count - a.count);
    const highlighted = (highlight || []).map((p) => ({ pair: p, count: pairCount[p] || 0 }));
    return { ranked, highlighted, drawsWithConsecutive, total: rows.length };
  }

  /** Combinaciones frecuentes de tamaño k. Devuelve top resultados. */
  function frequentCombos(rows, k, topN) {
    const map = new Map();
    rows.forEach((r) => {
      const sorted = r.numeros.slice().sort((a, b) => a - b);
      combinations(sorted, k).forEach((c) => {
        const key = c.join("-");
        map.set(key, (map.get(key) || 0) + 1);
      });
    });
    return [...map.entries()]
      .map(([key, count]) => ({ combo: key.split("-").map(Number), count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, topN);
  }

  global.BS = global.BS || {};
  global.BS.analysis = {
    combinations, oddEven, lowHigh, decades, sumDistribution, consecutive, frequentCombos,
  };
})(window);
