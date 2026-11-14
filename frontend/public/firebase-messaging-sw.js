/* Service worker de FCM (RF-16, contratos.md §5). Lo registra src/realtime/push.ts con la config pública
 * de Firebase en la query string (un service worker no puede leer import.meta.env).
 * Muestra los push de notify_bridge (B) cuando la pestaña está cerrada o en segundo plano.
 * El payload `data` trae lo del mensaje Pub/Sub (§4): incident_id, deep_link, severity, title, body. */
/* global importScripts, firebase, clients */
importScripts("https://www.gstatic.com/firebasejs/10.14.1/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/10.14.1/firebase-messaging-compat.js");

const params = new URL(self.location.href).searchParams;
firebase.initializeApp({
  apiKey: params.get("apiKey"),
  projectId: params.get("projectId"),
  messagingSenderId: params.get("messagingSenderId"),
  appId: params.get("appId"),
});

const messaging = firebase.messaging();

messaging.onBackgroundMessage((payload) => {
  const n = payload.notification || {};
  const d = payload.data || {};
  // Si el mensaje ya trae `notification`, FCM lo muestra solo; aquí cubrimos los mensajes solo-`data`.
  if (payload.notification) return;
  self.registration.showNotification(d.title || n.title || "ArquiFusion", {
    body: d.body || n.body || "",
    icon: "/favicon.svg",
    tag: d.incident_id || undefined,
    data: { deep_link: d.deep_link || "/" },
  });
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const link = (event.notification.data && event.notification.data.deep_link) || "/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      for (const w of wins) {
        if ("focus" in w) {
          w.navigate(link);
          return w.focus();
        }
      }
      return clients.openWindow(link);
    }),
  );
});
