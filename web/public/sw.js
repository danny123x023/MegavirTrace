/* MegavirTrace service worker (FR19): works offline after one visit.
 * Pages: network first, cached copy when offline.  Static assets: cache first (they are versioned).
 * GET /api/*: network first, cached copy when offline.  POST requests are never cached here; the page
 * keeps its recent analyses on the device instead (lib/offline.ts). */
const VERSION = "mt-v1";
const SHELL = ["/", "/compare", "/related", "/start", "/ask", "/methods", "/world.json", "/maplibre-gl-worker.mjs"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k)))).then(() => self.clients.claim()),
  );
});

async function networkFirst(request, fallbackUrl) {
  const cache = await caches.open(VERSION);
  try {
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch (err) {
    const hit = (await cache.match(request, { ignoreVary: true })) || (fallbackUrl && (await cache.match(fallbackUrl)));
    if (hit) return hit;
    throw err;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(VERSION);
  const hit = await cache.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  if (response.ok) cache.put(request, response.clone());
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
  } else if (url.pathname.startsWith("/api/")) {
    event.respondWith(networkFirst(req));
  }
});
