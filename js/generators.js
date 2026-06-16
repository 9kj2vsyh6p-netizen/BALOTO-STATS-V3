/* generators.js — Cinco motores de generación + modos premium.

   NOTA HONESTA: la lotería es un proceso aleatorio. Estos motores producen
   combinaciones a partir de patrones históricos, pero NO aumentan la
   probabilidad de ganar. Son una herramienta estadística y de entretenimiento. */
(function (global) {
  "use strict";

  const stats = () => global.BS.stats;
  const analysis = () => global.BS.analysis;

  // ---- utilidades ---------------------------------------------------------

  /** Toma k índices distintos en [1..max] con probabilidad proporcional a weights[i]. */
  function weightedSampleDistinct(weights, max, k) {
    const pool = [];
    for (let n = 1; n <= max; n++) pool.push({ n, w: Math.max(weights[n] || 0, 1e-9) });
    const picked = [];
    for (let i = 0; i < k && pool.length; i++) {
      const total = pool.reduce((s, p) => s + p.w, 0);
      let r = Math.random() * total, idx = 0;
      while (idx < pool.length - 1 && (r -= pool[idx].w) > 0) idx++;
      picked.push(pool[idx].n);
      pool.splice(idx, 1);
    }
    return picked.sort((a, b) => a - b);
  }

  function randomLine(max, k) {
    const pool = [];
    for (let n = 1; n <= max; n++) pool.push(n);
    for (let i = pool.length - 1; i > 0; i--) { const j = (Math.random() * (i + 1)) | 0; [pool[i], pool[j]] = [pool[j], pool[i]]; }
    return pool.slice(0, k).sort((a, b) => a - b);
  }

  function superball(game) {
    const cfg = global.BS.data.GAMES[game];
    return cfg.sb ? 1 + ((Math.random() * cfg.sb) | 0) : null;
  }

  function profileOf(game) {
    const rows = global.BS.data.all(game);
    const cfg = global.BS.data.GAMES[game];
    const max = cfg.max, k = 5;
    const freqAll = stats().relative(stats().frequency(rows, max));
    const freq50 = stats().relative(stats().windowFrequency(rows, max, 50));
    const freq100 = stats().relative(stats().windowFrequency(rows, max, 100));
    const abs = {};
    stats().absence(rows, max).forEach((a) => { abs[a.n] = a.ausencia; });
    const maxAbs = Math.max(1, ...Object.values(abs));
    const sumStats = analysis().sumDistribution(rows);
    return { rows, max, k, game, freqAll, freq50, freq100, abs, maxAbs, sumStats };
  }

  // ---- Motor 1: frecuencia simple ----------------------------------------
  function engine1(game) {
    const p = profileOf(game);
    const w = new Array(p.max + 1).fill(0);
    for (let n = 1; n <= p.max; n++) w[n] = p.freqAll[n];
    return { numeros: weightedSampleDistinct(w, p.max, p.k), superbalota: superball(game) };
  }

  // ---- Motor 2: frecuencia ponderada (recencia) --------------------------
  function engine2(game) {
    const p = profileOf(game);
    const w = new Array(p.max + 1).fill(0);
    for (let n = 1; n <= p.max; n++) w[n] = 0.5 * p.freq50[n] + 0.3 * p.freq100[n] + 0.2 * p.freqAll[n];
    return { numeros: weightedSampleDistinct(w, p.max, p.k), superbalota: superball(game) };
  }

  // ---- Motor 3: balance caliente/frío ------------------------------------
  function engine3(game) {
    const p = profileOf(game);
    const ranked = stats().ranking(stats().frequency(p.rows, p.max), p.max);
    const third = Math.max(3, Math.floor(p.max / 3));
    const hotPool = ranked.slice(0, third).map((x) => x.n);
    const coldPool = ranked.slice(-third).map((x) => x.n);
    const pick = (pool, n) => {
      const c = pool.slice();
      const out = [];
      while (out.length < n && c.length) out.push(c.splice((Math.random() * c.length) | 0, 1)[0]);
      return out;
    };
    const hotN = Math.ceil(p.k / 2);
    let nums = [...pick(hotPool, hotN), ...pick(coldPool, p.k - hotN)];
    nums = [...new Set(nums)];
    while (nums.length < p.k) { const r = 1 + ((Math.random() * p.max) | 0); if (!nums.includes(r)) nums.push(r); }
    return { numeros: nums.sort((a, b) => a - b), superbalota: superball(game) };
  }

  // ---- aptitud (fitness) para Monte Carlo y modos premium ----------------
  function fitness(line, p, weights) {
    const set = new Set(line);
    // frecuencia media (recencia ponderada)
    let f = 0; line.forEach((n) => { f += 0.5 * p.freq50[n] + 0.3 * p.freq100[n] + 0.2 * p.freqAll[n]; });
    f /= line.length;
    // recencia / ausencia normalizada (favorece atrasados si weights.recency>0)
    let rec = 0; line.forEach((n) => { rec += p.abs[n] / p.maxAbs; }); rec /= line.length;
    // balance pares/impares (ideal 2-3 impares)
    const odd = line.filter((n) => n % 2 === 1).length;
    const oddScore = 1 - Math.abs(odd - 2.5) / 2.5;
    // balance bajos/altos
    const mid = Math.floor(p.max / 2);
    const low = line.filter((n) => n <= mid).length;
    const lowScore = 1 - Math.abs(low - 2.5) / 2.5;
    // dispersión por décadas (más décadas distintas = mejor reparto)
    const dec = new Set(line.map((n) => Math.floor((n - 1) / 10)));
    const decScore = dec.size / Math.min(5, Math.ceil(p.max / 10));
    // cercanía de la suma a la media histórica
    const sum = line.reduce((a, b) => a + b, 0);
    const sumScore = 1 - Math.min(1, Math.abs(sum - p.sumStats.avg) / (p.sumStats.avg || 1));

    return (
      weights.freq * f +
      weights.recency * rec +
      weights.odd * oddScore +
      weights.low * lowScore +
      weights.decade * decScore +
      weights.sum * sumScore
    );
  }

  /** Búsqueda Monte Carlo: muestrea N líneas y devuelve la de mayor aptitud. */
  function monteCarloSearch(game, weights, N) {
    const p = profileOf(game);
    let best = null, bestScore = -Infinity;
    for (let i = 0; i < N; i++) {
      const line = randomLine(p.max, p.k);
      const s = fitness(line, p, weights);
      if (s > bestScore) { bestScore = s; best = line; }
    }
    return { numeros: best, score: bestScore, simulations: N };
  }

  // ---- Motor 4: Monte Carlo (>=100.000 simulaciones) ---------------------
  function engine4(game, N) {
    N = N || 100000;
    const w = { freq: 1, recency: 0.2, odd: 0.6, low: 0.6, decade: 0.8, sum: 0.6 };
    const r = monteCarloSearch(game, w, N);
    return { numeros: r.numeros, superbalota: superball(game), simulations: r.simulations };
  }

  // ---- Motor 5: híbrido premium ------------------------------------------
  function engine5(game, N) {
    N = N || 100000;
    const w = { freq: 1.0, recency: 0.6, odd: 0.7, low: 0.7, decade: 1.0, sum: 0.7 };
    const r = monteCarloSearch(game, w, N);
    return { numeros: r.numeros, superbalota: superball(game), simulations: r.simulations, score: r.score };
  }

  // ---- Modos premium ------------------------------------------------------
  const PREMIUM_WEIGHTS = {
    conservadora: { freq: 1.4, recency: 0.1, odd: 0.9, low: 0.9, decade: 1.0, sum: 1.0 },
    equilibrada:  { freq: 1.0, recency: 0.6, odd: 0.7, low: 0.7, decade: 1.0, sum: 0.7 },
    agresiva:     { freq: 0.4, recency: 1.4, odd: 0.4, low: 0.4, decade: 0.7, sum: 0.3 },
  };

  function premium(game, mode, N) {
    N = N || 60000;
    const w = PREMIUM_WEIGHTS[mode] || PREMIUM_WEIGHTS.equilibrada;
    const r = monteCarloSearch(game, w, N);
    return { mode, numeros: r.numeros, superbalota: superball(game), simulations: r.simulations };
  }

  function premiumAll(game) {
    return {
      conservadora: premium(game, "conservadora"),
      equilibrada: premium(game, "equilibrada"),
      agresiva: premium(game, "agresiva"),
    };
  }

  const ENGINES = [
    { id: 1, name: "Frecuencia simple", run: (g) => engine1(g) },
    { id: 2, name: "Frecuencia ponderada", run: (g) => engine2(g) },
    { id: 3, name: "Hot/Cold balance", run: (g) => engine3(g) },
    { id: 4, name: "Monte Carlo", run: (g) => engine4(g) },
    { id: 5, name: "Híbrido premium", run: (g) => engine5(g) },
  ];

  global.BS = global.BS || {};
  global.BS.generators = { engine1, engine2, engine3, engine4, engine5, premium, premiumAll, ENGINES, fitness };
})(window);
