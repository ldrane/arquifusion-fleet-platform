# Frontend: consola web de ArquiFusion

- **Dueño:** Persona C · **RF:** RF-05, RF-11, RF-15, RF-16 (+ vistas de RF-03/04/07/08/14)
- **Stack:** React 18 + Vite + TypeScript + Tailwind (tokens del diseño *Precision Industrial Dark*), React Router, Leaflet, Recharts.
- **Consume:** la API REST (`contracts/openapi.yaml`, stage `v1`, rutas **sin** prefijo `/v1`: `${VITE_API_URL}/me`) y Firestore (`contracts/contratos.md` §5, reglas en `infra/gcp/firestore.rules`).

## Arranque rápido

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173  (modo demo: no necesita AWS ni GCP)
npm run build      # typecheck + build de producción en dist/
npm test           # vitest: ciclo de vida del incidente, RBAC, zona, paginación, scoring
```

## Dos modos, mismas pantallas

| | **Demo** (sin `VITE_API_URL`) | **Real** (`VITE_API_URL` definido) |
|---|---|---|
| Datos | `contracts/fixtures/seed/*.json` (los seeds de C1, importados tal cual) + simulación | API Gateway (`api-lectura` / `api-comandos`) |
| Login | Selector de los usuarios demo del runbook (`u-op-01`, `u-tec-07`, …) | Cognito `USER_PASSWORD_AUTH`, **ID token** |
| Tiempo real | Mundo simulado (procesar → GestionIncidente → replicar) | Firestore `onSnapshot` (o polling cada 10 s si no hay config de Firebase) |
| Chat | Simulado | Firestore `incidents/{id}/messages`, con caché offline |

Las vistas solo hablan con la interfaz `FleetApi` (`src/api/client.ts`) y con `RealtimeSource` (`src/realtime/types.ts`).
La única pieza que sabe en qué modo corre la app es `src/services.ts`.

**Modo demo para el pitch:** el botón **Simulador** del encabezado inyecta **solo** los escenarios que existen en `simulator/scenarios.py` (`degradacion`, `falla_subita`, `combustible`, `grupal_zona`; #27). Los patrones hidráulico, eléctrico y de neumáticos solo aparecen en el historial y el piloto automático.
El técnico `u-tec-07` (TEC-07, Pedro Rojas) recibe el incidente de **EX-023** y lo acepta, resuelve y cierra a mano: es el golden path completo.

## Configuración (modo real)

Copia `.env.example` a `.env.local`. Todo lo que va ahí es **público**: el navegador lo ve. Los secretos nunca van en el front.

| Variable | De dónde sale |
|---|---|
| `VITE_API_URL` | URL del stage `v1` de `{p}-api` (B, `infra/base`) |
| `VITE_COGNITO_REGION`, `VITE_COGNITO_CLIENT_ID` | User Pool de B. App client **sin secret** y con `ALLOW_USER_PASSWORD_AUTH` |
| `VITE_FIREBASE_*` | Firebase → Configuración → app web (runbook H0 §4) |
| `VITE_FIREBASE_MESSAGING_SENDER_ID`, `VITE_FIREBASE_VAPID_KEY` | Firebase → Configuración → Cloud Messaging (ID del remitente y clave pública de *Certificados push web*). Sin ellas no hay push |

Las `VITE_*` se **hornean al build**: tras cambiarlas hay que reconstruir y volver a publicar.
`scripts/deploy_frontend.sh` las toma del entorno o de `frontend/.env.local` (y, si faltan, `VITE_API_URL` y
`VITE_COGNITO_CLIENT_ID` de los outputs `api_url` / `cognito_client_id` de `infra/base`); no imprime valores. Sin `VITE_API_URL`
aborta, salvo `VITE_FORCE_DEMO=true` (demo a propósito). La consola avisa con un banner qué variables faltan (solo nombres), el chat
indica la causa cuando no hay `VITE_FIREBASE_API_KEY`/`PROJECT_ID`, y el asistente muestra el motivo del modo de respaldo de Gemini (`degraded_reason`).

## Integración con el backend

1. **Identidad (#8):** `GET /me` devuelve `technician_id` (claim `custom:technician_id`). El front usa `myTechnicianId(me)`;
   `technicianIdFromUser` (mapeo `u-tec-07` → `TEC-07`) queda solo como respaldo para sesiones viejas.
2. **Tiempo real:** `POST /auth/firebase-token` → `signInWithCustomToken` (claims `role`, `zone`, `technician_id`) →
   `onSnapshot` de `machines`, `incidents`, `technicians` (las escribe `replicar`). Sin config de Firebase: polling cada 10 s.
3. **Push FCM (#15, RF-16):** `src/realtime/push.ts` registra `public/firebase-messaging-sw.js`, pide permiso y obtiene el
   token con `getToken`; lo envía en el body de `POST /auth/firebase-token` (`{ "fcm_token" }`) y `api-lectura` lo guarda en
   `users/{uid}.fcm_tokens[]`. Los `deep_link` `/incidents/{id}` del push redirigen a `/incidentes/{id}`.
4. **Comandos:** `ack`/`assign`/`resolve` devuelven el `Incident` completo con `meta.pending_transition`; el estado final llega por Firestore.
5. **CORS (B):** `OPTIONS` en cada recurso y headers de contratos.md §1.2 en todas las respuestas.

## Estructura

```
src/
  api/        types.ts (espejo del OpenAPI), client.ts (FleetApi), http.ts (API real), errors.ts
  auth/       cognito.ts (login sin SDK), permissions.ts (x-roles → vistas y acciones), AuthContext, sessionStore
  demo/       world.ts (simulación de GestionIncidente), demoApi.ts, analytics.ts, telemetry.ts, assistant.ts, data.ts (seeds)
  realtime/   firestore.ts, polling.ts, demo.ts
  state/      FleetContext (flota en vivo), queryCache (stale-while-revalidate), viewState (estado de UI por vista)
  components/ layout/, ui/, map/FleetMap, incidents/ (tarjeta, acciones, chat), charts/
  views/      CommandCenter, PredictiveHealth, MachineDetail, Dispatch, Inventory, Efficiency,
              IncidentHistory, IncidentDetail, Assistant, Login
```

**Navegación sin perder estado:** el layout y la suscripción de tiempo real se montan una sola vez sobre todas las rutas.
Los filtros, pestañas, borradores del chat y la conversación del asistente viven en `useViewState` (memoria + `sessionStorage`).
Las respuestas de la API viven en `queryCache` y se revalidan en segundo plano. El scroll se recuerda por ruta.
