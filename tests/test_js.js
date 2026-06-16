/* Tests de los módulos JS de BALOTO STATS V3.
   Ejecutar:  node tests/test_js.js
   No requiere frameworks: usa assert nativo de Node. */
"use strict";
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");
const path = require("path");

// --- Shim mínimo del navegador --------------------------------------------
global.window = global;

// Datos de prueba deterministas (Baloto: 1-43 + superbalota)
const ROWS = {
  baloto: [
    { fecha: "2026-06-01", sorteo: 1, numeros: [1, 2, 3, 4, 5], superbalota: 1 },
    { fecha: "2026-06-02", sorteo: 2, numeros: [1, 2, 3, 40, 43], superbalota: 2 },
    { fecha: "2026-06-03", sorteo: 3, numeros: [1, 2, 30, 41, 42], superbalota: 3 },
    { fecha: "2026-06-04", sorteo: 4, numeros: [1, 10, 11, 12, 13], superbalota: 4 },
  ],
  miloto: [
    { fecha: "2026-06-01", sorteo: 1, numeros: [1, 2, 3, 4, 5], superbalota: null },
    { fecha: "2026-06-02", sorteo: 2, numeros: [5, 6, 7, 8, 9], superbalota: null },
  ],
};

const GAMES = {
  baloto: { key: "baloto", label: "Baloto", max: 43, sb: 16 },
  revancha: { key: "revancha", label: "Revancha", max: 43, sb: 16 },
  miloto: { key: "miloto", label: "MiLoto", max: 39, sb: null },
};

global.BS = {
  data: {
    GAMES,
    WINDOWS: [25, 50, 100, 200, 500, 1000],
    all: (g) => ROWS[g] || [],
    lastN: (g, n) => (ROWS[g] || []).slice(-n).reverse(),
    latest: (g) => { const r = ROWS[g] || []; return r.length ? r[r.length - 1] : null; },
    coverage: (g) => { const r = ROWS[g] || []; return r.length ? { desde: r[0].fecha, hasta: r[r.length - 1].fecha, total: r.length } : { total: 0 }; },
    isSample: () => false,
  },
};

// Cargar los módulos reales
for (const f of ["stats", "analysis", "generators"]) {
  const code = fs.readFileSync(path.join(__dirname, "..", "js", f + ".js"), "utf8");
  vm.runInThisContext(code, { filename: f + ".js" });
}

const { stats, analysis, generators } = BS;
let passed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log("  ✓ " + name); }
  catch (e) { console.error("  ✗ " + name + "\n     " + e.message); process.exitCode = 1; }
}

console.log("\nSTATS");
test("frequency cuenta apariciones", () => {
  const f = stats.frequency(ROWS.baloto, 43);
  assert.strictEqual(f.counts[1], 4);   // el 1 sale en los 4 sorteos
  assert.strictEqual(f.counts[2], 3);   // el 2 sale en 3
  assert.strictEqual(f.draws, 4);
});
test("relative entre 0 y 1", () => {
  const rel = stats.relative(stats.frequency(ROWS.baloto, 43));
  assert.ok(rel[1] === 1 && rel[2] === 0.75);
});
test("ranking ordena por frecuencia desc", () => {
  const r = stats.ranking(stats.frequency(ROWS.baloto, 43), 43);
  assert.strictEqual(r[0].n, 1);
  assert.ok(r[0].count >= r[1].count);
});
test("hot devuelve topN", () => {
  assert.strictEqual(stats.hot(stats.frequency(ROWS.baloto, 43), 43, 3).length, 3);
});
test("absence calcula ausencia", () => {
  const abs = stats.absence(ROWS.baloto, 43);
  const n40 = abs.find((x) => x.n === 40);
  assert.ok(n40.ausencia >= 0);
});

console.log("\nANALYSIS");
test("oddEven suma correcta", () => {
  const oe = analysis.oddEven(ROWS.baloto);
  assert.strictEqual(oe.odd + oe.even, ROWS.baloto.length * 5);
});
test("lowHigh corte en la mitad", () => {
  const lh = analysis.lowHigh(ROWS.baloto, 43);
  assert.strictEqual(lh.mid, 21);
  assert.strictEqual(lh.low + lh.high, ROWS.baloto.length * 5);
});
test("decades reparte en bandas", () => {
  const dec = analysis.decades(ROWS.baloto, 43);
  const total = dec.counts.reduce((a, b) => a + b, 0);
  assert.strictEqual(total, ROWS.baloto.length * 5);
});
test("sumDistribution min<=avg<=max", () => {
  const sd = analysis.sumDistribution(ROWS.baloto);
  assert.ok(sd.min <= sd.avg && sd.avg <= sd.max);
});
test("frequentCombos parejas", () => {
  const pares = analysis.frequentCombos(ROWS.baloto, 2, 50);
  const top = pares.find((p) => p.combo[0] === 1 && p.combo[1] === 2);
  assert.strictEqual(top.count, 3);   // (1,2) aparece junto 3 veces
});
test("consecutive detecta pares", () => {
  const c = analysis.consecutive(ROWS.baloto, 43, ["1-2"]);
  assert.ok(c.total === 4);
  assert.ok(c.highlighted[0].count >= 1);
});

console.log("\nGENERATORS");
function valida(line, max) {
  assert.strictEqual(line.numeros.length, 5, "deben ser 5 números");
  assert.strictEqual(new Set(line.numeros).size, 5, "sin repetidos");
  line.numeros.forEach((n) => assert.ok(n >= 1 && n <= max, "en rango"));
}
test("motor 1 frecuencia simple", () => valida(generators.engine1("baloto"), 43));
test("motor 2 frecuencia ponderada", () => valida(generators.engine2("baloto"), 43));
test("motor 3 hot/cold", () => valida(generators.engine3("baloto"), 43));
test("motor 4 monte carlo (línea válida)", () => {
  const r = generators.engine4("baloto", 2000);
  valida(r, 43);
  assert.ok(r.simulations === 2000);
});
test("motor 5 híbrido premium", () => valida(generators.engine5("baloto", 2000), 43));
test("baloto trae superbalota 1-16", () => {
  const r = generators.engine1("baloto");
  assert.ok(r.superbalota >= 1 && r.superbalota <= 16);
});
test("miloto NO trae superbalota", () => {
  const r = generators.engine1("miloto");
  assert.strictEqual(r.superbalota, null);
  r.numeros.forEach((n) => assert.ok(n >= 1 && n <= 39));
});
test("premiumAll devuelve 3 perfiles", () => {
  const p = generators.premiumAll("baloto");
  ["conservadora", "equilibrada", "agresiva"].forEach((k) => valida(p[k], 43));
});

console.log(`\n${passed} tests JS pasaron` + (process.exitCode ? " (con fallos)" : " ✅"));
