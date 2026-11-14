# Frontend: consola web de ArquiFusion

- **Dueño:** Persona C · **RF:** RF-05, RF-11, RF-15, RF-16 (+ vistas de RF-03/04/07/08/14)
- **Stack:** React 18 + Vite + TypeScript + Tailwind (tokens del diseño *Precision Industrial Dark*), React Router, Leaflet, Recharts.
- **Consume:** `GET/POST /v1/*` (`contracts/openapi.yaml`) y Firestore (`contracts/contratos.md` §5, reglas en `infra/gcp/firestore.rules`).

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
| Datos | `contracts/fixtures/seed/*.json` (los seeds de C1, importados tal cual) + simulación | API Gateway `/v1/*` |
| Login | Selector de los usuarios demo del runbook (`u-op-01`, `u-tec-07`, …) | Cognito `USER_PASSWORD_AUTH`, **ID token** |
| Tiempo real | Mundo simulado (procesar → GestionIncidente → replicar) | Firestore `onSnapshot` (o polling cada 10 s si no hay config de Firebase) |
| Chat | Simulado | Firestore `incidents/{id}/messages`, con caché offline |

Las vistas solo hablan con la interfaz `FleetApi` (`src/api/client.ts`) y con `RealtimeSource` (`src/realtime/types.ts`).
La única pieza que sabe en qué modo corre la app es `src/services.ts`.

**Modo demo para el pitch:** el botón **Simulador** del encabezado inyecta los escenarios de `simulator/` (degradación, falla súbita, combustible, grupal por zona…).
El técnico `u-tec-07` (TEC-07, Pedro Rojas) recibe el incidente de **EX-023** y lo acepta, resuelve y cierra a mano: es el golden path completo.

## Configuración (modo real)

Copia `.env.example` a `.env.local`. Todo lo que va ahí es **público**: el navegador lo ve. Los secretos nunca van en el front.

| Variable | De dónde sale |
|---|---|
| `VITE_API_URL` | URL del stage `v1` de `{p}-api` (B, `infra/base`) |
| `VITE_COGNITO_REGION`, `VITE_COGNITO_CLIENT_ID` | User Pool de B. App client **sin secret** y con `ALLOW_USER_PASSWORD_AUTH` |
| `VITE_FIREBASE_*` | Firebase → Configuración → app web (runbook H0 §4) |

## Lo que el front necesita del backend (pendiente)

1. **CORS (B):** API Gateway con `OPTIONS` en `/v1/*` y `shared/response.py` con `Access-Control-Allow-Origin` y `Access-Control-Expose-Headers: X-Correlation-Id`.
   El front envía `Authorization`, `Content-Type` y `X-Correlation-Id` (acuerdo 3 de `docs/h0-persona-c.md`).
2. **`api-lectura` (C2/C3):** hoy solo responde `/v1/me`. Las demás rutas GET deben devolver exactamente los shapes del OpenAPI (el demo ya los respeta).
3. **`POST /v1/auth/firebase-token` (C6)** con los claims `role`, `zone` y `technician_id`, y **`replicar` (C5)**. Sin ellos, el modo real usa polling y el chat queda deshabilitado.

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
