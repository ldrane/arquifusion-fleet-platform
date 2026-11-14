# Pruebas de humo — AWS Academy Learner Lab

Verificamos manualmente qué permite el lab antes de escribir la infraestructura real en Terraform.
Fecha: 2026-11-14 · Cuenta: integración (stage=dev) · Región: us-east-1 · Rol: LabRole

| # | Prueba | Resultado |
|---|---|---|
| 1 | DynamoDB con PITR y Streams | ✅ |
| 2 | Lambda con LabRole | ✅ |
| 3 | SNS con suscripción por correo | ✅ |
| 4 | EventBridge: regla → Lambda | ✅ (en bus default) |
| 5 | Step Functions con `PutItem` directo a DynamoDB | ✅ |
| 6 | Step Functions con callback `waitForTaskToken` | ✅ |
| 7 | EventBridge: regla → Step Functions | ✅ (en bus default) |

## Notas

- En la consola del lab, un bus custom muestra "Subscribers" en vez de la pestaña Rules. Las pruebas 4 y 7 se hicieron en el bus `default`.
- Pendiente: confirmar que una regla funciona en el bus custom `fleet-events` antes de depender de él en Terraform.
- Las reglas, Lambdas y state machines de prueba (`smoke-*`) son desechables. La infraestructura real vive en `infra/`.
- Las credenciales del lab caducan en ~4 h y el Reset borra todo. Por eso todo lo real va en Terraform.