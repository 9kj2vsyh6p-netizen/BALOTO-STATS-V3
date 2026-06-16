/* charts.js — Wrappers de Chart.js y mapa de calor histórico. */
(function (global) {
  "use strict";

  const registry = {};

  function css(varName) {
    return getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
  }

  function destroy(id) {
    if (registry[id]) { registry[id].destroy(); delete registry[id]; }
  }

  function baseOptions(extra) {
    const grid = "rgba(255,255,255,0.06)";
    const tick = css("--ink-muted");
    return Object.assign({
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 350 },
      plugins: {
        legend: { labels: { color: tick, font: { family: "Inter" } } },
        tooltip: { backgroundColor: css("--surface-2"), borderColor: grid, borderWidth: 1,
          titleColor: css("--ink"), bodyColor: css("--ink") },
      },
      scales: {
        x: { ticks: { color: tick, font: { size: 10 } }, grid: { color: grid } },
        y: { ticks: { color: tick, font: { size: 10 } }, grid: { color: grid }, beginAtZero: true },
      },
    }, extra || {});
  }

  /** Barras de frecuencia por número, coloreadas por temperatura. */
  function barFrequency(canvas, ranking, maxCount) {
    const id = canvas.id;
    destroy(id);
    const labels = ranking.map((r) => r.n);
    const data = ranking.map((r) => r.count);
    const hot = css("--hot"), cold = css("--cold"), mid = css("--accent");
    const colors = ranking.map((r) => {
      const t = maxCount ? r.count / maxCount : 0;
      if (t > 0.66) return hot;
      if (t < 0.33) return cold;
      return mid;
    });
    registry[id] = new Chart(canvas, {
      type: "bar",
      data: { labels, datasets: [{ label: "Apariciones", data, backgroundColor: colors, borderRadius: 3 }] },
      options: baseOptions(),
    });
  }

  /** Líneas: frecuencia relativa de varios números a través de ventanas. */
  function lineWindows(canvas, windows, series) {
    const id = canvas.id;
    destroy(id);
    const palette = [css("--hot"), css("--accent"), css("--cold"), css("--pos"), "#B388FF", "#FF8A65"];
    const datasets = series.map((s, i) => ({
      label: "N° " + s.n,
      data: s.values.map((v) => +(v * 100).toFixed(1)),
      borderColor: palette[i % palette.length],
      backgroundColor: "transparent",
      tension: 0.3, borderWidth: 2, pointRadius: 3,
    }));
    registry[id] = new Chart(canvas, {
      type: "line",
      data: { labels: windows.map((w) => "U" + w), datasets },
      options: baseOptions({ scales: { y: { ticks: { color: css("--ink-muted"),
        callback: (v) => v + "%" }, grid: { color: "rgba(255,255,255,0.06)" }, beginAtZero: true },
        x: { ticks: { color: css("--ink-muted") }, grid: { color: "rgba(255,255,255,0.06)" } } } }),
    });
  }

  /** Barras genéricas (distribución). */
  function barDistribution(canvas, labels, data, color) {
    const id = canvas.id;
    destroy(id);
    registry[id] = new Chart(canvas, {
      type: "bar",
      data: { labels, datasets: [{ data, backgroundColor: color || css("--accent"), borderRadius: 4 }] },
      options: baseOptions({ plugins: { legend: { display: false } } }),
    });
  }

  /** Dona (pares/impares, bajos/altos). */
  function doughnut(canvas, labels, data, colors) {
    const id = canvas.id;
    destroy(id);
    registry[id] = new Chart(canvas, {
      type: "doughnut",
      data: { labels, datasets: [{ data, backgroundColor: colors, borderColor: css("--surface"), borderWidth: 2 }] },
      options: { responsive: true, maintainAspectRatio: false, cutout: "62%",
        plugins: { legend: { position: "bottom", labels: { color: css("--ink-muted") } } } },
    });
  }

  /** Histograma de suma (línea de área). */
  function sumHistogram(canvas, hist) {
    const id = canvas.id;
    destroy(id);
    const keys = Object.keys(hist).map(Number).sort((a, b) => a - b);
    const labels = keys, data = keys.map((k) => hist[k]);
    registry[id] = new Chart(canvas, {
      type: "line",
      data: { labels, datasets: [{ data, label: "Sorteos", borderColor: css("--accent"),
        backgroundColor: "rgba(244,193,78,0.12)", fill: true, tension: 0.35, pointRadius: 0, borderWidth: 2 }] },
      options: baseOptions({ plugins: { legend: { display: false } } }),
    });
  }

  /** Mapa de calor histórico: cuadrícula de celdas coloreadas por frecuencia. */
  function heatmap(container, ranking, max) {
    container.innerHTML = "";
    const counts = {};
    ranking.forEach((r) => { counts[r.n] = r.count; });
    const values = ranking.map((r) => r.count);
    const lo = Math.min(...values), hi = Math.max(...values);
    const grid = document.createElement("div");
    grid.className = "heat-grid";
    for (let n = 1; n <= max; n++) {
      const c = counts[n] || 0;
      const t = hi > lo ? (c - lo) / (hi - lo) : 0.5;
      const cell = document.createElement("div");
      cell.className = "heat-cell";
      // interpolación frío(azul) -> medio -> caliente(rojo)
      cell.style.background = heatColor(t);
      cell.style.color = t > 0.55 ? "#1a1030" : "var(--ink)";
      cell.innerHTML = `<span class="heat-n">${n}</span><span class="heat-c">${c}</span>`;
      cell.title = `Número ${n}: ${c} apariciones`;
      grid.appendChild(cell);
    }
    container.appendChild(grid);
  }

  function heatColor(t) {
    // 0 -> cyan frío, 0.5 -> oro, 1 -> rosa caliente
    const stops = [[79, 195, 247], [244, 193, 78], [255, 92, 122]];
    const seg = t < 0.5 ? 0 : 1;
    const lt = t < 0.5 ? t / 0.5 : (t - 0.5) / 0.5;
    const a = stops[seg], b = stops[seg + 1];
    const ch = a.map((v, i) => Math.round(v + (b[i] - v) * lt));
    return `rgb(${ch[0]},${ch[1]},${ch[2]})`;
  }

  global.BS = global.BS || {};
  global.BS.charts = { barFrequency, lineWindows, barDistribution, doughnut, sumHistogram, heatmap, destroy };
})(window);
