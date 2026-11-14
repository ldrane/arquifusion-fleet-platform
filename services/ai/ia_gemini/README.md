# ia_gemini

- **Dueño:** Persona A
- **Qué hace:** Cliente de Vertex AI/Gemini: diagnose, summarize_by_role, common_cause, summarize_chat, assistant_chat. Fallback determinista.
- **Consume:** Invocación desde SFN `GestionIncidente` y `POST /v1/assistant/chat`
- **Produce:** Ver contrato interno en `contracts/fixtures/ia/`
- **Cubre:** RF-02.6, RF-12.3, RF-14, RF-16.8
- **Despliegue:** Fuera de la VPC (sale a GCP).
- **Cómo probar:** `pytest services/ai/ia_gemini/tests`
