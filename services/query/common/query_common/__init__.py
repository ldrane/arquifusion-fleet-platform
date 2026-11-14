"""Código común de los servicios de la Persona C (api_lectura y replicar).

- `items`: de ítems DynamoDB a los shapes del OpenAPI / Firestore (contratos.md §5, §9; dynamodb.md).
- `gcp`: service account de Secrets Manager, custom token de Firebase y cliente REST de Firestore (sin firebase-admin).

Se empaqueta en el zip de cada Lambda (infra/query) junto a `arquifusion_shared` (B).
"""
