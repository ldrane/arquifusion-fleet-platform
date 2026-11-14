# infra/query

- **Dueño:** Persona C
- **Contiene:** Lambdas `{p}-api-lectura` y `{p}-replicar`, layer `{p}-c-gcp` (google-auth), event source mappings de los Streams de `machines`, `incidents` (filtro `sk = META`, #26) y `technicians`, DLQ `{p}-replicar-dlq`, alarmas a `{p}-platform-alarms`, permisos de invocación para API Gateway y parámetros SSM.
- **State:** `s3://<bucket-tfstate>/arquifusion/query/terraform.tfstate`.
- **Requisitos:** `infra/base` aplicado (tablas con Streams, SNS `platform-alarms`, secreto `arquifusion/{stage}/gcp/service-account` con la llave cargada, runbook H0 §6).

```bash
scripts/build_query_layer.sh                          # build/layer-c-gcp.zip (google-auth, python3.12)
terraform -chdir=infra/query init -backend-config=../backend.hcl
terraform -chdir=infra/query apply -var stage=<stage> # -var alarms_enabled=false si aún no existe platform-alarms
```

Variables de entorno de las Lambdas (contratos.md §1.1): `TABLE_*` (nombre completo), `STAGE`, `CORS_ORIGIN`, `DEFAULT_OPERATION_ID`, `FIREBASE_SECRET_NAME`, `GCP_PROJECT_ID` (vacío = el de la llave), `REPLICA_HEARTBEAT_S` (replicar).
Ambas Lambdas van **fuera de la VPC** (salen a Firestore; la VPC no tiene NAT).

## Salidas (SSM)

| Parámetro | Valor | Lo usa |
|---|---|---|
| `/arquifusion/{stage}/query/api_lectura_invoke_arn` | invoke ARN de `api-lectura` | B: `uri` de las integraciones `AWS_PROXY` |
| `/arquifusion/{stage}/query/api_lectura_arn` | ARN de la función | B, si prefiere armar el `uri` |

## Contrato de integración con B (pedido a B, `infra/base`)

Rutas de `{p}-api` (stage `v1`, **sin** prefijo `/v1` en el recurso), authorizer Cognito (ID token), integración
`AWS_PROXY` (`httpMethod: POST`) al invoke ARN de SSM, y `OPTIONS` MOCK con los headers CORS de contratos.md §1.2:

| Método | Recurso de API Gateway |
|---|---|
| GET | `/me` |
| POST | `/auth/firebase-token` |
| GET | `/machines`, `/machines/{machine_id}`, `/machines/{machine_id}/telemetry`, `/machines/{machine_id}/timeline` |
| GET | `/incidents`, `/incidents/{incident_id}` |
| GET | `/technicians` |
| GET | `/inventory`, `/parts/ranking`, `/parts/forecast`, `/maintenance/plan` |
| GET | `/analytics/fuel`, `/analytics/productivity`, `/analytics/kpis`, `/reports/latest`, `/ml/model` |

- Los parámetros de ruta **deben** llamarse `{machine_id}` e `{incident_id}` (la Lambda enruta por `event.resource`).
  Si B usa `{id}` en `/incidents/{id}/ack` para api-comandos, el recurso hermano tiene que llamarse igual: API Gateway
  no permite dos nombres de variable en el mismo nivel. Acordado: `{incident_id}` y `{machine_id}` en todos.
- Los permisos `lambda:InvokeFunction` ya los crea este stack (`*/*/GET/*` y `*/*/POST/auth/firebase-token`); B no
  necesita leer este state.
- Después de agregar rutas: nuevo deployment del stage `v1`.
