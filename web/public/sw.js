/* MegavirTrace service worker (FR19): works offline after one visit.
 * Pages: network first, cached copy when offline.  Static assets: cache first (they are versioned).
 * GET /api/*: network first, cached copy when offline.  POST requests are never cached here; the page
 * keeps its recent analyses on the device instead (lib/offline.ts).
 * Street map files (/api/basemap/*) have their own cache, capped at TILE_LIMIT entries: the places
 * you looked at stay viewable offline without filling the device. */
const VERSION = "mt-v1";
const TILES = "mt-tiles-v1";
const TILE_LIMIT = 2000;
const SHELL = ["/", "/compare", "/related", "/start", "/ask", "/methods", "/world.json", "/maplibre-gl-worker.mjs"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== VERSION && k !== TILES).map((k) => caches.delete(k)))).then(() => self.clients.claim()),
  );
});

let tilePuts = 0;
async function keep(cache, name, request, response) {
  await cache.put(request, response);
  if (name !== TILES || ++tilePuts % 100) return;
  const keys = await cache.keys(); // oldest first
  await Promise.all(keys.slice(0, Math.max(0, keys.length - TILE_LIMIT)).map((k) => cache.delete(k)));
}

async function networkFirst(request, fallbackUrl, name = VERSION) {
  const cache = await caches.open(name);
  try {
    const response = await fetch(request);
    if (response.ok) keep(cache, name, request, response.clone()).catch(() => undefined);
    return response;
  } catch (err) {
    const hit = (await cache.match(request, { ignoreVary: true })) || (fallbackUrl && (await cache.match(fallbackUrl)));
    if (hit) return hit;
    throw err;
  }
}

async function cacheFirst(request, name = VERSION) {
  const cache = await caches.open(name);
  const hit = await cache.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  if (response.ok) keep(cache, name, request, response.clone());
  return response;
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/reports/") && url.pathname.endsWith("/export")) return; // downloads: always live
  if (req.mode === "navigate") {
    event.respondWith(networkFirst(req, "/"));
  } else if (url.pathname.startsWith("/_next/static/") || url.pathname === "/world.json" || url.pathname.endsWith(".mjs")) {
    event.respondWith(cacheFirst(req));
  } else if (url.pathname.startsWith("/api/basemap/")) {
    // the style and tile index can change; tiles, fonts and icons at a given address do not
    const changing = url.pathname.startsWith("/api/basemap/style/") || url.pathname === "/api/basemap/planet";
    event.respondWith(changing ? networkFirst(req, undefined, TILES) : cacheFirst(req, TILES));
  } else if (url.pathname.startsWith("/api/")) {
    event.respondWith(networkFirst(req));
  }
});
