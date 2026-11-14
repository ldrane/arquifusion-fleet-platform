# arquifusion_shared

- **Dueño:** Persona B. **Cualquier cambio requiere review de las 3 personas.**
- **Qué hace:** librería común de todas las Lambdas: envoltorio de respuesta, errores del contrato, `correlation_id`, observabilidad (Powertools) y RBAC.
- **Cubre:** `contracts/contratos.md` §1, RNF-09, TRZ.
- **Uso:** se empaqueta como Lambda Layer (`infra/base`). En local: `pip install -e services/shared`.
- **Cómo probar:** `pytest services/shared/tests`
