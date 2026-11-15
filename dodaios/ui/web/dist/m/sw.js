/* The phone companion's service worker (scope /m/).
 *
 * Two jobs, nothing more: keep the app shell opening when the phone is away
 * from the computer, and show the pushes the computer sends. API calls are
 * never cached: the conversation is read live, with the device token the page
 * holds. A service worker only runs in a secure context (HTTPS), so over plain
 * LAN HTTP this file is simply never registered and the page works as a page.
 */
const CACHE = "dodaios-mobile-v1";
const SHELL = ["/m/", "/m/manifest.json", "/m/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(SHELL).catch(() => undefined)),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

function cacheable(url) {
  if (url.origin !== self.location.origin) return false;
  if (url.pathname.startsWith("/api/")) return false;
  return url.pathname === "/m/" || url.pathname.startsWith("/m/") || url.pathname.startsWith("/assets/mobile");
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (!cacheable(url)) return;
  event.respondWith(
    caches.open(CACHE).then(async (cache) => {
      const cached = await cache.match(request);
      const network = fetch(request)
        .then((response) => {
          if (response.ok) cache.put(request, response.clone());
          return response;
        })
        .catch(() => cached);
      return cached || network;
    }),
  );
});

self.addEventListener("push", (event) => {
  let note = {};
  try {
    note = event.data ? event.data.json() : {};
  } catch (_err) {
    note = { body: event.data ? event.data.text() : "" };
  }
  const title = note.title || "Assistant";
  const options = {
    body: note.body || "",
    tag: note.tag || undefined,
    renotify: Boolean(note.tag),
    icon: "/m/icon-192.png",
    badge: "/m/icon-192.png",
    data: { url: note.url || "/m/", kind: note.kind || "" },
  };
  event.waitUntil(
    Promise.all([
      self.registration.showNotification(title, options),
      self.clients.matchAll({ type: "window" }).then((clients) => {
        for (const client of clients) client.postMessage({ type: "refresh", kind: note.kind || "" });
      }),
    ]),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/m/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if (new URL(client.url).pathname.startsWith("/m")) {
          client.postMessage({ type: "refresh" });
          return client.focus();
        }
      }
      return self.clients.openWindow(target);
    }),
  );
});
