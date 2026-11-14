"""Lectura de resultados de Athena con tipos (la consulta la ejecuta Step Functions con `.sync`)."""

from datetime import date, datetime

_INT = {"tinyint", "smallint", "integer", "int", "bigint"}
_FLOAT = {"double", "float", "real", "decimal"}


def _cast(value: str | None, athena_type: str):
    if value is None or value == "":
        return None
    if athena_type in _INT:
        return int(value)
    if athena_type in _FLOAT:
        return float(value)
    if athena_type == "boolean":
        return value.lower() == "true"
    if athena_type == "date":
        return date.fromisoformat(value)
    if athena_type.startswith("timestamp"):
        return datetime.fromisoformat(value)
    return value


def fetch_rows(athena_client, query_execution_id: str) -> list[dict]:
    """Devuelve las filas de una consulta ya terminada como dicts tipados (omite la fila de encabezados)."""
    rows: list[dict] = []
    columns: list[tuple[str, str]] = []
    paginator = athena_client.get_paginator("get_query_results")
    for page_no, page in enumerate(paginator.paginate(QueryExecutionId=query_execution_id)):
        result = page["ResultSet"]
        if not columns:
            columns = [(c["Name"], c["Type"].lower()) for c in result["ResultSetMetadata"]["ColumnInfo"]]
        data = result["Rows"][1:] if page_no == 0 else result["Rows"]
        for row in data:
            values = [cell.get("VarCharValue") for cell in row["Data"]]
            rows.append({name: _cast(v, t) for (name, t), v in zip(columns, values, strict=True)})
    return rows
