# ia_gemini

- **Dueño:** Persona A
- **Qué hace:** cliente LLM con **proveedor configurable** (`llm_client.py`: `LLM_PROVIDER=gemini|bedrock`) con salida JSON estructurada, prompts versionados (`prompts/*.md`) y **fallback determinista** por tarea. Tareas: `diagnose`, `summarize_by_role`, `common_cause`, `summarize_chat`, `executive_report` y el asistente `POST /v1/assistant/chat` con function calling sobre lecturas acotadas de DynamoDB (nunca SQL libre).
- **Consume:** invocación directa `{task, correlation_id, payload}` (SFN de B, `kpis_report`) y evento proxy de API Gateway (JWT Cognito).
- **Produce:** `{result, model, degraded, prompt_version, latency_ms}` (`contratos.md` §8) o la respuesta del OpenAPI del asistente (siempre 200; `degraded: true` si el LLM falla).
- **Cubre:** RF-02.6, RF-10.1, RF-10.3, RF-12.3, RF-14, RF-16.8, MH-MC-03.
- **Proveedores:**
  - `gemini` (default, activo en el Learner Lab): Gemini API por REST con urllib (`gemini_client.py`), modelo `GEMINI_MODEL` (default `gemini-flash-lite-latest`). `thinkingConfig` solo se envía a la familia 2.5 flash.
  - `bedrock`: Bedrock Converse con boto3 del runtime (`bedrock_client.py`), modelo `BEDROCK_MODEL_ID` (default `amazon.nova-micro-v1:0`). JSON estructurado con herramienta forzada `respond`; asistente con `toolConfig`. En el Learner Lab LabRole recibe AccessDenied → cae al fallback; listo para una cuenta real.
  - `LLM_TIMEOUT_S` (default 12) por llamada; el asistente corta con un deadline global de 20 s (API Gateway: 29 s). Cualquier falla → `LLMError` → fallback determinista.
  - Terraform: `-var llm_provider=bedrock` (también `gemini_model`, `bedrock_model_id`, `llm_timeout_s`).
- **`summarize_chat` (RF-16.8):** resume **solo** los mensajes del chat (`payload.messages`); ignora `resolution_notes` y cualquier otro dato del incidente, y descarta mensajes marcados `kind|type|source` = `resolution`/`resolution_notes`/`system`/`event`. Sin mensajes → fallback "No hubo conversación en el chat del incidente." sin llamar al LLM.
- **Despliegue:** zip + capa común, fuera de la VPC (`infra/ingest/ai.tf`). API key en Secrets Manager `arquifusion/<stage>/gemini/api-key` (texto plano o `{"api_key": "..."}`), con caché de 5 min. 
- **RBAC del asistente:** técnico, mantenimiento, supervisor, admin, gerencia. Técnico y supervisor solo ven su zona (`custom:zone`).
- **Cómo probar:** `pytest services/ai/ia_gemini/tests`
