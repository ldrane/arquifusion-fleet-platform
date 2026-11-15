# Rúbrica → evidencia (TAREA-19)

Matriz que conecta **cada criterio de la rúbrica** (`docs/rubrica.md`) con la **evidencia concreta**: el archivo del repo que lo sustenta y la pantalla de la demo donde se ve. Sirve para dos cosas: ensayar el pitch señalando la evidencia, y responder preguntas del jurado con el archivo exacto.

Criterios y puntaje (total 20): problemas del contexto **3** · persistencia/HA **2** · Step Functions **2** · 2+ nubes **3** · arquitectura **3** · pitch **2** · serverless **2** · IA **3**.

---

## 1. Resolver la mayor cantidad de problemas del contexto — **3 pts**

Fuente: `docs/contexto.md` (14 dolores) y trazabilidad en `docs/requerimientos.md` §7.

| Dolor del contexto | Solución real | Evidencia (archivo) | Pantalla de la demo |
|---|---|---|---|
| Falla inesperada | Detección en 3 capas y anomalía → incidente | `services/ingest/procesar/`, `services/ml/arquifusion_ml/` | Mapa: pin en rojo tras inyectar la falla |
| Comportamiento conjunto de variables | z-score por variable + top-3 factores | `services/ingest/procesar/service.py` | Detalle del incidente: factores y z-scores |
| Mantenimiento preventivo (innecesario vs. atrasado) | Plan por condición vs. calendario | `services/analytics/preventivo/` | Plan preventivo (bloque 4) |
| Repuestos (demanda y reubicación) | Recomendación de stock por almacén | `services/analytics/repuestos/`, `scripts/seed.py` (warehouses) | Pantalla de repuestos: faltantes y reubicación |
| Ubicación y tiempo de respuesta | Mapa por zona + ranking por distancia | `frontend/src/` (mapa), `services/incidents/scoring/` | Mapa con zonas y ranking de técnicos |
| Asignación de técnicos | Scoring por especialidad, distancia y carga | `services/incidents/scoring/service.py` | Desglose del ranking del incidente |
| Consumo de combustible | Análisis de desvíos por máquina/modelo | `services/analytics/combustible/` | Pantalla de combustible |
| Productividad de la flota | Utilización y sobre/subutilización | `services/analytics/productividad/` | Pantalla de productividad |
| Comportamiento inusual | Baseline propio + cohorte + IsolationForest | `services/ingest/procesar/service.py`, `services/ml/` | Badge del modelo v3 + anomalía detectada |
| Comunicación por rol y urgencia | Chat por incidente + notificaciones por rol | `infra/gcp/firestore.rules`, `services/incidents/notificar/` | Chat en vivo + Telegram/FCM |
| Historial de incidentes por máquina | Ledger append-only `EVT#` + tabla `audit-events` | `services/incidents/auditoria/`, `infra/base/main.tf` | Detalle de la máquina: historial y línea de tiempo |
| Incidentes multi-máquina | Correlación por zona y ventana temporal | `services/incidents/correlacion/` | Incidente padre con máquinas correlacionadas |
| Planificación con datos históricos | Firmas pre-falla sobre el histórico | `services/analytics/precursores/` | "CAT-336: 78 % de fallas, +1,5σ a 18 h" |
| Escalar a miles de máquinas sin infra. fija | Pago por uso, DR multinube | `docs/costos.md`, `services/query/export_gcp/` | Tabla N=10.000 + cierre en USD protegidos |

## 2. Persistencia y alta disponibilidad de los datos — **2 pts**

| Evidencia | Archivo |
|---|---|
| DynamoDB on-demand con **PITR** y **Streams** `NEW_AND_OLD_IMAGES` en todas las tablas | `infra/base/main.tf` |
| Réplica **DynamoDB → Firestore** (máquinas, incidentes, técnicos) para tiempo real y offline | `services/query/replicar/`, `infra/gcp/firestore.tf` |
| **DR multinube**: export diario del lake, incidentes cerrados e insights a BigQuery (sandbox) + tablero Looker | `services/query/export_gcp/`, `infra/gcp/bigquery.tf` |
| **Offline en campo**: el SDK de Firestore encola y sincroniza sin red | `frontend/src/realtime/firestore.ts`, `docs/arquitectura-solucion-aws.md` §4 Flujo F |
| **Idempotencia** (no se duplican lecturas) y TTL | `services/ingest/procesar/`, `infra/base/main.tf` |

**Pantalla:** badge LIVE (bloque 3), cambios en vivo por Firestore, y la frase de cierre «si AWS cae, el historial vive en BigQuery, en otra nube».

## 3. Uso de Step Functions para automatización — **2 pts**

| Evidencia | Archivo |
|---|---|
| **3 state machines reales**: `GestionIncidente` (Standard), `AnalisisDiario` y `Reentrenamiento` | `services/incidents/sfn/gestion_incidente.asl.json`, `services/analytics/sfn/analisis_diario.asl.json`, `services/analytics/sfn/reentrenamiento.asl.json` |
| `waitForTaskToken` (espera humana de ack/resolve con `TimeoutSeconds`), `Parallel`, `Map`, `Choice`, `Catch States.Timeout` (escalamiento) | `services/incidents/sfn/gestion_incidente.asl.json` |
| `analisis-diario` y `reentrenamiento` con diagrama ASL y alarmas de fallo | `infra/ingest/analytics.tf` |

**Pantalla:** ejecución de `arquifusion-<stage>-gestion-incidente` corriendo en vivo mientras el pin cambia a rojo; transición a `in_progress` tras el ack del jurado.

## 4. Uso de 2 nubes o más — **3 pts**

| Nube | Rol real (no decorativo) | Evidencia |
|---|---|---|
| **AWS** | Decide: ingesta, ML, orquestación, ledger, notificaciones | `infra/base`, `infra/ingest`, `infra/incidents`, `infra/query` |
| **GCP** | Llega al campo y recuerda: Firestore (tiempo real/offline), FCM, Gemini, BigQuery (DR), Looker, Firebase Hosting | `infra/gcp/`, `services/query/export_gcp/`, `gcp/functions/notify_bridge/`, `infra/gcp/firestore.rules` |

**Pantalla:** Telegram (GCP → móvil) moviendo la Step Function de AWS; Firestore en vivo; tabla BigQuery + Looker.
**Plan B de pregunta:** «una tercera nube sería decorativa» (decisión **D2**).

## 5. Arquitectura de la solución — **3 pts**

| Evidencia | Archivo |
|---|---|
| Documento de arquitectura AWS+GCP con flujos A–G | `docs/arquitectura-solucion-aws.md` |
| Diagrama editable cuyo contenido existe en Terraform | `arquitectura-arquifusion.drawio`, `docs/arquitectura.png` |
| Contratos como fuente de verdad (REST + eventos + Firestore) | `contracts/openapi.yaml`, `contracts/contratos.md` |
| Decisiones de diseño y no-funcionales (RBAC 6 roles, concurrencia, zero-trust) | `docs/concurrencia-lambda.md`, `docs/requerimientos.md` |

**Pantalla:** el diagrama del bloque 2, con la frase «cada caja existe en Terraform o en el deploy por defecto».

## 6. Pitch de 5 minutos — **2 pts**

| Evidencia | Archivo |
|---|---|
| Guion cronometrado con hablante, pantalla, frase exacta y plan B por bloque | `docs/pitch.md` |
| Modelo de costos para la diapositiva de escala | `docs/costos.md` |
| Ensayo 3 veces con cronómetro + preflight verde | `scripts/demo_preflight.sh`, `scripts/demo_reset.py` |

## 7. Solución completamente serverless — **2 pts**

| Evidencia | Archivo |
|---|---|
| Sin EC2 ni clústeres: API Gateway, SQS, Lambda, DynamoDB, Step Functions, EventBridge, Firehose, Athena | `infra/base`, `infra/ingest`, `infra/incidents`, `infra/query` |
| Única "computación en VPC" es la Lambda `auditoria` (sin NAT, con Gateway Endpoint de DynamoDB) | `infra/incidents/vpc.tf` |
| Simulador serverless ("gemelo de flota") en lugar de depender de la laptop | `services/ingest/sim_driver/`, `infra/ingest/sim.tf` |
| Concurrencia reservada acotada para el tope del Learner Lab | `docs/concurrencia-lambda.md` |

**Pantalla:** lista de Lambdas en la consola; ausencia de EC2; inyección de la falla desde la consola (no desde una laptop).

## 8. Uso de IA en la solución — **3 pts**

| Evidencia | Archivo |
|---|---|
| Detección con ML: IsolationForest versionado + z-score EWMA propio y de cohorte | `services/ml/arquifusion_ml/`, `services/ingest/procesar/` |
| Diagnóstico LLM con **cadena resiliente** `gemini → bedrock → determinista` y badge del proveedor | `services/ai/ia_gemini/` |
| Asistente conversacional con *function calling* | `services/ai/ia_gemini/`, ruta `POST /v1/assistant/chat` |
| Resúmenes por rol, causa común y resumen del chat al cierre | `services/ai/ia_gemini/`, `services/incidents/incidente/service.py` |
| Firmas pre-falla (patrones históricos) y KPIs/reporte ejecutivo | `services/analytics/precursores/`, `services/analytics/kpis_report/` |

**Pantalla:** diagnóstico de Gemini con factores y z-scores; badge del proveedor («Motor determinista» si se cae Gemini); respuesta del asistente; firmas pre-falla; resumen de cierre + USD protegidos.

---

## Cómo usar esta matriz el día de la demo

1. Antes de subir: recorrer las 8 filas y confirmar que cada «pantalla de la demo» está a un clic de distancia.
2. Durante el pitch: no leer el archivo en voz alta; usarlo solo como respaldo mental del bloque que toca.
3. Si el jurado pide "muéstrame dónde está eso en el código": abrir la columna **Evidencia (archivo)** de la fila en cuestión.
4. Preguntas frecuentes y su evidencia: multinube (fila 4), «¿es mock?» (fila 7 + badge LIVE), «¿y si la IA cae?» (fila 8, cadena resiliente), «¿cómo escala?» (fila 1, última fila + `docs/costos.md`).
