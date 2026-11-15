/*
 * Service worker mínimo de la PWA (TAREA-17): cache-first del *app shell* para que el técnico
 * pueda abrir la app sin señal y una vez cargada sincronice por Firestore.
 *
 * Decisión de scope: `firebase-messaging-sw.js` (FCM) se registra en `src/realtime/push.ts` y, por
 * defecto, solo cuando el usuario habilita las notificaciones. Como ambos comparten el scope raíz,
 * el último registro gana ese scope; para no romper el push, este worker:
 *   1. nunca intercepta `googleapis.com` (Firestore/Auth/Gemini) ni `execute-api` (API Gateway): deja
 *      que la red responda siempre;
 *   2. solo sirve del caché el *app shell* estático (navegación y `/assets/*`), nunca respuestas de la API.
 * Si en el pitch se habilita FCM y `firebase-messaging-sw.js` toma el scope, la app sigue funcionando en
 * línea; para el offline estricto, el equipo puede fusionar el bloques de caché en `firebase-messaging-sw.js`.
 */
const SHELL_CACHE = "arquifusion-shell-v1";
const SHELL = ["/", "/index.html", "/manifest.webmanifest", "/favicon.svg", "/icons/icon-192.png", "/icons/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL_CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

/** No tocar: peticiones externas (Gemini, Firestore, Auth) y la API real. */
function isPassthrough(url) {
  return (
    url.origin !== self.location.origin ||
    url.hostname.endsWith("googleapis.com") ||
    url.hostname.includes("execute-api") ||
    url.hostname.endsWith("firebaseio.com") ||
    url.pathname.startsWith("/api/")
  );
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (isPassthrough(url)) return; // sin `respondWith` → red normal

  // Navegaciones: network-first con fallback al shell cacheado (SPA offline).
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(SHELL_CACHE).then((c) => c.put("/index.html", copy));
          return res;
        })
        .catch(() => caches.match("/index.html").then((r) => r || caches.match("/"))),
    );
    return;
  }

  // Estáticos compilados: cache-first (hashed assets son inmutables).
  if (url.pathname.startsWith("/assets/") || SHELL.includes(url.pathname)) {
    event.respondWith(caches.match(req).then((r) => r || fetch(req)));
  }
});
