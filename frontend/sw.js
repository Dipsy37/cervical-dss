/*
 * Service worker: makes the app installable and lets its screens open quickly on a slow network.
 *
 * What is cached: only the app's own files (HTML pages, CSS, JavaScript, icons).
 * What is NEVER cached: anything under /api/ (logins, client codes, risk answers, results).
 * Patient data is therefore never stored on the phone by this file, and every
 * assessment still goes to the server, where the model runs.
 *
 * Pages, CSS and JavaScript are fetched from the server first whenever there is a connection,
 * so an update reaches every phone on its next visit; the saved copy is used only when offline.
 * Icons and the manifest rarely change and are answered from the saved copy.
 *
 * When you change any frontend file, still raise CACHE_VERSION so the offline copy is refreshed too.
 */
const CACHE_VERSION = "v5";
const CACHE = `cdss-shell-${CACHE_VERSION}`;

const APP_SHELL = [
  "/", "/index.html", "/change-password.html",
  "/chw.html", "/assess.html", "/result.html", "/history.html", "/clients.html", "/client.html",
  "/dashboard.html", "/admin.html", "/admin-assessments.html",
  "/offline.html",
  "/css/style.css", "/js/api.js", "/js/dashboard.js", "/js/pwa.js",
  "/manifest.json",
  "/icons/icon-192.png", "/icons/icon-512.png", "/icons/icon-maskable-512.png",
  "/icons/apple-touch-icon.png", "/icons/favicon-32.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(APP_SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Only handle our own GET requests. API calls, logins and form submissions go straight to the network.
  if (req.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/docs")
      || url.pathname.startsWith("/redoc") || url.pathname === "/openapi.json") return;

  if (req.mode === "navigate" || /\.(js|css)$/.test(url.pathname)) {
    // Pages, CSS and JavaScript: try the network first (always the latest version).
    // If offline, use the saved copy (pages fall back to the offline page).
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req.mode === "navigate" ? url.pathname : req, copy));
          }
          return res;
        })
        .catch(async () => {
          const saved = await caches.match(req, { ignoreSearch: true });
          if (saved) return saved;
          return req.mode === "navigate" ? caches.match("/offline.html") : Response.error();
        })
    );
    return;
  }

  // Icons and manifest: answer from the saved copy at once, refresh it in the background.
  event.respondWith(
    caches.match(req).then((cached) => {
      const fresh = fetch(req)
        .then((res) => {
          if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
          return res;
        })
        .catch(() => cached);
      return cached || fresh;
    })
  );
});
