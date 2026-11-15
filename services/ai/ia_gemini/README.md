# ia_gemini

- **Dueño:** Persona A
- **Qué hace:** cliente LLM con **cadena de proveedores configurable** (`llm_client.py`: `LLM_PROVIDER` = lista separada por comas, default `gemini,bedrock`) con salida JSON estructurada, prompts versionados (`prompts/*.md`) y **fallback determinista** por tarea. Tareas: `diagnose`, `summarize_by_role`, `common_cause`, `summarize_chat`, `executive_report` y el asistente `POST /v1/assistant/chat` con function calling sobre lecturas acotadas de DynamoDB (nunca SQL libre).
- **Consume:** invocación directa `{task, correlation_id, payload}` (SFN de B, `kpis_report`) y evento proxy de API Gateway (JWT Cognito).
- **Produce:** `{result, model, provider, endpoint, degraded, prompt_version, latency_ms}` (`contratos.md` §8) o la respuesta del OpenAPI del asistente (siempre 200; `degraded: true` si todos los proveedores fallan).
- **Cubre:** RF-02.6, RF-10.1, RF-10.3, RF-12.3, RF-14, RF-16.8, MH-MC-03.
- **Proveedores:**
  - `gemini` (default, activo en el Learner Lab): Gemini API por REST con urllib (`gemini_client.py`), modelo `GEMINI_MODEL` (default `gemini-flash-lite-latest`). `GEMINI_API_BASE=aistudio|vertex|auto` (default `auto`): en `auto` intenta AI Studio y, si la clave se rechaza con 400/401/403, reintenta una vez contra **Vertex AI express** (`GEMINI_VERTEX_MODEL`, default `gemini-2.5-flash-lite`); la base ganadora queda cacheada en el contenedor (`endpoint` en la salida). `thinkingConfig` solo se envía a la familia 2.5 flash.
  - `bedrock`: Bedrock Converse con boto3 del runtime (`bedrock_client.py`), modelo `BEDROCK_MODEL_ID` (default `amazon.nova-micro-v1:0`). JSON estructurado con herramienta forzada `respond`; asistente con `toolConfig`. En el Learner Lab LabRole recibe AccessDenied → cae al fallback; listo para una cuenta real.
  - **Cadena:** se prueban en orden; el primero que responde gana (`provider` indica cuál). Si todos fallan → motor determinista con `provider: "fallback"` y el `degraded_reason` del primer error. En el asistente el primer proveedor usa hasta 12 s y el siguiente el resto menos 2 s.
  - `LLM_TIMEOUT_S` (default 12) por llamada; el asistente corta con un deadline global de 20 s (API Gateway: 29 s). Cualquier falla → `LLMError` → siguiente proveedor o fallback determinista.
  - Terraform: `-var llm_provider="gemini,bedrock"` (también `gemini_model`, `gemini_api_base`, `gemini_vertex_model`, `bedrock_model_id`, `llm_timeout_s`).
  - Sonda manual: `python3 scripts/check_gemini.py` (prueba AI Studio y Vertex express; no imprime la clave).
- **`summarize_chat` (RF-16.8):** resume **solo** los mensajes del chat (`payload.messages`); ignora `resolution_notes` y cualquier otro dato del incidente, y descarta mensajes marcados `kind|type|source` = `resolution`/`resolution_notes`/`system`/`event`. Sin mensajes → fallback "No hubo conversación en el chat del incidente." sin llamar al LLM.
- **Despliegue:** zip + capa común, fuera de la VPC (`infra/ingest/ai.tf`). API key en Secrets Manager `arquifusion/<stage>/gemini/api-key` (texto plano o `{"api_key": "..."}`), con caché de 5 min. 
- **RBAC del asistente:** técnico, mantenimiento, supervisor, admin, gerencia. Técnico y supervisor solo ven su zona (`custom:zone`).
- **Cómo probar:** `pytest services/ai/ia_gemini/tests`
