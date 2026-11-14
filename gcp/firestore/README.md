# Firestore

- **Dueño:** Persona C
- `firestore.rules`: Security Rules con claims `role` y `zone` del custom token (`POST /v1/auth/firebase-token`).
- Colecciones: ver `contracts/contratos.md` §5.
- Probar con el emulador: `firebase emulators:start --only firestore`.
