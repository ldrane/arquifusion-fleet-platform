# Presupuesto de concurrencia de Lambda (AWS Academy)

AWS Academy Learner Lab limita la cuenta a **10 Lambdas ejecutándose en paralelo**. Superarlo puede bloquear la cuenta.
Hay 20 Lambdas, así que no existe un tope duro global solo con concurrencia reservada (cada una necesita ≥ 1).
La estrategia es acotar cada fuente que escala sola, reintentar el throttling y alarmar antes del límite.

## Topes (concurrencia reservada, `var.reserved_concurrency` en cada stack)

| Lambda | Tope | Disparador | Si llega al tope |
|---|---|---|---|
| procesar | 2 | SQS (`maximum_concurrency` = 2, igual a la reservada) | SQS no invoca de más: sin throttles ni DLQ |
| replicar | 2 | 3 streams DynamoDB (1 shard c/u) | el stream reintenta; Firestore se atrasa segundos |
| api-lectura | 2 | API Gateway (front) | 429 puntual; el front reintenta en el siguiente refresco |
| api-comandos | 1 | API Gateway (acciones) | 429 puntual |
| ia-gemini | 2 | SFN + `/assistant/chat` | SFN reintenta; el asistente responde 429 puntual |
| incidente, scoring, correlacion, notificar | 1 c/u | SFN GestionIncidente | SFN reintenta (8 intentos, backoff hasta 20 s) |
| notify-push | 1 | Pub/Sub push → API Gateway | Pub/Sub reintenta |
| notify-telegram | 1 | EventBridge (solo incidentes critical) | Lambda reintenta el evento asíncrono |
| auditoria | 1 | EventBridge (asíncrono) | Lambda reintenta el evento asíncrono |
| heartbeat | 1 | Scheduler cada 1 min (~1 s de ejecución) | — |
| analytics-* (5) | 1 c/u | SFN AnalisisDiario, 05:00 Lima | SFN reintenta |
| retrain, retrain-promote | 1 c/u | SFN Reentrenamiento, domingo 04:00 Lima | SFN reintenta |

Las tres state machines tienen un retrier dedicado para `Lambda.TooManyRequestsException`
(`IntervalSeconds 2, MaxAttempts 8, BackoffRate 2, MaxDelaySeconds 20, JitterStrategy FULL`), así un tope nunca
rompe un flujo: solo lo demora.

## Carga típica

- **Flujo de la demo** (simulador + 1–3 usuarios + incidentes): pico medido de **5** con el smoke test.
- Mientras corre la demo, las Lambdas siempre activas (procesar, replicar, api-lectura, api-comandos, heartbeat) suman ≤ 8, pero se superponen poco: duran 0.1–2 s cada una.
- Batch (analytics, retrain): madrugada, fuera de la ventana de demo.
- `ReclamarMaquina` (SFN) impide más de un incidente abierto por máquina: el peor caso de tormenta es 1 por máquina, y los topes de arriba la serializan.

## Ritmo por defecto (bajo) y modo demo rápido

| Pieza | Default | Demo rápida (a mano, vigilando la alarma) |
|---|---|---|
| Simulador | `--rate 1 --speedup 60` | `--rate 2 --speedup 240` |
| Front REST (MachineDetail, Inventory, Efficiency, PredictiveHealth) | 15–30 s | — |
| Front tiempo real | Firestore `onSnapshot` (no usa Lambda) | — |

## Alarma

`arquifusion-<stage>-lambda-concurrency-high` (infra/base/concurrency.tf): `ConcurrentExecutions` máximo ≥ 8 en 1 min
→ SNS `platform-alarms`. Si salta: detener el simulador o bajar `--rate`.

Ver en vivo:
```
aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name ConcurrentExecutions \
  --start-time $(date -u -d '-30 min' +%FT%TZ) --end-time $(date -u +%FT%TZ) --period 60 --statistics Maximum
```
