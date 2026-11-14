# arquifusion_shared

- **Dueño:** Persona B. **Cualquier cambio requiere review de las 3 personas.**
- **Qué hace:** librería común de todas las Lambdas: envoltorio de respuesta con CORS (`CORS_ORIGIN`, §1.2) y `Decimal` → número (#25), errores del contrato, `correlation_id` (`from_any` para API/EventBridge/SFN, #27), `config.table("incidents")` → `TABLE_INCIDENTS` (§1.1), observabilidad (Powertools) y RBAC (`role` por precedencia, `zone`, `technician_id`, `actor`, `require(..., zone=)`).
- **Cubre:** `contracts/contratos.md` §1, RNF-09, TRZ.
- **Uso:** se empaqueta como Lambda Layer (`infra/base`). En local: `pip install -e services/shared`.
- **Cómo probar:** `pytest services/shared/tests`
