/* The production build writes precache-manifest.js beside this file. */
try { importScripts("./precache-manifest.js"); } catch { /* dev server may not have a generated manifest */ }

const VERSION = "answer-recorder-v3-uncertain-options";
const CACHE_PREFIX = "answer-recorder-";
const SHELL = `${VERSION}-shell`;
const FALLBACK_ASSETS = ["./", "./index.html", "./manifest.webmanifest", "./icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((cache) => cache.addAll(self.__ANSWER_RECORDER_PRECACHE || FALLBACK_ASSETS)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key.startsWith(CACHE_PREFIX) && key !== SHELL).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
      .then(() => self.clients.matchAll({ type: "window", includeUncontrolled: true }))
      .then((clients) => clients.forEach((client) => client.postMessage({ type: "PRECACHE_READY", cache: SHELL }))),
  );
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "CHECK_PRECACHE") event.source?.postMessage({ type: "PRECACHE_READY", cache: SHELL });
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET" || new URL(event.request.url).origin !== self.location.origin) return;
  event.respondWith((async () => {
    const cache = await caches.open(SHELL);
    const cached = await cache.match(event.request, { ignoreVary: true }) || await cache.match(new URL(event.request.url).href, { ignoreVary: true });
    if (cached) return cached;
    try {
      const response = await fetch(event.request);
      if (response.ok) void cache.put(event.request, response.clone());
      return response;
    } catch {
      if (event.request.mode === "navigate") return (await cache.match(new URL("./index.html", self.registration.scope), { ignoreVary: true })) || Response.error();
      return Response.error();
    }
  })());
});
