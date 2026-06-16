/* sw.js — Service Worker de Baloto Stats V3.
   App shell: cache-first. Datos (resultados.json): network-first con respaldo. */
const VERSION = "v3.1.0";
const SHELL_CACHE = "bs3-shell-" + VERSION;
const DATA_CACHE = "bs3-data-" + VERSION;

const SHELL = [
  "./",
  "./index.html",
  "./juego-responsable.html",
  "./terminos.html",
  "./privacidad.html",
  "./manifest.json",
  "./css/styles.css",
  "./js/data.js",
  "./js/stats.js",
  "./js/analysis.js",
  "./js/generators.js",
  "./js/charts.js",
  "./js/ui.js",
  "./js/app.js",
  "./js/agegate.js",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) =>
      Promise.allSettled(SHELL.map((u) => cache.add(u)))
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== SHELL_CACHE && k !== DATA_CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  // Datos: network-first para tener los últimos sorteos, con respaldo en cache.
  if (url.pathname.endsWith("resultados.json")) {
    event.respondWith(
      fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(DATA_CACHE).then((c) => c.put(req, copy));
        return res;
      }).catch(() => caches.match(req))
    );
    return;
  }

  // Resto: cache-first con relleno.
  event.respondWith(
    caches.match(req).then((cached) =>
      cached || fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(SHELL_CACHE).then((c) => c.put(req, copy));
        return res;
      }).catch(() => cached)
    )
  );
});
