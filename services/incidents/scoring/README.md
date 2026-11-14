# scoring

- **Dueño:** Persona B
- **Qué hace:** Lambda `scoring-tecnicos`: puntaje ponderado de técnicos candidatos.
- **Consume:** Invocación desde SFN (ver `contracts/fixtures/internal/scoring_*.json`)
- **Produce:** Técnico seleccionado + candidatos con puntaje
- **Cubre:** RF-06.2, RF-06.3, TRZ-03
- **Despliegue:** Fuera de la VPC.
- **Cómo probar:** `pytest services/incidents/scoring/tests`
