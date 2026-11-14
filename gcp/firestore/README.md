# Firestore

- **Dueño:** Persona C
- **Security Rules:** viven en [`infra/gcp/firestore.rules`](../../infra/gcp/firestore.rules) (archivo único). Terraform (`infra/gcp/firestore.tf`) las publica; no hay otra copia.
- Usan los claims `role`, `zone` y `technician_id` del custom token (`POST /auth/firebase-token`, api-lectura).
- Colecciones: ver `contracts/contratos.md` §5.
- Probar con el emulador: `firebase emulators:start --only firestore` apuntando a `infra/gcp/firestore.rules`.
- `users/{uid}` (perfil push con `fcm_tokens[]`): lo escribe solo `api-lectura` con la service account; el usuario solo lee el suyo. `notify_bridge` (B) lo lee con Admin SDK (contratos.md §4-§5).
- Técnicos: se filtra por `location.zone`; si faltara, la regla cae al `zone` de primer nivel (#11). `replicar` siempre escribe ambos.
