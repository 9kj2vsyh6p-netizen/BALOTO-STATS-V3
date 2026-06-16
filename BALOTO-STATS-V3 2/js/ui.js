/* ui.js — Render de las cuatro secciones de la aplicación. */
(function (global) {
  "use strict";

  const D = () => global.BS.data;
  const S = () => global.BS.stats;
  const A = () => global.BS.analysis;
  const G = () => global.BS.generators;
  const C = () => global.BS.charts;

  // ---- helpers de presentación -------------------------------------------

  function ball(n, temp) {
    const cls = temp ? " ball--" + temp : "";
    return `<span class="ball${cls}">${n}</span>`;
  }
  function superBall(n) {
    return n == null ? "" : `<span class="ball ball--super" title="Superbalota">${n}</span>`;
  }
  function line(numeros, sb) {
    return `<span class="line">${numeros.map((n) => ball(n)).join("")}${superBall(sb)}</span>`;
  }
  function tempForRank(idx, total) {
    const t = idx / Math.max(1, total - 1);
    if (t < 0.2) return "hot";
    if (t > 0.8) return "cold";
    return "neutral";
  }
  function fmtDate(s) {
    if (!s) return "—";
    const [y, m, d] = s.split("-");
    const meses = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
    return `${d} ${meses[+m - 1]} ${y}`;
  }
  function el(html) { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstChild; }

  function ballRow(ranking, count) {
    return ranking.slice(0, count).map((r, i) =>
      `<span class="ballwrap">${ball(r.n, i < 3 ? "hot" : "neutral")}<em>${r.count}</em></span>`).join("");
  }
  function coldRow(items, count, label) {
    return items.slice(0, count).map((r) =>
      `<span class="ballwrap">${ball(r.n, "cold")}<em>${label === "abs" ? r.ausencia : r.count}</em></span>`).join("");
  }

  // ---- DASHBOARD ----------------------------------------------------------

  function renderDashboard(game, mount) {
    const rows = D().all(game);
    const cfg = D().GAMES[game];
    const cov = D().coverage(game);
    const last = D().latest(game);
    const freqAll = S().frequency(rows, cfg.max);
    const rankAll = S().ranking(freqAll, cfg.max);
    const cold = S().coldByFrequency(freqAll, cfg.max, 20);
    const maxCount = rankAll.length ? rankAll[0].count : 0;

    mount.innerHTML = `
      <div class="grid">
        <div class="card stat">
          <span class="stat-label">Total sorteos</span>
          <span class="stat-value">${cov.total.toLocaleString("es-CO")}</span>
          <span class="stat-sub">${fmtDate(cov.desde)} – ${fmtDate(cov.hasta)}</span>
        </div>
        <div class="card stat">
          <span class="stat-label">Último sorteo · ${last ? "#" + (last.sorteo ?? "—") : ""}</span>
          <span class="stat-line">${last ? line(last.numeros, last.superbalota) : "—"}</span>
          <span class="stat-sub">${last ? fmtDate(last.fecha) : ""}</span>
        </div>
      </div>

      <div class="card">
        <h3>Números calientes <span class="muted">más frecuentes</span></h3>
        <div class="ball-strip">${ballRow(rankAll, 10)}</div>
      </div>

      <div class="card">
        <h3>Números fríos <span class="muted">menos frecuentes</span></h3>
        <div class="ball-strip">${coldRow(cold, 10, "freq")}</div>
      </div>

      <div class="card">
        <h3>Frecuencia histórica</h3>
        <div class="chart-box"><canvas id="dashFreqAll"></canvas></div>
      </div>

      <div class="grid">
        <div class="card">
          <h3>Frecuencia <span class="muted">últimos 100</span></h3>
          <div class="chart-box sm"><canvas id="dashFreq100"></canvas></div>
        </div>
        <div class="card">
          <h3>Frecuencia <span class="muted">últimos 500</span></h3>
          <div class="chart-box sm"><canvas id="dashFreq500"></canvas></div>
        </div>
      </div>`;

    C().barFrequency(mount.querySelector("#dashFreqAll"), rankAll, maxCount);
    const r100 = S().ranking(S().windowFrequency(rows, cfg.max, 100), cfg.max);
    const r500 = S().ranking(S().windowFrequency(rows, cfg.max, 500), cfg.max);
    C().barFrequency(mount.querySelector("#dashFreq100"), r100, r100[0] ? r100[0].count : 0);
    C().barFrequency(mount.querySelector("#dashFreq500"), r500, r500[0] ? r500[0].count : 0);
  }

  // ---- FRECUENCIAS --------------------------------------------------------

  let freqWindow = 0; // 0 = histórico

  function renderFrecuencias(game, mount) {
    const rows = D().all(game);
    const cfg = D().GAMES[game];
    const windows = D().WINDOWS;

    const btns = [{ w: 0, label: "Histórico" }].concat(windows.map((w) => ({ w, label: "U" + w })))
      .map((b) => `<button class="chip ${freqWindow === b.w ? "is-active" : ""}" data-w="${b.w}">${b.label}</button>`).join("");

    mount.innerHTML = `
      <div class="card">
        <div class="row-between">
          <h3>Ranking de frecuencia</h3>
          <div class="chips" id="freqChips">${btns}</div>
        </div>
        <div class="chart-box"><canvas id="freqBar"></canvas></div>
      </div>

      <div class="grid">
        <div class="card">
          <h3>Calientes <span class="muted">Top 5 · 10 · 20</span></h3>
          <div id="hotBlocks"></div>
        </div>
        <div class="card">
          <h3>Fríos <span class="muted">por ausencia y frecuencia</span></h3>
          <div id="coldBlocks"></div>
        </div>
      </div>

      <div class="card">
        <h3>Mapa de calor histórico</h3>
        <div id="heat"></div>
        <div class="heat-legend"><span>frío</span><span class="bar"></span><span>caliente</span></div>
      </div>

      <div class="card">
        <h3>Tendencia por ventanas <span class="muted">top 4 números</span></h3>
        <div class="chart-box"><canvas id="trendLine"></canvas></div>
      </div>`;

    function paint() {
      const freq = freqWindow ? S().windowFrequency(rows, cfg.max, freqWindow) : S().frequency(rows, cfg.max);
      const rank = S().ranking(freq, cfg.max);
      C().barFrequency(mount.querySelector("#freqBar"), rank, rank[0] ? rank[0].count : 0);
    }
    paint();

    mount.querySelector("#freqChips").addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      freqWindow = +b.dataset.w;
      mount.querySelectorAll("#freqChips .chip").forEach((c) => c.classList.toggle("is-active", +c.dataset.w === freqWindow));
      paint();
    });

    const freqAll = S().frequency(rows, cfg.max);
    const rankAll = S().ranking(freqAll, cfg.max);
    const cold = S().coldByFrequency(freqAll, cfg.max, 20);
    const abs = S().absence(rows, cfg.max);

    mount.querySelector("#hotBlocks").innerHTML =
      [5, 10, 20].map((n) => `<div class="topblock"><span class="tag">Top ${n}</span><div class="ball-strip">${ballRow(rankAll, n)}</div></div>`).join("");
    mount.querySelector("#coldBlocks").innerHTML =
      `<div class="topblock"><span class="tag">Mayor ausencia</span><div class="ball-strip">${coldRow(abs, 10, "abs")}</div></div>` +
      [5, 10, 20].map((n) => `<div class="topblock"><span class="tag">Menos frecuentes ${n}</span><div class="ball-strip">${coldRow(cold, n, "freq")}</div></div>`).join("");

    C().heatmap(mount.querySelector("#heat"), rankAll, cfg.max);

    const top4 = rankAll.slice(0, 4).map((r) => r.n);
    const matrix = S().windowsMatrix(rows, cfg.max, windows);
    const series = top4.map((n) => ({ n, values: matrix.map((m) => m.rel[n]) }));
    C().lineWindows(mount.querySelector("#trendLine"), windows, series);
  }

  // ---- ANÁLISIS -----------------------------------------------------------

  function renderAnalisis(game, mount) {
    const rows = D().all(game);
    const cfg = D().GAMES[game];

    const oe = A().oddEven(rows);
    const lh = A().lowHigh(rows, cfg.max);
    const dec = A().decades(rows, cfg.max);
    const sum = A().sumDistribution(rows);
    const cons = A().consecutive(rows, cfg.max, ["12-13", "21-22", "38-39"]);
    const pares = A().frequentCombos(rows, 2, 50);
    const trios = A().frequentCombos(rows, 3, 50);
    const cuartetos = A().frequentCombos(rows, 4, 25);

    mount.innerHTML = `
      <div class="grid">
        <div class="card">
          <h3>Pares vs impares</h3>
          <div class="chart-box sm"><canvas id="oeDon"></canvas></div>
          <p class="muted center">Pares ${oe.even.toLocaleString("es-CO")} · Impares ${oe.odd.toLocaleString("es-CO")}</p>
        </div>
        <div class="card">
          <h3>Bajos vs altos <span class="muted">corte ${lh.mid}</span></h3>
          <div class="chart-box sm"><canvas id="lhDon"></canvas></div>
          <p class="muted center">Bajos ${lh.low.toLocaleString("es-CO")} · Altos ${lh.high.toLocaleString("es-CO")}</p>
        </div>
      </div>

      <div class="card">
        <h3>Distribución por décadas</h3>
        <div class="chart-box sm"><canvas id="decBar"></canvas></div>
      </div>

      <div class="card">
        <h3>Suma de los 5 números</h3>
        <div class="chart-box sm"><canvas id="sumHist"></canvas></div>
        <p class="muted center">Mín ${sum.min} · Media ${sum.avg.toFixed(1)} · Máx ${sum.max}</p>
      </div>

      <div class="card">
        <h3>Consecutivos</h3>
        <p class="muted">Sorteos con al menos un par consecutivo:
          <strong>${cons.drawsWithConsecutive.toLocaleString("es-CO")}</strong>
          (${((cons.drawsWithConsecutive / Math.max(1, cons.total)) * 100).toFixed(1)}%)</p>
        <div class="pair-row">${cons.highlighted.map((h) =>
          `<span class="pairpill">${h.pair.replace("-", "·")}<em>${h.count}</em></span>`).join("")}</div>
        <h4 class="muted">Pares consecutivos más frecuentes</h4>
        <div class="pair-row">${cons.ranked.slice(0, 12).map((h) =>
          `<span class="pairpill">${h.pair.replace("-", "·")}<em>${h.count}</em></span>`).join("")}</div>
      </div>

      <div class="card">
        <h3>Parejas frecuentes <span class="muted">Top 50</span></h3>
        <div class="combo-grid">${comboList(pares)}</div>
      </div>
      <div class="card">
        <h3>Tríos frecuentes <span class="muted">Top 50</span></h3>
        <div class="combo-grid">${comboList(trios)}</div>
      </div>
      <div class="card">
        <h3>Cuartetos frecuentes <span class="muted">Top 25</span></h3>
        <div class="combo-grid">${comboList(cuartetos)}</div>
      </div>`;

    C().doughnut(mount.querySelector("#oeDon"), ["Impares", "Pares"], [oe.odd, oe.even],
      [cssv("--hot"), cssv("--cold")]);
    C().doughnut(mount.querySelector("#lhDon"), ["Bajos", "Altos"], [lh.low, lh.high],
      [cssv("--accent"), cssv("--pos")]);
    C().barDistribution(mount.querySelector("#decBar"),
      dec.bands.map((b) => b[0] + "–" + b[1]), dec.counts, cssv("--accent"));
    C().sumHistogram(mount.querySelector("#sumHist"), sum.hist);
  }

  function comboList(items) {
    return items.map((it, i) =>
      `<div class="combo"><span class="combo-rank">${i + 1}</span>
        <span class="combo-balls">${it.combo.map((n) => ball(n)).join("")}</span>
        <span class="combo-count">${it.count}</span></div>`).join("");
  }

  // ---- GENERADOR ----------------------------------------------------------

  function renderGenerador(game, mount) {
    mount.innerHTML = `
      <div class="card highlight">
        <h3>Modo Premium</h3>
        <p class="muted">Tres líneas con distinto perfil de riesgo, generadas con el motor híbrido.</p>
        <button class="btn btn-primary" id="genPremium">Generar líneas premium</button>
        <div id="premiumOut" class="premium-out"></div>
      </div>

      <div class="card">
        <h3>Motores independientes</h3>
        <p class="muted">Cada motor usa una estrategia estadística distinta.</p>
        <div class="engine-grid">${G().ENGINES.map((e) =>
          `<button class="btn engine" data-engine="${e.id}">
            <span class="engine-id">Motor ${e.id}</span>
            <span class="engine-name">${e.name}</span></button>`).join("")}</div>
        <div id="engineOut" class="engine-out"></div>
      </div>

      <p class="disclaimer">La lotería es un proceso aleatorio: estas combinaciones no aumentan
      la probabilidad de ganar. Juega con responsabilidad.</p>`;

    const engineOut = mount.querySelector("#engineOut");
    mount.querySelector(".engine-grid").addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      const id = +b.dataset.engine;
      const eng = G().ENGINES.find((x) => x.id === id);
      b.classList.add("is-busy");
      // permitir repintar el "busy" antes del cálculo pesado (Monte Carlo)
      setTimeout(() => {
        const res = eng.run(game);
        b.classList.remove("is-busy");
        const sim = res.simulations ? ` · ${res.simulations.toLocaleString("es-CO")} simulaciones` : "";
        engineOut.insertBefore(el(
          `<div class="result-row"><span class="result-tag">Motor ${id} · ${eng.name}${sim}</span>
            ${line(res.numeros, res.superbalota)}</div>`), engineOut.firstChild);
      }, 20);
    });

    const premiumOut = mount.querySelector("#premiumOut");
    mount.querySelector("#genPremium").addEventListener("click", (ev) => {
      ev.target.classList.add("is-busy");
      setTimeout(() => {
        const p = G().premiumAll(game);
        ev.target.classList.remove("is-busy");
        const card = (m, label, cls) =>
          `<div class="premium-card ${cls}"><span class="premium-label">${label}</span>${line(m.numeros, m.superbalota)}</div>`;
        premiumOut.innerHTML =
          card(p.conservadora, "Conservadora", "cons") +
          card(p.equilibrada, "Equilibrada", "equi") +
          card(p.agresiva, "Agresiva", "agr");
      }, 20);
    });
  }

  function cssv(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }

  global.BS = global.BS || {};
  global.BS.ui = { renderDashboard, renderFrecuencias, renderAnalisis, renderGenerador };
})(window);
