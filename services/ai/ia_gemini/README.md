# ia_gemini

- **Dueño:** Persona A
- **Qué hace:** cliente de la Gemini API (Google AI Studio, `gemini-2.5-flash`, REST con urllib) con salida JSON estructurada, prompts versionados (`prompts/*.md`) y **fallback determinista** por tarea. Tareas: `diagnose`, `summarize_by_role`, `common_cause`, `summarize_chat`, `executive_report` y el asistente `POST /v1/assistant/chat` con function calling sobre lecturas acotadas de DynamoDB (nunca SQL libre).
- **Consume:** invocación directa `{task, correlation_id, payload}` (SFN de B, `kpis_report`) y evento proxy de API Gateway (JWT Cognito).
- **Produce:** `{result, model, degraded, prompt_version, latency_ms}` (`contratos.md` §8) o la respuesta del OpenAPI del asistente (siempre 200; `degraded: true` si Gemini falla).
- **Cubre:** RF-02.6, RF-10.1, RF-10.3, RF-12.3, RF-14, RF-16.8, MH-MC-03.
- **Despliegue:** zip + capa común, fuera de la VPC (`infra/ingest/ai.tf`). API key en Secrets Manager `arquifusion/<stage>/gemini/api-key` (texto plano o `{"api_key": "..."}`), con caché de 5 min. Timeout de Gemini 8 s.
- **RBAC del asistente:** técnico, mantenimiento, supervisor, admin, gerencia. Técnico y supervisor solo ven su zona (`custom:zone`).
- **Cómo probar:** `pytest services/ai/ia_gemini/tests`
