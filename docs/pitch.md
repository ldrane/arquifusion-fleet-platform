# Pitch de 5 minutos (TAREA-19)

Guion cronometrado de la demo de ArquiFusion (Grupo 27 · RootAccess). Dos personas en escena:

- **P** · Presentador: habla, vende el problema y el cierre.
- **O** · Operador de consola: acciona la app y la terminal de AWS; narra lo que va saliendo.

> Regla de oro: **la pantalla nunca miente**. Todo lo que se muestra está corriendo en AWS real (o en GCP real) en ese momento. Si algo falla, se usa el plan B del bloque y se sigue: la caída también demuestra resiliencia.

## Checklist antes de subir al escenario

1. `STAGE=<stage> scripts/demo_preflight.sh` en **verde** (7/7). Los avisos `•` no bloquean.
2. `degradacion` de la **EX-023** encendida **15 min antes** (por si el jurado pide una segunda demo de "falla progresiva").
3. Simulador **apagado** hasta el bloque 3 (`POST /v1/sim/stop`, `GET /v1/sim/state`); se enciende en vivo.
4. Estado limpio entre ensayos: `python3 scripts/demo_reset.py --stage <stage>` (dry-run) y luego `--yes`.
5. Teléfono de un **miembro del jurado** ya suscrito al bot de Telegram (`scripts/telegram_setup.py`). Confirmar que llega un mensaje de prueba.
6. `docs/arquitectura.png` abierto en una pestaña; pestaña de Step Functions (`arquifusion-<stage>-gestion-incidente`) lista; CloudWatch logs filtrados.
7. **Video de respaldo** `docs/demo.mp4` (60 s del golden path) descargado local, por si cae el lab o el wifi.
8. Cronómetro visible para P (o cuenta regresiva de 5:00 en el reloj).

---

## Bloque 1 · 0:00–0:40 · El problema, en dinero

| | |
|---|---|
| **Habla** | P |
| **Pantalla** | Slide/título del proyecto (o la portada de la app con el tile "USD protegidos" en 0) |
| **Frase exacta** | «Un camión CAT-793F parado cuesta unos **USD 1.500 por hora**. En una mina, una falla descubierta tarde no es un problema técnico: es una cadena completa de actividades detenida. Hoy las fallas se descubren tarde. Nosotros las detectamos **antes** de que paren la operación, y lo convertimos en un número: **dólares protegidos**.» |
| **Plan B** | Si no hay proyector, se narra sin slide mirando al jurado. El dato del USD/hora sale de `docs/costos.md` §1 y de los supuestos de valor (`docs/requerimientos.md`). |

## Bloque 2 · 0:40–1:20 · El diagrama: una frase por nube

| | |
|---|---|
| **Habla** | P (señalando el diagrama); O deja `docs/arquitectura.png` en pantalla |
| **Pantalla** | `docs/arquitectura.png` (mismo que `arquitectura-arquifusion.drawio`) |
| **Frase exacta** | «**AWS decide**: recibe la telemetría, detecta la anomalía con ML y orquesta la respuesta con Step Functions. **GCP llega al campo y recuerda**: Firestore sincroniza aunque no haya señal, FCM despierta al técnico, Gemini diagnostica y BigQuery guarda una copia diaria del historial en **otra nube**. No son dos nubes decorativas: cada una hace un trabajo que la otra no hace.» |
| **Plan B** | Si preguntan «¿por qué no una tercera nube?»: «Una tercera nube solo suma credenciales y otro punto de falla en la demo; el valor está en que cada nube tenga un rol real. Lo profundizamos aquí» (decisión **D2** del blueprint). |

## Bloque 3 · 1:20–3:30 · En vivo (el corazón)

O opera; P conversa con el jurado. Pantalla: la consola web. El clímax es el **teléfono del jurado**.

| T | Acción (O) | Frase exacta | Plan B |
|---|---|---|---|
| 1:20 | Abrir la app; señalar el **badge LIVE** | «Mira el pulso: **LIVE · AWS us-east-1 + GCP**, última lectura hace 4 segundos, IA: Gemini OK, modelo v3. Esto no es un mock.» | Si el badge sale ámbar, decir que es la degradación controlada y seguir. |
| 1:35 | Encender el simulador y elegir **`falla_subita`** sobre **CM-004** (`POST /v1/sim/scenario`) | «Inyecto una **falla súbita en la CM-004**. Esto entra a AWS real: API Gateway → SQS → Lambda.» | Si la consola no responde, inyectar con `simulator/cli.py` local contra el mismo `POST /telemetry`. |
| 1:50 | Esperar 10–20 s; el **pin se pone rojo** | «Ahí está: el pin en rojo. Y en Step Functions puedes ver la ejecución de **GestionIncidente** corriendo en vivo.» | Mostrar la ejecución abierta en la consola de Step Functions. |
| 2:10 | Abrir el detalle del incidente | «El diagnóstico lo produce **Gemini** con los factores que más se salieron: **temperatura y vibración, +2,4σ** sobre el propio historial de la máquina.» | Si Gemini falla → **badge "Motor determinista"** (o "Bedrock"): «la plataforma no se cae; cambia de proveedor y te dice cuál respondió». |
| 2:30 | Ver el **ranking de técnicos** con desglose | «El ranking no es alfabético: pesa **distancia, especialidad y carga** de cada técnico. Arriba está el TEC-07.» | — |
| 2:45 | El teléfono del jurado vibra con la alerta **Telegram** | «Este es el teléfono del jurado: le acaba de llegar la alerta **crítica** con dos botones. **Toca "✅ Aceptar".**» | Si no llega Telegram → **push FCM** al móvil; si tampoco, O hace **Aceptar** en la consola mientras P explica: «el mismo `SendTaskSuccess` se dispara desde la consola». |
| 3:05 | El botón llama al webhook y la consola **cambia sola** a `in_progress` | «Fíjate: la consola cambió sola a **in_progress**, sin tocar el teclado. El botón llamó a un webhook de API Gateway que ejecutó `SendTaskSuccess` sobre la Step Functions. Eso es el humano **dentro** del flujo orquestado.» | Si Firestore tarda, refrescar; la verdad ya quedó en DynamoDB. |
| 3:15 | Escribir un mensaje en el **chat** del incidente | «El técnico, el operador y el supervisor están en el **mismo hilo**, sincronizado por Firestore; sin señal, el móvil encola y sincroniza al volver.» | — |
| 3:25 | **Resolver** el incidente | «Resolvemos. La IA resume el hilo y calcula el **valor protegido**: paro evitado ≈ **14 h · USD 12.600**.» | Si el resumen tarda, ya se ve el tile de **USD protegidos** actualizado. |

## Bloque 4 · 3:30–4:20 · Decisiones (no solo alarmas)

| | |
|---|---|
| **Habla** | P; O navega entre tres pantallas |
| **Pantalla** | Plan preventivo · Repuestos · Firmas pre-falla · Asistente |
| **Frase exacta** | «Además de reaccionar, la plataforma **decide**. Este es el **plan preventivo**: separa los mantenimientos innecesarios de los atrasados. Aquí, **qué repuestos faltan y dónde reubicarlos**. Estas son las **firmas pre-falla**: "la CAT-336 subió su vibración 1,5σ en el **78 %** de sus fallas, con **18 horas** de anticipación". Y le pregunto al asistente: **"¿qué 3 máquinas atiendo hoy y con quién?"** — me responde con el plan y los técnicos concretos.» |
| **Plan B** | Si el asistente falla, mostrar la respuesta del `AnalisisDiario` ya ejecutado (tabla `insights`) y explicar que el asistente usa la misma cadena resiliente de IA. Si no hay datos frescos de repuestos, abrir el último resultado del workflow. |

## Bloque 5 · 4:20–5:00 · Escala, costo y cierre

| | |
|---|---|
| **Habla** | P; O deja `docs/costos.md` (tabla N=10.000) y el tile de USD protegidos |
| **Pantalla** | `docs/costos.md` + tile "USD protegidos (30 d)" |
| **Frase exacta** | «Todo esto corre **sin un solo servidor encendido**: pago por uso. El mismo diseño atiende **10.000 máquinas** — los números están en `docs/costos.md` — y si no hay tráfico, el costo es **prácticamente cero**. Y si AWS desapareciera, el historial **vive en BigQuery, en otra nube**, y Gerencia lo ve en Looker Studio. *(cierre)* En este turno protegimos **USD 12.600** en paro evitado. Ese es el paso de datos a decisiones.» |
| **Plan B** | Si piden otra falla: la **`degradacion` de EX-023** ya está encendida (checklist). Si piden más detalle de costos, abrir la tabla N=1.000/10.000. |

---

## Plan B global · el lab o el wifi se caen

- **Reproducir `docs/demo.mp4`** (60 s del golden path, grabado por el equipo) y narrar los mismos bloques 3–5 sobre el video.
- Decirlo con honestidad: «el lab gratuito de AWS se renueva cada pocas horas; grabamos el golden path como respaldo para no depender de su ventana».
- Si solo cae GCP: la app sigue operando contra AWS (DynamoDB es la fuente de verdad) y el chat/push se ve como «pendiente» hasta que vuelva la red.

## Reparto y ensayo

- **Ensayado 3 veces con cronómetro** (gate de salida de la fase P3). Cada ensayo termina con `scripts/demo_preflight.sh` verde y `scripts/demo_reset.py --yes`.
- Roles fijos: P no toca el teclado; O no improvisa el guion.
- Preguntas frecuentes: multinube (bloque 2), costo (bloque 5), «¿es mock?» (pulso LIVE + SFN en vivo), «¿y si la IA cae?» (badge del proveedor, bloque 3).
