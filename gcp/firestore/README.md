# Firestore

- **Dueño:** Persona C
- **Security Rules:** viven en [`infra/gcp/firestore.rules`](../../infra/gcp/firestore.rules) (archivo único). Terraform (`infra/gcp/firestore.tf`) las publica; no hay otra copia.
- Usan los claims `role`, `zone` y `technician_id` del custom token (`POST /v1/auth/firebase-token`).
- Colecciones: ver `contracts/contratos.md` §5.
- Probar con el emulador: `firebase emulators:start --only firestore` apuntando a `infra/gcp/firestore.rules`.
