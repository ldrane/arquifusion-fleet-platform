"""Escritura de la tabla `insights` (contratos.md §9) con el formato de `arquifusion_ml.insights`."""

from arquifusion_ml.insights import items

from analytics_common.dynamo import to_dynamo


def write_insight(table, kind: str, data, run_at_iso: str, correlation_id: str) -> None:
    """Escribe el histórico del día y `LATEST`. `data` debe tener la forma exacta del endpoint del OpenAPI."""
    day = run_at_iso[:10]
    with table.batch_writer() as batch:
        for item in items(kind, day, data, run_at_iso, correlation_id):
            batch.put_item(Item=to_dynamo(item))
