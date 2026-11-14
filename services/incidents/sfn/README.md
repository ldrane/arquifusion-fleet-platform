# Step Function `GestionIncidente` (Standard)

- **Dueño:** Persona B
- **Disparo:** regla EventBridge `AnomalyDetected` / `MachineSilent` en el bus `fleet-events`.
- **Flujo:** CrearIncidente (condicional) → Parallel (ia-gemini · correlacion-zona · stock) → Choice severidad → scoring → Map notificar → canal Firestore → EsperarAceptacion (`ack_token`, timeout + escalamiento ×2) → EsperarResolucion (`resolve_token`) → cierre (resumen IA, MTTR, inventario).
- **Emite:** `IncidentStateChanged` en cada transición.
- **Cubre:** RF-06, RF-10, RF-11, RF-12, MH-SFN-01.
