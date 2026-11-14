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
  },
  forceDemo: clean(env.VITE_FORCE_DEMO) === "true",
};

/** Demo si no hay API configurada (o si se fuerza). Ver frontend/README.md. */
export const isDemo = config.forceDemo || !config.apiUrl;
export const hasFirebase = Boolean(config.firebase.apiKey && config.firebase.projectId);
export const hasCognito = Boolean(config.cognito.clientId);
