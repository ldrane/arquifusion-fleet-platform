# Requerimientos — Plataforma de Gestión de Flota ArquiFusion Corp

> Documento derivado de `contexto.md` y `rubrica.md`.
> Prioridad: **Alta** (necesario para la rúbrica), **Media** (suma puntos, deseable), **Baja** (si sobra tiempo).

---

## 1. Objetivo

Construir una plataforma **100% serverless y multinube** que reciba telemetría simulada de maquinaria pesada. Con esos datos debe:
- detectar anomalías y predecir fallas con IA,
- automatizar la respuesta a incidentes con Step Functions,
- y convertir los datos operativos en **decisiones**: qué máquina atender, con qué técnico, con qué repuesto y a quién avisar.

No basta con un dashboard que solo muestre datos.

---

## 2. Actores / Stakeholders

| Actor | Necesidad principal | Urgencia / canal |
|---|---|---|
| Operador | Estado de su máquina y alertas inmediatas de seguridad | Inmediata, en la app o por SMS |
| Técnico | Detalle del incidente, ubicación, diagnóstico sugerido y repuestos | Inmediata, por push o SMS |
| Responsable de mantenimiento | Cola de incidentes priorizada, asignación de técnicos y plan preventivo | Alta, por email o dashboard |
| Supervisor de operación | Mapa de la flota, disponibilidad e incidentes por zona | Media, por dashboard |
| Administrador de operación | Productividad, combustible, costos y stock de repuestos | Baja, con reporte diario |
| Gerencia / empresa | KPIs agregados (disponibilidad, MTBF, MTTR, costo) | Baja, con reporte semanal |

**Permisos en el canal del incidente (RF-16):**

| Actor | Permiso |
|---|---|
| Operador, técnico asignado, responsable de mantenimiento | Leer y escribir; cambiar estado (según rol) |
| Supervisor de operación | Leer y escribir |
| Almacén / especialista invitado | Leer y escribir mientras esté invitado |
| Administrador de operación, gerencia | Solo lectura |

---

## 3. Requerimientos funcionales

### RF-01 Ingesta de telemetría — **Alta**
- RF-01.1 Recibir lecturas por máquina con: `machine_id`, modelo, tipo, `timestamp`, ubicación (lat/lon, zona), horas de operación, temperatura, vibración, presión, consumo de combustible, carga, velocidad, RPM y estado.
- RF-01.2 Incluir un simulador de flota configurable (N máquinas, frecuencia de envío, inyección de fallas: progresivas, súbitas y grupales por zona).
- RF-01.3 Validar y normalizar los mensajes. Los mensajes inválidos van a una DLQ.
- RF-01.4 Soportar envío en lote (batch) y en tiempo casi real.

### RF-02 Detección de anomalías y mantenimiento predictivo — **Alta**
- RF-02.1 Detectar anomalías **univariadas** con umbrales por modelo de máquina.
- RF-02.2 Detectar anomalías **multivariadas**, por ejemplo temperatura, vibración y combustible juntos, con un modelo de IA (Isolation Forest, autoencoder o Random Cut Forest).
- RF-02.3 Analizar la **tendencia temporal**: pendiente o deriva de cada variable en ventanas de 1 h, 24 h y 7 días.
- RF-02.4 Calcular un **Health Score (0–100)** y un **nivel de severidad** por máquina: Info, Baja, Media, Alta o Crítica.
- RF-02.5 Estimar la probabilidad de falla y la vida útil remanente (RUL) aproximada.
- RF-02.6 Generar con LLM un diagnóstico en lenguaje natural: causa probable y acción sugerida.

### RF-03 Mantenimiento preventivo basado en condición — **Alta**
- RF-03.1 Calcular la próxima fecha de mantenimiento por máquina según horas reales, intensidad de uso (carga, RPM), historial y health score, no solo por calendario.
- RF-03.2 Marcar los mantenimientos innecesarios (máquina sana y poco uso) y los atrasados (riesgo crítico).
- RF-03.3 Generar un calendario de mantenimiento priorizado.

### RF-04 Gestión de repuestos — **Media**
- RF-04.1 Mantener un catálogo de componentes y la relación componente ↔ modelo de máquina.
- RF-04.2 Llevar el inventario por ubicación o almacén.
- RF-04.3 Mostrar el ranking de los componentes más demandados.
- RF-04.4 Pronosticar la demanda por ubicación a partir de los mantenimientos previstos y las fallas predichas.
- RF-04.5 Detectar consumo irregular de repuestos (picos o recambios repetidos).
- RF-04.6 Recomendar stock mínimo y máximo por ubicación. Generar una alerta cuando falte un repuesto para un mantenimiento planificado, o cuando haya sobrestock.

### RF-05 Ubicación y estado de la flota — **Alta**
- RF-05.1 Mapa con todas las máquinas, coloreadas por estado: Operativa, Detenida, En mantenimiento o Requiere intervención.
- RF-05.2 Filtros por zona, tipo, estado y severidad.
- RF-05.3 Mostrar la ubicación de los técnicos y la distancia o tiempo estimado hasta cada máquina.

### RF-06 Asignación de técnicos — **Alta**
- RF-06.1 Mantener un registro de técnicos con especialidad, ubicación, disponibilidad, turno y carga actual.
- RF-06.2 Asignar automáticamente el mejor técnico a cada incidente con una función de puntaje que combine severidad, distancia/ETA, especialidad, disponibilidad y tiempo estimado de reparación.
- RF-06.3 Si hay varios incidentes simultáneos, priorizar la cola de forma global (los críticos primero).
- RF-06.4 Permitir que el responsable acepte, rechace o reasigne manualmente.
- RF-06.5 Escalar el incidente si no se acepta dentro de un SLA (timeout en Step Functions).

### RF-07 Análisis de combustible — **Media**
- RF-07.1 Calcular el consumo normalizado (L/h y L/ton transportada).
- RF-07.2 Comparar cada máquina con sus pares (mismo modelo y actividad) y con su propio historial.
- RF-07.3 Detectar aumentos progresivos de consumo.
- RF-07.4 Sugerir causas posibles (desgaste, sobrecarga, ralentí excesivo, fallo de componente) cruzando con otras variables. Puede apoyarse en un LLM.

### RF-08 Productividad de la flota — **Media**
- RF-08.1 Calcular la tasa de utilización por máquina: horas activas frente a horas disponibles.
- RF-08.2 Identificar máquinas subutilizadas (inactivas por periodos largos).
- RF-08.3 Identificar máquinas sobreexplotadas (por encima de su capacidad o en jornadas excesivas).
- RF-08.4 Usar una matriz de productividad frente a costo operativo para encontrar las de baja productividad y alto costo.
- RF-08.5 Recomendar redistribución de máquinas entre zonas.

### RF-09 Detección de comportamiento inusual — **Alta**
- RF-09.1 Comparar cada máquina con **su propio historial** (baseline individual).
- RF-09.2 Comparar cada máquina con **su cohorte** (mismo modelo, zona y tarea).
- RF-09.3 Generar alertas de "investigar", de menor severidad que una falla.

### RF-10 Notificaciones por rol — **Alta**
- RF-10.1 Definir reglas de enrutamiento por rol × severidad × tipo de evento.
- RF-10.2 Ofrecer varios canales: email, SMS, push o webhook (Slack/Teams) y dashboard.
- RF-10.3 Adaptar el contenido al rol: el técnico recibe detalle técnico, el gerente un resumen e impacto. El LLM puede generar ambos resúmenes.
- RF-10.4 Escalar automáticamente si nadie confirma la alerta (acknowledge).
- RF-10.5 Agrupar alertas repetidas para evitar spam (deduplicación y throttling).

### RF-11 Historial de incidentes — **Alta**
- RF-11.1 Registrar el ciclo de vida completo del incidente: detectado → asignado → en atención → resuelto → cerrado.
- RF-11.2 Guardar el tiempo detenido (downtime), las intervenciones, los componentes reemplazados, el técnico y el costo.
- RF-11.3 Detectar **reincidencias**: el mismo patrón se repite después de la intervención.
- RF-11.4 Mostrar una línea de tiempo por máquina y calcular KPIs: MTBF, MTTR y disponibilidad.

### RF-12 Incidentes correlacionados / multi-máquina — **Media**
- RF-12.1 Agrupar anomalías por zona y ventana temporal mediante clustering espacio-temporal.
- RF-12.2 Crear un "incidente padre" que agrupe los incidentes de esas máquinas.
- RF-12.3 Sugerir una causa común: terreno, clima, lote de combustible o componente/lote compartido. Puede enriquecerse con una API de clima y con un LLM.

### RF-13 Planificación con datos históricos — **Media**
- RF-13.1 Detectar patrones precursores de falla, es decir, secuencias de señales que preceden a fallas pasadas.
- RF-13.2 Reentrenar el modelo de forma periódica y automatizada (pipeline de ML con Step Functions).
- RF-13.3 Generar reportes de planificación: fallas esperadas por semana y repuestos o técnicos necesarios.

### RF-14 Asistente IA conversacional — **Media**
- RF-14.1 Un chat en lenguaje natural sobre la flota, por ejemplo "¿qué máquinas de la zona norte están en riesgo?" o "¿por qué falló la EX-023?".
- RF-14.2 Responder con datos reales mediante RAG o tool-calling sobre la base de datos.

### RF-15 Dashboard / Frontend — **Alta**
- RF-15.1 Vistas por rol: operador, técnico, mantenimiento, supervisor y gerencia.
- RF-15.2 Vista general de KPIs, mapa, cola de incidentes, detalle de máquina, repuestos, combustible y productividad.
- RF-15.3 Actualización casi en tiempo real (WebSocket o polling).

### RF-16 Comunicación y colaboración por incidente — **Alta**
- RF-16.1 Cada incidente abre su propio canal o hilo de conversación. Entran automáticamente el operador, el técnico asignado, el responsable de mantenimiento y el supervisor de la zona.
- RF-16.2 Mensajes en tiempo real con texto, fotos, audio y ubicación, también desde el celular en campo.
- RF-16.3 Mensajes rápidos predefinidos: "en camino", "llegué", "necesito repuesto X", "necesito apoyo", "máquina operativa".
- RF-16.4 Avisar a una persona concreta (@mención) y sumar participantes, por ejemplo un especialista o el almacén.
- RF-16.5 Cambiar el estado del incidente desde la conversación: aceptar, en atención, pausado por repuesto, resuelto.
- RF-16.6 Funcionar sin conexión, enviando los mensajes cuando vuelva la red (zonas mineras con mala cobertura).
- RF-16.7 Guardar la conversación en el historial del incidente (RF-11) como registro de auditoría.
- RF-16.8 Que la IA resuma la conversación al cerrar el incidente y extraiga causa, acciones y repuestos usados para completar el historial automáticamente.
- RF-16.9 Opcional: enviar y recibir mensajes por WhatsApp, Slack o Teams además de la app.

---

## 4. Requerimientos no funcionales

| ID | Categoría | Requerimiento | Prioridad |
|---|---|---|---|
| RNF-01 | Escalabilidad | Escalar de ~10 a miles de máquinas sin rediseño ni cambios de código. Ver detalle en 4.1. | Alta |
| RNF-02 | Serverless | Cero servidores siempre encendidos. Solo servicios de pago por uso (Lambda, Step Functions, DynamoDB on-demand, S3, API Gateway, Cloud Functions/Run, etc.). | Alta |
| RNF-03 | Costo | Costo proporcional al uso y cercano a $0 en reposo. Políticas de ciclo de vida en S3 (Standard → IA → Glacier). | Alta |
| RNF-04 | Disponibilidad | ≥ 99,9 %. Servicios multi-AZ por defecto. Réplica de datos críticos en una segunda región o nube. | Alta |
| RNF-05 | Persistencia / durabilidad | Telemetría cruda en data lake (S3, 11 nueves). Estado e incidentes en DynamoDB con PITR y backups. Réplica en la segunda nube. | Alta |
| RNF-06 | Latencia | Alerta crítica en ≤ 60 s desde la lectura. Dashboard con datos de ≤ 1 min de antigüedad. | Media |
| RNF-07 | Tolerancia a fallos | Reintentos con backoff, DLQ, idempotencia por `machine_id`+`timestamp`, sin pérdida de mensajes. | Alta |
| RNF-08 | Seguridad | IAM con mínimo privilegio, autenticación de usuarios (Cognito), RBAC por rol, cifrado en tránsito (TLS) y en reposo (KMS), secretos en Secrets Manager. | Alta |
| RNF-09 | Observabilidad | Logs estructurados, métricas, trazas distribuidas, dashboards y alarmas de todos los componentes y de ambas nubes. Ver detalle en 4.2. | Alta |
| RNF-10 | Mantenibilidad | Infraestructura como código (SAM, CDK, Terraform o Serverless Framework). Repositorio con README. | Media |
| RNF-11 | Portabilidad multinube | Componentes desacoplados por eventos/APIs. Ninguna funcionalidad crítica depende de una sola nube. | Media |
| RNF-12 | Usabilidad | Interfaz simple, mapa claro y alertas entendibles por personal no técnico (explicaciones generadas por IA). | Media |
| RNF-13 | Explicabilidad IA | Cada alerta de IA indica qué variables la causaron y con qué confianza. | Media |
| RNF-14 | Retención de datos | Telemetría cruda ≥ 1 año en almacenamiento frío. Incidentes de forma indefinida. | Baja |
| RNF-15 | Trazabilidad / auditoría | Toda acción, decisión automática y dato es rastreable de punta a punta: quién, qué, cuándo, por qué y a partir de qué dato. Ver detalle en 4.3. | Alta |
| RNF-16 | Mensajería | Entrega de mensajes del canal de incidente en ≤ 2 s, orden garantizado por incidente, cifrado en tránsito y en reposo, conversaciones retenidas junto con el incidente. | Alta |

### 4.1 Escalabilidad
- ESC-01 Ingesta horizontal: ≥ 1.000 msg/s en la configuración base y hasta ≥ 10.000 msg/s (≈ 10.000 máquinas a 1 msg/s) sin rediseño, escalando shards/particiones.
- ESC-02 Particionado por `machine_id` en streams y tablas para evitar hot partitions y mantener el orden por máquina.
- ESC-03 Todos los componentes de cómputo son stateless y escalan automáticamente (Lambda, Cloud Functions, Step Functions Express para alto volumen).
- ESC-04 Desacoplamiento por colas y eventos (Kinesis, SQS, EventBridge, Pub/Sub) para absorber picos sin perder datos (backpressure).
- ESC-05 Separación de caminos: tiempo real (hot path: alertas) y analítico (cold path: data lake por lotes), para que la analítica no afecte la latencia de alertas.
- ESC-06 Multi-tenant / multi-operación: una misma plataforma soporta varias operaciones, minas u obras aisladas por `operation_id`.
- ESC-07 Agregaciones precalculadas (ventanas 1 min / 1 h / 1 día) para que dashboards y consultas no escaneen telemetría cruda.
- ESC-08 Datos en formato columnar (Parquet) particionados por fecha, operación y tipo de máquina.
- ESC-09 Límites y cuotas documentados (concurrencia de Lambda, throughput de DynamoDB, shards) con alarmas antes de alcanzarlos.
- ESC-10 Pruebas de carga con el simulador a 100, 1.000 y 10.000 máquinas, registrando latencia, errores y costo en cada escenario.

### 4.2 Observabilidad
- OBS-01 Logs estructurados en JSON en todos los componentes, con campos comunes: `timestamp`, `service`, `level`, `operation_id`, `machine_id`, `incident_id`, `correlation_id`, `trace_id`.
- OBS-02 Trazas distribuidas de punta a punta (X-Ray / OpenTelemetry) desde la lectura de telemetría hasta la notificación al técnico, incluyendo las llamadas a la segunda nube y a los modelos de IA.
- OBS-03 Métricas técnicas: throughput de ingesta, latencia por etapa, errores, throttling, mensajes en DLQ, duración y fallos de ejecuciones de Step Functions, edad del iterador del stream.
- OBS-04 Métricas de negocio: incidentes abiertos por severidad, tiempo de detección, tiempo de asignación, MTTR, máquinas por estado, alertas por rol.
- OBS-05 Métricas de IA: latencia y costo por inferencia, tokens consumidos por el LLM, tasa de falsos positivos reportados, deriva (drift) de los datos y del modelo.
- OBS-06 Dashboards operativos de la plataforma (salud del sistema) separados de los dashboards de negocio.
- OBS-07 Alarmas con umbrales y notificación al equipo responsable: errores, DLQ con mensajes, latencia de alerta > 60 s, ejecuciones fallidas, presupuesto de costo superado.
- OBS-08 Observabilidad unificada multinube: logs y métricas de la segunda nube correlacionables con los de AWS por `correlation_id`.
- OBS-09 Health checks / heartbeat por máquina: detectar máquinas que dejaron de enviar telemetría (silencio) como evento propio.
- OBS-10 Retención de logs definida (por ejemplo, 30 días en caliente y archivado en S3) para controlar costos.

### 4.3 Trazabilidad
- TRZ-01 `correlation_id` único que se genera en la lectura de telemetría y se propaga por anomalía → incidente → ejecución de Step Functions → notificaciones → mensajes → cierre.
- TRZ-02 Registro de auditoría inmutable (append-only) de toda acción humana: quién creó, aceptó, reasignó, comentó, cambió de estado o cerró un incidente, con fecha, rol y origen.
- TRZ-03 Registro de toda decisión automática: por qué se generó una alerta (variables, valores, umbral o score del modelo, versión del modelo), por qué se eligió a un técnico (puntaje de cada candidato) y por qué se notificó a cada rol.
- TRZ-04 Linaje de datos: cada incidente enlaza a las lecturas de telemetría y anomalías que lo originaron.
- TRZ-05 Versionado de modelos de IA, prompts y reglas de negocio, de modo que cada resultado indique con qué versión se produjo.
- TRZ-06 Historial de cambios de estado de cada máquina, incidente, técnico e inventario (event sourcing o tabla de eventos).
- TRZ-07 Trazabilidad de repuestos: qué pieza (y lote, si aplica) se instaló en qué máquina, en qué incidente y por qué técnico.
- TRZ-08 Historial de ejecuciones de Step Functions consultable desde el detalle del incidente.
- TRZ-09 Consulta de la línea de tiempo completa de un incidente o máquina desde la interfaz y por API.

---

## 5. Requerimientos técnicos (alineados a la rúbrica)

### 5.1 Arquitectura de referencia (propuesta)

```
[Simulador IoT] ──► AWS IoT Core / Kinesis Data Streams
                          │
                          ├──► Kinesis Firehose ──► S3 (data lake, Parquet) ──► Athena / Glue
                          │                                   │
                          │                                   └──► Réplica ► GCP Cloud Storage / BigQuery
                          ▼
                    Lambda (procesamiento + features)
                          │
                          ├──► DynamoDB (estado actual, health score, incidentes, técnicos, repuestos)
                          │       (Global Tables / PITR)
                          ▼
                    Detección de anomalías (Lambda + modelo / SageMaker Serverless / Vertex AI)
                          │  severidad ≥ umbral
                          ▼
              EventBridge ──► Step Functions: "Gestión de Incidente"
                                 1. Enriquecer (historial, clima, cohorte)
                                 2. Diagnóstico IA (Bedrock / Gemini)
                                 3. Correlación multi-máquina
                                 4. Asignar técnico (scoring)
                                 5. Reservar repuesto / alertar falta de stock
                                 6. Notificar por rol (SNS / SES / Pinpoint)
                                 7. Esperar confirmación (callback + timeout → escalar)
                                 8. Cerrar y registrar historial

  Step Functions programadas (EventBridge Scheduler):
   - Plan preventivo diario
   - Pronóstico de repuestos
   - Reporte de productividad / combustible
   - Reentrenamiento del modelo (semanal)

[Frontend: S3 + CloudFront / Firebase Hosting] ◄── API Gateway (REST + WebSocket) ◄── Lambda
[Auth: Cognito]
```

### 5.2 Mapeo rúbrica → requerimiento técnico

| Criterio rúbrica | Pts | Requerimiento técnico |
|---|---|---|
| Problemas resueltos | 0-3 | Cubrir RF-01 a RF-13. Mínimo: 02, 05, 06, 09, 10 y 11, más todos los posibles. |
| Persistencia y alta disponibilidad | 0-2 | S3 (data lake) + DynamoDB con PITR/Global Tables + réplica cross-cloud a GCS/BigQuery o Azure Cosmos DB. |
| Step Functions | 0-2 | Al menos 2 workflows: **Incidente** (con callback/timeout, ramas `Choice`, `Parallel`, `Map`) y **Plan preventivo/reentrenamiento** (programado). |
| 2+ nubes | 0-3 | AWS (núcleo) + GCP (Vertex AI/Gemini o BigQuery analítica o Firebase) y/o Azure (Azure OpenAI, Cosmos DB). Cada nube con un rol **real**, no decorativo. |
| Arquitectura | 0-3 | Diagrama claro, orientado a eventos, desacoplado, con justificación de cada servicio. |
| 100% serverless | 0-3 | Sin EC2, sin RDS provisionado, sin contenedores siempre encendidos. Todo bajo demanda. |
| Uso de IA | 0-3 | ML de anomalías y predicción de fallas, más un LLM para diagnóstico, resúmenes por rol, correlación de causa común y chat. |

### 5.3 Stack técnico sugerido

| Capa | AWS | Segunda nube (opción) |
|---|---|---|
| Ingesta | IoT Core, Kinesis Data Streams, Firehose | GCP Pub/Sub (espejo) |
| Cómputo | Lambda | Cloud Functions / Cloud Run |
| Orquestación | Step Functions, EventBridge, EventBridge Scheduler | Workflows (opcional) |
| Datos operacionales | DynamoDB | Firestore / Cosmos DB (réplica) |
| Data lake / analítica | S3, Glue, Athena | BigQuery |
| IA / ML | SageMaker Serverless Inference, Bedrock (Claude) | Vertex AI, Gemini / Azure OpenAI |
| Notificaciones | SNS, SES, Pinpoint | Firebase Cloud Messaging |
| API | API Gateway (REST + WebSocket) | — |
| Frontend | S3 + CloudFront o Amplify | Firebase Hosting |
| Auth | Cognito | Firebase Auth |
| Mapas | Amazon Location Service | Google Maps API |
| IaC | SAM / CDK / Terraform | Terraform |
| Mensajería entre trabajadores | API Gateway WebSocket o AppSync (suscripciones), S3 para adjuntos | Firebase Realtime DB / Firestore + FCM |
| Observabilidad | CloudWatch Logs/Metrics/Dashboards/Alarms, X-Ray, ADOT (OpenTelemetry) | Cloud Logging, Cloud Monitoring, Cloud Trace |
| Auditoría | CloudTrail, tabla DynamoDB append-only de eventos | Cloud Audit Logs |

### 5.4 Modelo de datos (mínimo)

| Entidad | Atributos clave |
|---|---|
| `Machine` | machine_id, modelo, tipo, zona, ubicación, estado, horas_totales, health_score, último_mantenimiento, próximo_mantenimiento |
| `TelemetryReading` | machine_id, timestamp, temp, vibración, presión, combustible, carga, velocidad, rpm, lat, lon |
| `Anomaly` | anomaly_id, machine_id, timestamp, variables_afectadas, score, severidad, tipo (individual/cohorte/tendencia) |
| `Incident` | incident_id, parent_incident_id, machine_id(s), severidad, estado, técnico_asignado, diagnóstico_ia, t_detección, t_asignación, t_resolución, downtime, componentes_reemplazados, costo, reincidencia |
| `Technician` | tech_id, nombre, especialidades, ubicación, disponible, turno, carga_actual |
| `Component` | component_id, nombre, modelos_compatibles, costo, lead_time |
| `Inventory` | ubicación_id, component_id, stock, stock_min, stock_max |
| `MaintenanceRecord` | record_id, machine_id, tipo (preventivo/correctivo), fecha, técnico, componentes, horas_al_momento |
| `NotificationRule` | rol, severidad_min, tipo_evento, canales, plantilla |
| `User` | user_id, rol, zona, canales_contacto |
| `IncidentChannel` | channel_id, incident_id, participantes (user_id, rol, permiso), estado, resumen_ia |
| `Message` | message_id, incident_id, autor, rol, tipo (texto/foto/audio/ubicación/rápido/cambio_estado), contenido, adjuntos, timestamp, correlation_id |
| `AuditEvent` | event_id, entidad, entidad_id, acción, actor (usuario o sistema), rol, valores_antes/después, motivo, versión_modelo/regla, correlation_id, timestamp |

### 5.5 APIs mínimas

- `POST /telemetry`: ingesta (alternativa a IoT Core)
- `GET /machines`, `GET /machines/{id}` (con historial y health)
- `GET /incidents`, `GET /incidents/{id}`, `POST /incidents/{id}/ack`, `POST /incidents/{id}/resolve`
- `GET /technicians`, `POST /incidents/{id}/assign`
- `GET /inventory`, `GET /parts/forecast`
- `GET /analytics/fuel`, `GET /analytics/productivity`, `GET /analytics/kpis`
- `POST /assistant/chat`: asistente IA
- `GET /incidents/{id}/messages`, `POST /incidents/{id}/messages`: conversación del incidente
- `POST /incidents/{id}/participants`: invitar participantes
- `GET /incidents/{id}/timeline`, `GET /machines/{id}/timeline`: trazabilidad completa
- `GET /audit?entity=&id=`: registro de auditoría
- `WS /live`: actualizaciones en tiempo real
- `WS /incidents/{id}/chat`: mensajes en tiempo real del canal del incidente

### 5.6 Datos simulados (requisitos del simulador)
- Al menos 50–100 máquinas de 4–5 tipos (excavadora, camión minero, cargador, bulldozer, perforadora) en 3–5 zonas.
- Al menos 10 técnicos con distintas especialidades (motor, hidráulica, eléctrica, neumáticos).
- 20–30 componentes con inventario en 2–3 almacenes.
- Historial sintético de 3–6 meses con fallas etiquetadas para entrenar o validar el modelo.
- Escenarios inyectables:
  1. Degradación progresiva (temperatura y vibración suben durante días).
  2. Falla súbita.
  3. Consumo de combustible anómalo.
  4. Incidente grupal en una zona (por ejemplo, combustible contaminado).
  5. Máquina ociosa o sobreexplotada.

---

## 6. Requerimientos no técnicos

### 6.1 Negocio
- Propuesta de valor: pasar de mantenimiento reactivo a predictivo y de datos a decisiones.
- KPIs de éxito: disponibilidad de flota, MTBF, MTTR, % de mantenimientos evitados, rotación de inventario, costo de combustible por tonelada y utilización de flota.
- Estimación de costo de la plataforma: costo por máquina por mes a 100 y a 10.000 máquinas, para demostrar que escala de forma económica.
- Modelo de adopción: piloto en una operación y luego expansión progresiva.

### 6.2 Organizacionales
- Repositorio único con README, diagrama y pasos para desplegar.
- Definition of Done: desplegado en la nube, funcional de punta a punta y documentado.

### 6.3 Restricciones
- Datos simulados. No hay integración con hardware real.
- Tiempo limitado de hackathon. Priorizar profundidad en el flujo principal sobre cobertura superficial.
- Presupuesto de nube limitado (capas gratuitas o créditos). Evitar servicios con costo fijo (por ejemplo, endpoints de SageMaker en tiempo real o clusters de OpenSearch provisionados).
- La solución debe ser 100% serverless (lo exige la rúbrica).

### 6.4 Supuestos
- Las máquinas envían telemetría periódica (por ejemplo, cada 10–60 s) con conectividad intermitente tolerable.
- Existe un catálogo de modelos, componentes y técnicos (simulado).
- La ubicación GPS está disponible en cada lectura.

### 6.5 Riesgos y mitigación

| Riesgo | Mitigación |
|---|---|
| Modelo ML poco preciso con datos sintéticos | Combinar reglas y ML (híbrido) y mostrar la explicabilidad |
| Integración multinube compleja | Limitar la segunda nube a 1–2 roles claros (IA o réplica/analítica) |
| Costos inesperados | Billing alarms y servicios on-demand |
| Falta de tiempo | Priorizar los requerimientos marcados como **Alta** |

---

## 7. Trazabilidad problema → requerimiento

| # | Problema del contexto | Requerimientos |
|---|---|---|
| 1 | Fallas inesperadas / anomalías combinadas | RF-02, RF-09 |
| 2 | Mantenimiento preventivo según uso | RF-03 |
| 3 | Distribución de repuestos | RF-04 |
| 4 | Ubicación y estado de máquinas | RF-05 |
| 5 | Asignación de técnicos | RF-06 |
| 6 | Consumo de combustible | RF-07 |
| 7 | Productividad de flota | RF-08 |
| 8 | Comportamiento inusual (vs historial y vs pares) | RF-09 |
| 9 | Comunicación entre participantes / por rol | RF-10, RF-16 |
| 10 | Historial de incidentes y reincidencia | RF-11, RF-16.7, RNF-15 |
| 11 | Incidentes simultáneos con causa común | RF-12 |
| 12 | Planificación con históricos | RF-13 |
| 13 | Escalar a miles de máquinas, bajo costo, sin infra encendida | RNF-01 (4.1), RNF-02, RNF-03, RNF-09 (4.2) |
| 14 | "No solo un dashboard": datos → decisiones | RF-02.6, RF-06, RF-10, RF-14 |

