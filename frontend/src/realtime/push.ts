/**
 * Push web con FCM (RF-16, contratos.md §4-§5).
 * 1. Registra `public/firebase-messaging-sw.js` (recibe los push con la pestaña cerrada o en segundo plano).
 * 2. Pide permiso de notificaciones y obtiene el token con `getToken` (VAPID).
 * 3. El token se manda en el body de POST /auth/firebase-token; api-lectura lo agrega con arrayUnion a
 *    Firestore `users/{uid}.fcm_tokens[]`, que es donde lo busca `notify_bridge` (B).
 * Todo es "mejor esfuerzo": si el navegador no soporta push, no hay config o el usuario niega el permiso,
 * se devuelve null y el tiempo real (Firestore) sigue igual.
 */
import type { FirebaseApp } from "firebase/app";
import { config, hasPush } from "@/config";

const SW_PATH = "firebase-messaging-sw.js";

/** URL del service worker con la config pública de Firebase (el SW no puede leer import.meta.env). */
export function serviceWorkerUrl(base = import.meta.env.BASE_URL ?? "/"): string {
  const f = config.firebase;
  const params = new URLSearchParams({
    apiKey: f.apiKey,
    projectId: f.projectId,
    messagingSenderId: f.messagingSenderId,
    appId: f.appId,
  });
  return `${base.endsWith("/") ? base : `${base}/`}${SW_PATH}?${params}`;
}

export async function registerPush(app: FirebaseApp): Promise<string | null> {
  if (!hasPush || typeof window === "undefined" || !("serviceWorker" in navigator) || !("Notification" in window)) return null;
  try {
    const messaging = await import("firebase/messaging");
    if (!(await messaging.isSupported())) return null;
    const permission = Notification.permission === "default" ? await Notification.requestPermission() : Notification.permission;
    if (permission !== "granted") return null;
    const registration = await navigator.serviceWorker.register(serviceWorkerUrl());
    const token = await messaging.getToken(messaging.getMessaging(app), {
      vapidKey: config.firebase.vapidKey,
      serviceWorkerRegistration: registration,
    });
    return token || null;
  } catch {
    return null; // sin push: el resto de la app no depende de esto
  }
}
