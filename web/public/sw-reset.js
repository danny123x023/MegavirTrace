/* Development only: `next dev` serves this file as /sw.js (see next.config.ts).
 *
 * A worker registered while a production build ran on the same address (for example the offline test
 * on localhost:3000) stays installed and keeps answering /_next/static requests from its cache, so the
 * dev server's pages run stale code and React reports hydration errors.  The page's own clean-up code
 * cannot help, because it arrives in one of those stale files.
 *
 * Browsers re-download /sw.js on every page load to look for an update.  Finding this different file,
 * they install it; it deletes the old worker's caches, unregisters itself and reloads the open tabs,
 * which then load fresh code straight from the dev server.  Saved results (localStorage) are untouched. */
self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.filter((k) => k.startsWith("mt-")).map((k) => caches.delete(k)));
      await self.clients.claim();
      await self.registration.unregister();
      const tabs = await self.clients.matchAll({ type: "window" });
      await Promise.all(tabs.map((tab) => tab.navigate(tab.url).catch(() => undefined)));
    })(),
  );
});
