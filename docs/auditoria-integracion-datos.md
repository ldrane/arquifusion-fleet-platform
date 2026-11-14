# Auditoría de integración de datos A · B · C

> Fecha: 2026-11-14 · Base: `origin/main` @ `a63ee04` (todas las ramas `feat/*` ya mergeadas).
> Método: tres revisiones paralelas (una por persona). Cada una revisó su parte y sus interfaces con las otras dos, y luego se consolidaron los resultados. Los hallazgos críticos se verificaron a mano en el código.
> Fuente de verdad: `contracts/openapi.yaml`, `contracts/contratos.md`, `contracts/dynamodb.md`, `contracts/fixtures/**`.

**Severidad:** 🔴 rompe el golden path · 🟠 dato incoherente o rompe una feature secundaria · 🟡 deuda o riesgo.
**Tipo:** **Mismatch** = existe, pero no coincide entre partes. **Brecha** = aún no existe y otra parte ya lo asume.

## Resumen ejecutivo

| # | Hallazgo | Sev. | Tipo | Dueño |
|---|---|---|---|---|
| 1 | La flota del simulador no coincide con los seeds y `procesar` sobrescribe el seed | 🔴 | Mismatch | A |
| 2 | Los umbrales de `procesar` disparan alarmas sobre la operación nominal del seed | 🔴 | Mismatch | A (+C) |
| 3 | Faltan recursos en `infra/base` que A y C buscan por nombre | 🔴 | Brecha | B |
| 4 | No hay cableado de EventBridge → SFN, y la SFN es un único `Pass` | 🔴 | Brecha | B |
| 5 | Sin CORS en `shared/response.py` | 🔴 | Brecha | B |
| 6 | `api_lectura` solo implementa `/v1/me`, `replicar` no existe y `firebase-token` no tiene dueño | 🔴 | Brecha | C (+B) |
| 7 | GSI de `anomalies`: tres definiciones distintas | 🟠 | Mismatch | A + B |
| 8 | El claim del técnico es `custom:technician_id` (B) vs `cognito:username` → `user_id` (C) | 🟠 | Mismatch | B + C |
| 9 | `diagnose` depende de `candidate_parts`, que no está en el contrato | 🟠 | Mismatch | A + B |
| 10 | Athena con proyección `injected` sin filtro `operation_id` | 🟠 | Mismatch | A |
| 11 | Ubicación del técnico sin `zone`: desaparece del Firestore por zona | 🟠 | Mismatch | B + C |
| 12 | Fixtures de contrato incoherentes con los seeds | 🟠 | Mismatch | C (+A) |
| 13 | Intervalos de mantenimiento: seed (250/500 h) vs analítica (500/400 h) | 🟠 | Mismatch | A |
| 14 | `notification_rules` no se activa con ningún `IncidentStateChanged` | 🟠 | Mismatch | B + C |
| 15 | Push FCM sin destino: no se sabe dónde se guarda el token y no existe el topic | 🟠 | Brecha | B + C |
| 16 | `assign` desde `detected` siempre devuelve 409 | 🟠 | Mismatch | B |
| 17 | `ack` no registra al actor ni verifica que el técnico sea el asignado | 🟠 | Mismatch | B |
| 18 | `required_specialty` no tiene regla de derivación | 🟠 | Brecha | B |
| 19 | Zona oeste (32 máquinas) sin almacén | 🟠 | Mismatch | C |
| 20–27 | Deuda: nombre del bus, heartbeat, credencial Gemini, variables de entorno, respuestas de comandos, Decimal, `machine_id` vs `machine_ids`, smoke | 🟡 | — | varios |

---

## 🔴 Críticos: rompen el golden path

### 1. La flota del simulador no coincide con los seeds y `procesar` sobrescribe el seed (A)

**Cifras:**
- **Cantidad:** el simulador tiene 84 máquinas y el seed tiene 100. Los IDs del simulador son un subconjunto, así que 16 máquinas del seed nunca reportan.
- **Zonas:** solo 17 de las 84 tienen la misma zona en ambos lados.
- **Coordenadas:** ~550 km de diferencia (simulador `-14.40,-71.95`; seed `-11.95,-76.40`).
- **Horómetro:** difiere ~5 842 h en promedio.
- **Modelos:** el simulador usa `AF-EX350`/`AF-EX520` (`simulator/fleet.py:50`) y el seed `CAT-336`, etc.
- **Máquina de la demo:** EX-023 es `CAT-336`/norte en el seed y en el OpenAPI, y `AF-EX350`/este en el simulador.
- **Escenarios:** sus objetivos por defecto (`EX-001`, `CM-001`, `BD-001`) caen en zonas distintas en cada lado, así que `grupal_zona` deja de ser un grupo de una sola zona.

**Por qué es peor de lo que parece:** `procesar/service.py:213-231` (`_machine_fields`) copia `model`, `zone`, `location` y `operating_hours` de cada lectura al ítem `machines`. Con la primera lectura se pierde el seed. Eso afecta en cadena:
- el GSI `by_zone`;
- el filtro por zona de Firestore;
- el mapa, donde las máquinas saltan de lugar;
- el `GetItem MODEL#AF-EX350` de la SFN, que no existe, así que no hay stock ni repuestos candidatos;
- el plan preventivo.

Además, el upsert no exige `attribute_exists(pk)`, así que un ID desconocido crea una máquina fantasma.

**Fix (A cede ante el contrato):**
- `simulator/fleet.py::build_fleet` lee `contracts/fixtures/seed/machines.json` y `machine_models.json` (IDs, modelo, zona, coordenadas, horas y `nominal`).
- `procesar` no sobrescribe `model`, `type`, `zone` ni `operating_hours` de máquinas sembradas, y exige `attribute_exists(pk)` (si no existe, va a DLQ o se registra en log).

### 2. Los umbrales de la capa 1 disparan sobre la operación nominal del seed (A + C)

`services/ingest/procesar/thresholds_default.json` está calibrado para las líneas base del simulador, no para el `nominal` del seed (`scripts/seed_data.py:41-60`):

| Modelo | `fuel_rate_lph` nominal (seed) | `crit_high` en procesar |
|---|---|---|
| CAT-793F / KOM-930E | 170 / 190 | 140 |
| CAT-994K / KOM-WA900 | 160 / 120 | 60 |
| KOM-PC2000 | 110 | 70 |
| EPI-PV271 | 90 | 65 |

`pressure_bar` de KOM-PC2000 (320) y de EPI-PV271 (350) queda justo en `warn_high`. Entre 11 y 15 combinaciones de modelo y variable superan `warn_high` con la media + 2σ.

**Consecuencia:** al corregir el hallazgo 1, unas 70 máquinas quedan en high/critical de forma permanente. Eso genera una tormenta de incidentes y la demo se vuelve ilegible.
**Fix (A):** derivar los umbrales **por modelo** desde `machine_models.nominal` (por ejemplo, warn = μ+3σ y crit = μ+4σ) y publicarlos en SSM `/thresholds/{model}`. Los dos fixes tienen que salir **juntos**.

### 3. Faltan en `infra/base` recursos que A y C buscan por nombre (B)

| Recurso esperado (contratos §9) | Quién lo asume | Estado |
|---|---|---|
| REST API `arquifusion-{stage}-api`, stage `v1` | `infra/ingest/main.tf:51` (data source), `infra/query/main.tf:91` | **No existe**, así que el `terraform plan` de A falla y no hay `POST /telemetry` |
| Cognito User Pool + 6 grupos + usuarios `u-tec-07`… | front, `api_lectura`, `h0-persona-c.md:135-137` | No existe |
| Tablas `{p}-insights` y `{p}-maintenance-records` | `infra/ingest/main.tf:33-34`, `analytics.tf`, `ai.tf:65` | No existen (`maintenance-records` tampoco tiene seed) |
| SNS `{p}-platform-alarms` | `infra/ingest/ingest.tf:10` | Solo existen `alerts-{rol}` |
| Secretos `gcp/service-account` y `bridge-gcp` | `replicar`, `notificar`, H0 | No existen |

**Fix (B):** completar B0 en `infra/base`, agregar las dos tablas a `contracts/dynamodb.md` y exportar los outputs.

### 4. No hay cableado de eventos hacia la SFN (B, brecha)
- No existe ninguna `aws_cloudwatch_event_rule`, así que el `AnomalyDetected` que emite `procesar` (`procesar/service.py:29-30`, correcto según §3) no llega a ningún consumidor.
- `infra/incidents/main.tf` es solo un TODO y `gestion_incidente.asl.json` tiene un único estado `Pass`.
- `scoring`, `correlacion`, `notificar`, `auditoria` y `notify_bridge` lanzan `NotImplementedError`.

**Fix (B):** reglas `source=arquifusion.processor` y `arquifusion.heartbeat` → SFN, y la máquina de estados real.

### 5. Sin CORS (B)
- `services/shared/arquifusion_shared/response.py:10` solo devuelve `Content-Type` y `X-Correlation-Id`.
- El front llama desde el navegador con `Authorization` y `X-Correlation-Id` (`frontend/src/api/http.ts:37-45`), así que todo `/v1/*` falla en modo real.
- C ya lo había pedido (acuerdo 3 en `h0-persona-c.md:129`).

**Fix (B):** headers CORS en `_resp` y `OPTIONS` en API Gateway.

### 6. Front real sin datos ni tiempo real (C, + B en la asignación de dueño)
- `api_lectura/service.py:64-66` implementa solo `GET /v1/me`. Los otros 18 GET responden 404.
- `replicar/service.py:18` lanza `NotImplementedError`, e `infra/query` no despliega `replicar` ni sus mapeos de Streams.
- `POST /v1/auth/firebase-token` **no tiene dueño claro**: el contrato lo asigna a api-ack (B), `division-trabajo-backend.md:86` a C, e `iam.tf:9` a C. No está en las `ROUTES` de nadie.
  - Sin ese endpoint, `frontend/src/realtime/firestore.ts:178` falla y el chat queda muerto.

**Fix:** definir el dueño de `firebase-token` (propuesta: C, dentro de `api_lectura`) e implementar los GET del golden path primero.

---

## 🟠 Mismatches de datos y features secundarias

### 7. GSI de `anomalies`: tres definiciones (A + B)
- `contratos.md §9` y `procesar` (`service.py:239-240`, `repository.py:9`) escriben `gsi1pk = {zone}#{YYYY-MM-DD}` y `gsi1sk = timestamp`.
- `dynamodb.md` e `infra/base/main.tf` (tabla `anomalies`) crean `by_zone` con `zone` → `detected_at`.
- `procesar` **nunca escribe `detected_at`**. Como el GSI es disperso, queda vacío, y la correlación por zona (RF-12) y el timeline de C no encuentran nada.

**Fix:** elegir **uno**. Propuesta: `procesar` escribe `detected_at` (timestamp de la lectura), se quitan los campos `gsi1*` y se corrige §9.

### 8. Identidad del técnico (B + C)
- **B:** `api_comandos/service.py:178` lee `custom:technician_id`.
- **C:** el seed usa `cognito:username = u-tec-07` → `technicians.user_id` → `TEC-07` (`seed_data.py:235`, `frontend/src/lib/ids.ts:26`). `firestore.rules:32,46` espera el claim `technician_id` en el custom token de Firebase.
- La fixture `get_me.event.json` no trae `custom:technician_id`.
- **Consecuencia:** `PUT /v1/technicians/me/status` responde 400 siempre, así que el técnico no puede reportar disponibilidad ni ubicación, que son entradas del scoring.

**Fix:** un solo mecanismo documentado en `contratos.md`. Propuesta: atributo `custom:technician_id` en Cognito, poblado por el seed de usuarios y agregado a la fixture.

### 9. `diagnose` depende de `candidate_parts`, que no está en el contrato (A + B)
- `ia_tasks.py:49-50` filtra `parts_suggested` contra `payload.candidate_parts`, un campo que no está en `contratos §8` ni en `fixtures/ia/diagnose_request.json`.
- Con la request del contrato, la respuesta siempre trae `parts_suggested: []`. La fixture de respuesta, en cambio, promete `["CMP-014"]` y no incluye `prompt_version`.

**Fix:**
- Agregar `candidate_parts[] {component_id, name}` a §8 y a la fixture. La SFN los arma con `MODEL#…component_ids` + `catalog`.
- Corregir el modelo de la fixture a `CAT-336`.

### 10. Athena: proyección `injected` sin filtro (A)
- `infra/ingest/lake.tf:123` declara `projection.operation_id.type = "injected"`.
- `daily_machine_stats.sql` y `retrain/training.sql` no filtran `operation_id`. Athena falla con CONSTRAINT_VIOLATION, así que AnalisisDiario y Reentrenamiento no corren e `insights` queda vacío para C.

**Fix:** agregar `WHERE operation_id = 'OP-01'` en ambos SQL, o usar una proyección `enum`.

### 11. El técnico desaparece del Firestore por zona al actualizar su ubicación (B + C)
- B guarda `location` tal como llega (`{lat, lon}` desde `Dispatch.tsx`, sin `zone`).
- `firestore.rules:31` y `firestore.ts:218` filtran por `location.zone`.
- El modo demo lo enmascara: `demo/world.ts:797` agrega `zone`.

**Fix:** B conserva `location.zone = item.zone`, o reglas y consulta usan el `zone` de primer nivel.

### 12. Fixtures de contrato incoherentes con los seeds (C, + A)

| Fixture | Valor | Seed |
|---|---|---|
| `api/telemetry_batch.json` (EX-023) | `model: "EX-350"`, `-12.0464,-77.0428` (Lima) | `CAT-336`, `-11.9132,-76.3998` |
| `ia/diagnose_request.json` | `EX-350` | `CAT-336` |
| `internal/scoring_request.json` | ubicación en Lima, `required_specialty: hidraulica` | la demo es una degradación de motor (CMP-014) |
| `internal/scoring_response.json` | TEC-03 como 2.º candidato; `tech_id`/`eta_min` | TEC-03 es de la zona este y eléctrica; el front usa `technician_id` |
| `events/machine_silent.json` | `expected_interval_s: 60` | 30 |

Como `procesar` copia lo que llega (hallazgo 1), probar con estas fixtures mueve EX-023 unos 70 km y la cambia de zona.

**Fix (C):** regenerar las fixtures desde `seed_data.build_all()` y que sean un test (`scripts/tests`).

### 13. Intervalos de mantenimiento distintos (A)
- **Seed:** `maintenance_interval_h` es 250 h (500 h en camiones), con 16 h/día. Con eso, 53 de 100 máquinas ya salen vencidas al 2026-11-14 y en estado `operational`.
- **Analítica (A):** `analytics_common/fleet.py:14-22` usa 500/400 h a 10 h/día y `CAPACITY_TPH` propio. Además, `preventivo` sobrescribe `next_maintenance_at`.

**Fix:**
- A lee `maintenance_interval_h` y `payload_t` desde `catalog MODEL#…`.
- C revisa si 53 máquinas vencidas es lo que quiere para la demo.

### 14. `notification_rules` no se activa con ningún evento real (B + C)
- Los `event_type` del seed son `incident.detected|escalated|closed`, `machine.silent`, `parts.shortage` y `report.daily`.
- `IncidentStateChanged` trae `from`/`to` con los valores de `incident.status`, y `escalated` no es un estado.
- Tampoco hay reglas para `assigned`/`in_progress`, ni implementación del canal `dashboard`.

**Fix:** tabla **transición → `event_type`** en `contratos.md` y ajustar el seed a esa tabla.

### 15. Push FCM sin destino (B + C)
- El mensaje Pub/Sub apunta a `target.user_id`, pero ningún contrato define dónde se guarda el `fcm_token`.
- El front no registra FCM: no llama a `getToken` y no tiene service worker.
- El topic `notificaciones` no existe en `infra/gcp`.

**Relación con GCP sin facturación:** Pub/Sub y Cloud Functions requieren billing. Si se elimina el puente y `notificar` llama directo a FCM HTTP v1, igual hay que definir dónde vive el token. Propuesta: el doc Firestore `users/{uid}.fcm_tokens[]`.

### 16. `assign` desde `detected` siempre devuelve 409 (B)
- `service.py:130` acepta el estado `detected`, pero `:133` exige `ack_token`, que solo existe mientras la SFN espera la aceptación.
- El front muestra "Asignar" en `detected` (`IncidentActions.tsx:29`).

**Fix:** agregar a la SFN un estado con token para la asignación manual, o quitar `detected` del front y de la validación.

### 17. `ack` sin actor ni verificación de propiedad (B)
- `ack`, `assign` y `resolve` no envían a la SFN `cognito:username` ni el rol, así que `auditoria` no sabe quién actuó (TRZ-02).
- El ack de un técnico no verifica que el incidente sea suyo: cualquier técnico puede aceptar un incidente ajeno por REST, aunque el front y `firestore.rules:46` sí lo impiden.

### 18. `required_specialty` no tiene regla (B)
`scoring_request.json` lo pide, pero `AnomalyDetected` solo trae variables (`vibration_mm_s`…). **Fix:** derivarlo de `catalog.specialty` del primer repuesto sugerido, o fijar una tabla variable → especialidad en `contratos.md`.

### 19. La zona oeste (32 máquinas, la mayor) no tiene almacén (C)
- `warehouses.json` solo trae WH-01..03 (norte, sur y este).
- TEC-04, TEC-09 y TEC-12 usan WH-01 (norte) como base.
- El pronóstico de repuestos (`analytics/repuestos/service.py:104-110`) deja fuera las máquinas de oeste.
- Además, `warehouses` es solo una fixture: no se carga a DynamoDB, así que la SFN no tiene coordenadas de almacén.

**Fix (C):** agregar WH-04 en oeste y cargar `warehouses` a DynamoDB.

---

## 🟡 Deuda y riesgos

20. **Nombre del bus:** las fixtures `events/*.json` y `contratos §3` usan `EventBusName: "fleet-events"`, pero el real es `arquifusion-{stage}-fleet-events` (`infra/base/events.tf:3`). `put-events --entries file://` falla. Corregir §3 y el README de las fixtures.
21. **Margen del heartbeat:** el seed tiene `expected_interval_s = 30`, lo que da silencio a los 90 s; el simulador envía cada 60 s por defecto (`cli.py:37`). Un retraso provoca una tormenta de `MachineSilent`. Además, `MachineSilent` no trae `zone` y no pasa por el lock `open_incident_id`, así que la SFN tiene que deduplicar.
22. **Credencial de Gemini:** A usa la API key de AI Studio (`arquifusion/{stage}/gemini/api-key`, `ai.tf:17`), pero `infra/gcp/iam.tf:17` otorga `aiplatform.user` "para ia-gemini" y `h0-persona-c.md:148` dice que usa la service account. Mantener la API key: no requiere facturación en GCP. Quitar `aiplatform.user` y corregir H0.
23. **Variables de entorno:** B usa `INCIDENTS_TABLE`, A usa `TABLE_*` y C usa `TABLE_PREFIX`. Unificarlas en `services/shared`.
24. **Respuestas de `api_comandos` fuera de contrato:** devuelven objetos parciales y no `Incident`/`Technician`. `resolve` responde `status: "resolved"` aunque el incidente sigue en `in_progress`. Hoy el front ignora el cuerpo, así que no rompe nada.
25. **Decimal en JSON:** `response.py` usa `json.dumps(default=str)`, así que los números de DynamoDB salen como texto (`"92"`) en `api_lectura`.
26. **`machine_id` vs `machine_ids`:**
    - El GSI `by_machine` de `incidents` usa `machine_id` escalar, pero el OpenAPI y `ia_tools.py:156` usan `machine_ids[]`. B debe escribir los dos.
    - Los ítems `EVT#` no deben llevar `incident_id`/`status`: A escanea la tabla (`kpis_report/service.py:102`) y los contaría dos veces.
    - `replicar` debe ignorar los `EVT#`.
    - `kpis` se guarda sin zona, así que `?zone=` no se puede cumplir.
27. **Otros detalles:**
    - Smoke y escenarios:
      - `smoke_golden_path.sh` sigue siendo un TODO, y su comando comentado no incluye el subcomando `stream` que exige `simulator/cli.py`.
      - `infra/ingest/outputs.tf` está vacío: no expone la URL ni la API key del simulador.
      - El escenario `degradacion` del simulador ataca la "primera excavadora", no EX-023.
      - Los escenarios de la demo del front (`presion`, `electrico`, `neumaticos`) no existen en el simulador.
    - Contrato y configuración:
      - `servers.stage` del OpenAPI (`dev-ana`…) no coincide con el stage real `v1`.
      - `AuditEvents` no tiene lector.
      - `notificar` no tiene un store definido para dedup/throttle.
      - Los topics `alerts-*` no tienen suscripciones.
      - `rbac.require` no valida la zona.
      - `correlation_id_path="correlation_id"` no existe en los eventos de API Gateway.

---

## ✅ Verificado y alineado

- **Tablas:** nombres de las 10 tablas, pk/sk y los GSIs de `machines` (`by_zone`), `technicians`, `inventory` (`by_component`) e `incidents` (`by_machine`, `by_status`) son iguales en `dynamodb.md`, `infra/base` y `seed.py`. TTL, PITR y Streams (NEW_AND_OLD_IMAGES) están activos.
- **Claves compartidas:** `OP-01#EX-023`/`META` es igual en `procesar`, `heartbeat` y `seed`. `TECH#…/META` e `INC#…/META` coinciden. El dedup (`open_incident_id`, `anomaly_lock_until`) cumple §9.
- **Telemetría:** `POST /telemetry` coincide con el modelo de API Gateway y con `TelemetryReading` del OpenAPI. El envoltorio SQS es igual entre `ingest.tf` y `message.py`.
- **Eventos:** `source`/`detail-type` y `detail.data` de `AnomalyDetected` y `MachineSilent` coinciden con §3 y sus fixtures. `top_factors` cumple `Factor`.
- **Lake:** las columnas son iguales en `lake.py` y `lake.tf`, y las particiones coinciden con Firehose.
- **Enums y roles:** `severity`, `incident.status` y los 6 roles son idénticos en `rbac.py`, el OpenAPI, `permissions.ts`, los SNS topics y `firestore.rules`.
- **Comandos:** rutas, métodos y bodies de los comandos coinciden en el OpenAPI, `http.ts` y `api_comandos`.
- **Seeds:**
  - Son consistentes por dentro: 100 máquinas con modelo válido, coordenadas dentro de su zona, catálogo e inventario válidos y reglas con roles válidos. Las fixtures coinciden byte a byte con `build_all()`.
  - Golden path en el seed: EX-023 es `CAT-336`/norte, hay técnicos de motor en norte (TEC-01, TEC-07) y CMP-014 tiene stock en WH-01.
- **Front:** el modo demo importa los seeds (`@seed`) y no genera una flota propia. Los tipos de `types.ts` coinciden con el OpenAPI. El `tsc` pasa y vitest da 15/15.
- **Insights:** los nombres y campos de los ítems coinciden con el OpenAPI y el front.
- **ia-gemini:** la salida (`result`, `degraded`, `prompt_version`…) cumple §8. Existe el SSM `/lambda/ia-gemini/arn`.

---

## Plan de acción sugerido (orden por impacto en la demo)

**Decisiones que hay que tomar en equipo antes de codificar** (actualizar `contracts/` en un solo PR):
1. GSI de `anomalies`: `by_zone(zone, detected_at)` vs `gsi1`. Propuesta: `detected_at`. → #7
2. Identidad del técnico: `custom:technician_id` en Cognito. → #8
3. Dueño de `/v1/auth/firebase-token`. Propuesta: C. → #6
4. `candidate_parts` en `diagnose` y la regla de `required_specialty`. → #9, #18
5. Tabla transición → `event_type` y dónde vive el token FCM (sin Pub/Sub si GCP queda sin facturación). → #14, #15
6. Nombre del bus en §3. → #20

**Persona A:** simulador desde los seeds y `procesar` sin sobrescribir datos (#1, que va junto con los umbrales por modelo de #2), escribir `detected_at` (#7), filtro de Athena (#10), intervalos desde `MODEL#` (#13), outputs de ingest y escenario `degradacion` sobre EX-023 (#27).

**Persona B:** completar B0 en `infra/base`: API, Cognito, `insights`, `maintenance-records`, `platform-alarms` y secretos (#3); CORS (#5); reglas EventBridge → SFN real (#4); claim y actor en `api_comandos` (#8, #17); `location.zone` (#11); `assign` desde `detected` (#16).

**Persona C:** GET del golden path en `api_lectura` y `replicar` (#6), `firebase-token` (si se confirma que es de C), regenerar las fixtures desde los seeds con un test (#12), WH-04 en oeste y `warehouses` en DynamoDB (#19), `expected_interval_s` (#21), smoke real (#27).
