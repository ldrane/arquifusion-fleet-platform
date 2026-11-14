# infra/frontend

- **Dueño:** Persona C. **RF:** RF-15 (consola), RF-05, RF-11, RF-16.
- **Contiene:** bucket S3 privado `{p}-web-{account}`, CloudFront con OAC (HTTPS, fallback SPA 403/404 → `index.html`), SSM `/arquifusion/{stage}/frontend/url`.
- **State:** `s3://<bucket-tfstate>/arquifusion/frontend/terraform.tfstate`. Independiente del resto: se puede aplicar en cualquier momento.
- **Desplegar infra:** `terraform -chdir=infra/frontend init -backend-config=../backend.hcl && terraform -chdir=infra/frontend apply -var stage=<stage>`
- **Publicar el front:** `STAGE=<stage> scripts/deploy_frontend.sh` (build con `frontend/.env.local`, `s3 sync`, invalidación).
- CORS: `cors_origin` sigue en `*` por defecto; para restringir, pasar el `url` de este stack a `infra/base` e `infra/query`.
