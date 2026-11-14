# Scripts

| Script | Dueño | Qué hace |
|---|---|---|
| `seed.py` | C | Carga datos maestros idempotentes: máquinas, técnicos, catálogo, inventario, almacenes, reglas de notificación. `export` regenera `contracts/fixtures/seed/` (test: `python -m pytest scripts/tests -q`) |
| `smoke_golden_path.sh` | Todos | Prueba E2E del golden path. Se corre antes de cada merge a `main` desde H2 |
