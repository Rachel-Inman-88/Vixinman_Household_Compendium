// Compendium service worker (Piece 24.9) — offline cold-start for the field.
// All page CSS is inlined, so the "app shell" is just the HTML: we cache each
// page the user visits (network-first) and, when offline, serve the last-seen
// copy — falling back to a friendly offline page. Dynamic /api/ data is never
// cached; the Work Bag hydrates from its own on-device store instead.
const VERSION = "{{ version }}";
const SHELL = "compendium-shell-" + VERSION;
const PAGES = "compendium-pages-" + VERSION;
const OFFLINE_URL = "/offline";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL)
      .then((c) => c.add(OFFLINE_URL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  // Drop caches from older versions, then take control of open tabs.
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== SHELL && k !== PAGES).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("message", (event) => {
  // The page asks us to forget cached authenticated pages on logout.
  if (event.data && event.data.type === "clear-pages") {
    caches.delete(PAGES);
  }
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  // Only page navigations are cached for offline. Everything else (POSTs,
  // /api/ calls, cross-origin) passes straight through to the network.
  if (req.method !== "GET" || req.mode !== "navigate") return;
  if (new URL(req.url).origin !== self.location.origin) return;

  event.respondWith(
    fetch(req)
      .then((resp) => {
        const copy = resp.clone();
        caches.open(PAGES).then((c) => c.put(req, copy));
        return resp;
      })
      .catch(() =>
        caches.match(req).then((hit) => hit || caches.match(OFFLINE_URL))
      )
  );
});
