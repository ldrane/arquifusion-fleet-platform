/** Configuración pública del front (variables VITE_*). Nunca hay secretos aquí: todo esto viaja al navegador. */
const env = import.meta.env;

const clean = (v: string | undefined) => (v ?? "").trim();

export const config = {
  apiUrl: clean(env.VITE_API_URL).replace(/\/+$/, ""),
  cognito: {
    region: clean(env.VITE_COGNITO_REGION) || "us-east-1",
    clientId: clean(env.VITE_COGNITO_CLIENT_ID),
  },
  firebase: {
    apiKey: clean(env.VITE_FIREBASE_API_KEY),
    authDomain: clean(env.VITE_FIREBASE_AUTH_DOMAIN),
    projectId: clean(env.VITE_FIREBASE_PROJECT_ID),
    appId: clean(env.VITE_FIREBASE_APP_ID),
    /** FCM (push web, RF-16): Firebase > Configuración > Cloud Messaging. Sin ellos no se registra push. */
    messagingSenderId: clean(env.VITE_FIREBASE_MESSAGING_SENDER_ID),
    vapidKey: clean(env.VITE_FIREBASE_VAPID_KEY),
  },
  forceDemo: clean(env.VITE_FORCE_DEMO) === "true",
  /** Tablero de Gerencia en Looker Studio sobre BigQuery (TAREA-13). Vacío = no se muestra el botón. */
  lookerUrl: clean(env.VITE_LOOKER_URL),
};

/** Demo si no hay API configurada (o si se fuerza). Ver frontend/README.md. */
export const isDemo = config.forceDemo || !config.apiUrl;
export const hasFirebase = Boolean(config.firebase.apiKey && config.firebase.projectId);
export const hasCognito = Boolean(config.cognito.clientId);
export const hasPush = hasFirebase && Boolean(config.firebase.messagingSenderId && config.firebase.vapidKey && config.firebase.appId);
