# Modelo de costos por uso (TAREA-19)

Cómo calcular, **sin precios de memoria**, cuánto cuesta operar ArquiFusion a distintas escalas. La tabla de precios unitarios (§4) se llena desde las páginas oficiales de AWS y GCP con la fecha de consulta; las cantidades de consumo (§3 y §5) son exactas y no dependen de tarifas.

> Supuesto de fondo: **todo es pago por uso**. No hay servidores ni clústeres encendidos; el único costo en reposo es almacenamiento y unos pocos recursos de configuración (§6).

## 1. Variables y constantes

| Símbolo | Significado | Valor base del ejemplo |
|---|---|---|
| `N` | máquinas en la flota | 100 / 1.000 / 10.000 |
| `r` | lecturas por minuto por máquina | 1 (≈ cada 6 s con ventanas de 5 s) |
| `b` | lecturas por lote = lecturas por `POST /telemetry` | 100 (request validator y `SendMessage` directo) |
| `SQS batch` | mensajes por invocación de `procesar` | 100 (`ReportBatchItemFailures`) |
| `d` | duración media de `procesar` por invocación | 1,0 s |
| `m` | memoria de `procesar` | 1 GB (1024 MB) |
| `w` | unidades de escritura DynamoDB por lectura | 1 (mínimo; agregados `machine-state`) |
| `B` | bytes por lectura (JSON) | 250 B (cifra configurable; el lake comprime a Parquet) |
| `min_mes` | minutos por mes | 43.200 (30 × 24 × 60) |
| `h_mes` | horas por mes | 720 |
| `fp` | factor de compresión Parquet (S3 vs. Firehose) | 0,10 (≈ 10×) |

**Costo/mes** = Σ (cantidad de consumo del servicio × precio unitario del servicio).

## 2. Qué consume cada componente

- **API Gateway (REST):** una solicitud por lote → `solicitudes = N·r·min_mes / b`. También cuenta la API de consulta (`/v1/*`), pero su volumen es despreciable frente a la ingesta.
- **SQS:** un mensaje por solicitud; `mismo número que solicitudes`. La DLQ solo recibe lo que falla 3 veces.
- **Lambda `procesar`:** una invocación por cada 100 mensajes → `invocaciones = N·r·min_mes / (b·SQS_batch)`. Se cobra por invocaciones y por **GB-s** (`invocaciones × d × m`).
- **DynamoDB on-demand:** se cobra por **WRU** al escribir y por almacenamiento. `WRU = N·r·min_mes × w` (una escritura por lectura como mínimo). Las lecturas de la API y el almacenamiento son menores y se estiman aparte.
- **DynamoDB Streams → `replicar` / `auditoria`:** solo se disparan con cambios de incidentes (bajo volumen). No dominan el costo; se listan como "por evento".
- **Firehose:** se cobra por **GB ingeridos** → `N·r·min_mes × B / 1e9`.
- **S3 (lake):** se cobra por **GB-mes almacenados**. `GB/día = GB Firehose/día × fp`; el lifecycle mueve lo viejo a clases frías.
- **Athena:** se cobra por **TB escaneados** en consultas; depende del **uso del tablero**, no del tamaño de la flota. Nominal: 30 consultas/día × 1 GB = 0,9 TB/mes.
- **CloudWatch:** logs JSON (Powertools) en GB ingeridos; retención 7 días.
- **Firestore:** se cobra por escrituras/lecturas/almacenamiento. Con **coalescing a 12/h por máquina** (no una escritura por lectura): `escrituras = N × 12 × h_mes`.
- **FCM, Firebase Hosting, Looker Studio, Telegram:** capas gratuitas suficientes para la demo (Hosting y Looker sin costo; FCM gratis).
- **Cognito:** se cobra por **MAU**. El número de usuarios demo es mínimo.
- **Secrets Manager / SSM:** unos pocos secretos y parámetros estándar (SSM estándar es gratis).

## 3. Tabla de consumo (unidades físicas) para N = 100 / 1.000 / 10.000

Con `r = 1`, `b = 100`, `SQS batch = 100`, `d = 1 s`, `m = 1 GB`, `w = 1`, `B = 250 B`.

| Concepto (por mes) | Fórmula | N = 100 | N = 1.000 | N = 10.000 |
|---|---|---|---|---|
| Lecturas ingeridas | `N·r·43200` | 4.320.000 | 43.200.000 | 432.000.000 |
| Solicitudes API Gateway | `N·r·43200/b` | 43.200 | 432.000 | 4.320.000 |
| Mensajes SQS | = solicitudes | 43.200 | 432.000 | 4.320.000 |
| Invocaciones Lambda `procesar` | `N·r·43200/(b·100)` | 432 | 4.320 | 43.200 |
| GB-s Lambda `procesar` | `invocaciones × d × m` | 432 | 4.320 | 43.200 |
| WRU DynamoDB | `N·r·43200 × w` | 4.320.000 | 43.200.000 | 432.000.000 |
| GB Firehose ingeridos | `N·r·43200 × 250 / 1e9` | 1,08 | 10,8 | 108 |
| GB nuevos en S3/día | `Firehose/día × fp` | 0,0036 | 0,036 | 0,36 |
| TB Athena escaneados | uso (30 cons./día × 1 GB) | 0,9 | 0,9 | 0,9 |
| Escrituras Firestore | `N × 12 × 720` | 864.000 | 8.640.000 | 86.400.000 |

> Todos los valores escalan linealmente con `N` excepto Athena (depende del uso) y los recursos de configuración. Cambiar `r` multiplica las filas de ingesta por `r`.

## 4. Precios unitarios **(llenar desde las páginas oficiales; no inventar)**

Rellenar antes de la sustentación y anotar la fecha de consulta. Fuentes sugeridas: página de *pricing* de cada servicio (AWS) y *pricing* de cada producto (Google Cloud).

| Servicio | Unidad de cobro | Precio (USD) | Fuente (URL) | Fecha de consulta |
|---|---|---|---|---|
| API Gateway REST | por millón de solicitudes | | https://aws.amazon.com/api-gateway/pricing/ | |
| SQS | por millón de solicitudes | | https://aws.amazon.com/sqs/pricing/ | |
| Lambda | por millón de invocaciones | | https://aws.amazon.com/lambda/pricing/ | |
| Lambda | por GB-s | | https://aws.amazon.com/lambda/pricing/ | |
| DynamoDB on-demand | por millón de WRU | | https://aws.amazon.com/dynamodb/pricing/on-demand/ | |
| DynamoDB | por GB-mes | | https://aws.amazon.com/dynamodb/pricing/on-demand/ | |
| Firehose | por GB ingerido | | https://aws.amazon.com/kinesis/data-firehose/pricing/ | |
| S3 | por GB-mes (Standard) | | https://aws.amazon.com/s3/pricing/ | |
| Athena | por TB escaneado | | https://aws.amazon.com/athena/pricing/ | |
| CloudWatch Logs | por GB ingerido | | https://aws.amazon.com/cloudwatch/pricing/ | |
| Firestore | por millón de escrituras | | https://cloud.google.com/firestore/pricing | |
| Firestore | por GB-mes | | https://cloud.google.com/firestore/pricing | |
| Cognito | por MAU | | https://aws.amazon.com/cognito/pricing/ | |
| Secrets Manager | por secreto/mes | | https://aws.amazon.com/secrets-manager/pricing/ | |
| BigQuery (sandbox) | carga/consulta | gratis en sandbox | https://cloud.google.com/bigquery/pricing | |
| Firebase Hosting / FCM / Looker | — | gratis (capas free) | https://firebase.google.com/pricing · https://lookerstudio.google.com | |

## 5. Costo/mes (USD) — completar con los precios de §4

Cada celda es `cantidad × precio unitario`; no se sustituyen tarifas aquí.

| Servicio | Expresión (USD/mes) | N = 100 | N = 1.000 | N = 10.000 |
|---|---|---|---|---|
| API Gateway | solicitudes × PU | 43.200 × PU_api | 432.000 × PU_api | 4.320.000 × PU_api |
| SQS | mensajes × PU | 43.200 × PU_sqs | 432.000 × PU_sqs | 4.320.000 × PU_sqs |
| Lambda invocaciones | invoc. × PU | 432 × PU_inv | 4.320 × PU_inv | 43.200 × PU_inv |
| Lambda GB-s | GB-s × PU | 432 × PU_gbs | 4.320 × PU_gbs | 43.200 × PU_gbs |
| DynamoDB WRU | WRU × PU | 4.320.000 × PU_wru | 43.200.000 × PU_wru | 432.000.000 × PU_wru |
| Firehose | GB × PU | 1,08 × PU_fh | 10,8 × PU_fh | 108 × PU_fh |
| S3 | GB-mes × PU | (0,0036·días) × PU_s3 | (0,036·días) × PU_s3 | (0,36·días) × PU_s3 |
| Athena | TB × PU | 0,9 × PU_at | 0,9 × PU_at | 0,9 × PU_at |
| Firestore escrituras | escrituras × PU | 864.000 × PU_fs_w | 8.640.000 × PU_fs_w | 86.400.000 × PU_fs_w |
| **Total estimado** | Σ | **(suma)** | **(suma)** | **(suma)** |

> Al llenar §4, el total sale de multiplicar cada fila. La conclusión de ingeniería: **el costo crece lineal con la flota** y cada componente tiene una capa gratuita amplia, por lo que a escala pequeña (N=100) el total queda en el orden de decenas de USD/mes y a N=10.000 sigue en cientos, no en miles.

## 6. «Nada encendido»: costo ≈ 0 sin tráfico

Cuando la flota no envía lecturas y nadie usa la app, **casi todo el costo desaparece**, porque nada cómputa:

- **API Gateway, SQS, Lambda, DynamoDB (accesos), Firehose, Athena y Firestore (escrituras):** cero llamadas → cero costo.
- **Step Functions:** se cobra solo por transición de estado; sin ejecuciones, no hay costo.
- **Quedan solo los costos en reposo** (centavos): almacenamiento S3/DynamoDB/Firestore con los datos históricos, unos pocos **secretos** en Secrets Manager y los parámetros estándar de SSM (gratis). Con el lifecycle a clases frías, el almacenamiento del lake es marginal.
- **GCP:** BigQuery en **sandbox** (sin facturación) y Firebase Hosting / FCM dentro de la capa gratuita.

Por eso el mensaje del pitch es literal: **«pago por uso; si no hay tráfico, no hay costo»**. La plataforma no depende de infraestructura permanentemente encendida (contexto del cliente: «evitando depender de infraestructura permanentemente encendida»).

## 7. Notas de fidelidad del modelo

- Los valores de §3 son exactos para los supuestos dados; si `r` o `B` cambian, se recalculan con las fórmulas.
- El **coalescing de Firestore a 12/h** ya está en el diseño (`replicar` no escribe una vez por lectura): sin él, las escrituras serían ~360× mayores.
- DynamoDB Streams (invocaciones de `replicar` y `auditoria`) se disparan **por evento de incidente**, no por lectura; su costo es marginal y se puede estimar como `incidentes/mes × PU_inv`.
- El número de **USD protegidos** (bloque 5 del pitch) es otra cosa: sale de `baseline_h(severidad) × cost_usd_h(modelo)` en `services/incidents/incidente/service.py`, no de este modelo de infraestructura.
