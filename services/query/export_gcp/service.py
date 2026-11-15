"""Réplica DR multinube (TAREA-13): AnalisisDiario -> BigQuery (sandbox, sin facturación).

Si AWS pierde el lake, el historial vive en otra nube y otra región. Cada día se exportan tres tablas con *load
jobs* REST (el sandbox de BigQuery no permite streaming, pero sí carga por lotes):

- `daily_machine_stats`: el CSV que dejó la consulta compartida de Athena en S3, en NDJSON y con `run_date`.
- `incidents`: los incidentes con `closed_at` en las últimas 24 h, **solo los campos públicos** de
  `query_common.items.incident` (nunca `ack_token`/`resolve_token`).
- `kpis_daily`: los insights `kpis#7d` y `kpis#30d` `LATEST`.

La autenticación usa la service account de Secrets Manager (`google-auth` llega por la layer de C). Los errores
de BigQuery **no lanzan**: se devuelven como `{"error": ...}` para no bloquear el análisis diario (DR es best-effort).
"""

from __future__ import annotations

import csv
import io
import json
import time
import urllib.parse
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from boto3.dynamodb.conditions import Attr
from query_common import items

BIGQUERY_SCOPE = "https://www.googleapis.com/auth/bigquery"
UPLOAD_URL = "https://bigquery.googleapis.com/upload/bigquery/v2/projects/{project}/jobs?uploadType=multipart"
JOB_URL = "https://bigquery.googleapis.com/bigquery/v2/projects/{project}/jobs/{job}"
INCIDENT_WINDOW_H = 24
POLL_MAX_S = 40
TABLES = ("daily_machine_stats", "incidents", "kpis_daily")


# --------------------------------------------------------------------------- conversiones puras
def parse_csv(csv_text: str, run_date: str) -> list[dict]:
    """CSV de Athena -> filas dict en NDJSON-ready, con `run_date` (la partición diaria de BigQuery)."""
    reader = csv.DictReader(io.StringIO(csv_text))
    return [
        {**{k: _cast(v) for k, v in row.items() if k is not None}, "run_date": run_date}
        for row in reader
        if any(row.values())
    ]


def to_ndjson(rows: list[dict]) -> str:
    """Una fila JSON por línea (formato NEWLINE_DELIMITED_JSON de BigQuery). Termina en salto de línea."""
    return "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in rows)


def incident_rows(scan_items: list[dict], since_iso: str) -> list[dict]:
    """Incidentes META cerrados desde `since_iso`, proyectados a su forma pública (sin tokens)."""
    out = []
    for item in scan_items:
        if item.get("sk") != "META":
            continue
        closed_at = str(item.get("closed_at") or "")
        if closed_at < since_iso:
            continue
        out.append(items.incident(item))
    return out


def kpi_rows(kind: str, data: dict | None) -> list[dict]:
    """Insight `kpis#<period>` -> fila plana con `period` (tabla `kpis_daily`)."""
    if not data:
        return []
    return [{**items.plain(data), "period": kind.split("#", 1)[1] if "#" in kind else kind}]


def _cast(value: str) -> Any:
    """Los números del CSV viajan como texto; BigQuery `autodetect` los tipa, aquí se conservan crudos."""
    return value


# --------------------------------------------------------------------------- carga multipart
Transport = Callable[[str, str, bytes | None, str], tuple[int, dict]]


def multipart_body(config: dict, ndjson: str, boundary: str) -> bytes:
    """Cuerpo `multipart/related`: parte 1 = config JSON del load job, parte 2 = NDJSON."""
    parts = [
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n",
        json.dumps(config, separators=(",", ":")),
        f"\r\n--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n",
        ndjson,
        f"\r\n--{boundary}--\r\n",
    ]
    return "".join(parts).encode("utf-8")


def load_config(project: str, dataset: str, table: str) -> dict:
    """`configuration.load` con append, autodetect y permisos de esquema (TAREA-13)."""
    return {
        "configuration": {
            "load": {
                "destinationTable": {"projectId": project, "datasetId": dataset, "tableId": table},
                "sourceFormat": "NEWLINE_DELIMITED_JSON",
                "autodetect": True,
                "writeDisposition": "WRITE_APPEND",
                "createDisposition": "CREATE_IF_NEEDED",
                "schemaUpdateOptions": ["ALLOW_FIELD_ADDITION"],
            }
        }
    }


class BigQuery:
    """Cliente mínimo de BigQuery sobre un `transport` autenticado (inyectable para los tests)."""

    def __init__(
        self,
        project: str,
        dataset: str,
        transport: Transport,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        poll_s: float = 1.0,
    ):
        self.project = project
        self.dataset = dataset
        self._transport = transport
        self._sleep = sleep
        self._clock = clock
        self._poll_s = poll_s

    def load(self, table: str, rows: list[dict]) -> dict:
        """Sube `rows` y espera a que el job quede `DONE`. Devuelve `{"job_id", "rows"}` o `{"error"}`.

        A diferencia de `replicar`, un fallo de GCP no se propaga: DR es best-effort y no debe tumbar el análisis.
        """
        if not rows:
            return {"job_id": None, "rows": 0, "skipped": "sin filas"}
        boundary = f"bq-{uuid.uuid4().hex}"
        body = multipart_body(load_config(self.project, self.dataset, table), to_ndjson(rows), boundary)
        content_type = f"multipart/related; boundary={boundary}"
        status, resp = self._transport("POST", UPLOAD_URL.format(project=self.project), body, content_type)
        if status >= 300:
            return {"error": _error(status, resp)}
        job_id = (resp.get("jobReference") or {}).get("jobId")
        if not job_id:
            return {"error": f"BigQuery no devolvió jobId: {json.dumps(resp)[:200]}"}
        return {"job_id": job_id, "rows": len(rows), **self._wait(job_id)}

    def _wait(self, job_id: str) -> dict:
        deadline = self._clock() + POLL_MAX_S
        while True:
            status, resp = self._transport(
                "GET", JOB_URL.format(project=self.project, job=job_id), None, "application/json"
            )
            if status >= 300:
                return {"error": _error(status, resp)}
            state = ((resp.get("status") or {}).get("state") or "").upper()
            if state == "DONE":
                if resp.get("status", {}).get("errorResult"):
                    return {"error": str(resp["status"]["errorResult"])[:200]}
                return {"state": "DONE"}
            if self._clock() >= deadline:
                return {"state": state or "TIMEOUT", "note": f"sin DONE en {POLL_MAX_S} s"}
            self._sleep(self._poll_s)


def _error(status: int, resp: dict) -> str:
    message = (resp.get("error") or {}).get("message") or json.dumps(resp)[:200]
    return f"BigQuery {status}: {message}"


def authorized_transport(sa_info: dict) -> Transport:
    """Transport real: google-auth con scope BigQuery + urllib3 (viene en el runtime de Lambda)."""
    import urllib3
    from google.auth.transport.urllib3 import AuthorizedHttp
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_info(sa_info, scopes=[BIGQUERY_SCOPE])
    http = AuthorizedHttp(creds, http=urllib3.PoolManager(timeout=urllib3.Timeout(connect=3.0, read=15.0)))

    def transport(method: str, url: str, body: bytes | None, content_type: str) -> tuple[int, dict]:
        headers = {"Content-Type": content_type} if body is not None else {}
        resp = http.request(method, url, body=body, headers=headers)
        try:
            data = json.loads(resp.data or b"{}")
        except json.JSONDecodeError:
            data = {"raw": resp.data[:300].decode(errors="replace")}
        return resp.status, data

    return transport


# --------------------------------------------------------------------------- orquestación
def _s3_key(location: str) -> tuple[str, str]:
    """`s3://bucket/key` -> `(bucket, key)`."""
    parsed = urllib.parse.urlparse(location)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"OutputLocation inesperado de Athena: {location!r}")
    return parsed.netloc, parsed.path.lstrip("/")


def _parse(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def run(event: dict, *, athena, s3, incidents_table, insights_table, bigquery: BigQuery) -> dict:
    """Lee las fuentes y las replica a BigQuery. Devuelve `{"tables", "job_ids", "errors"}`."""
    run_at = _parse(event.get("run_at")) or datetime.now(UTC)
    since_iso = (run_at - timedelta(hours=INCIDENT_WINDOW_H)).strftime("%Y-%m-%dT%H:%M:%SZ")
    tables: dict[str, int] = {}
    job_ids: dict[str, str] = {}
    errors: dict[str, str] = {}

    for table, rows in _sources(event, athena, s3, incidents_table, insights_table, run_at, since_iso):
        result = bigquery.load(table, rows)
        if "error" in result:
            errors[table] = result["error"]
        tables[table] = result.get("rows", 0)
        if result.get("job_id"):
            job_ids[table] = result["job_id"]

    out = {"tables": tables, "job_ids": job_ids, "errors": errors}
    return out


def _sources(event, athena, s3, incidents_table, insights_table, run_at: datetime, since_iso: str):
    """Genera `(tabla, filas)` para cada fuente, tolerando una fuente vacía o ausente."""
    yield "daily_machine_stats", _lake_rows(event, athena, s3, run_at)
    scan = incidents_table.scan(FilterExpression=Attr("sk").eq("META") & Attr("closed_at").gte(since_iso))
    yield "incidents", incident_rows(scan.get("Items", []), since_iso)
    yield "kpis_daily", _kpi_rows(insights_table)


def _lake_rows(event, athena, s3, run_at: datetime) -> list[dict]:
    query_execution_id = event.get("query_execution_id")
    if not query_execution_id:
        return []
    execution = athena.get_query_execution(QueryExecutionId=query_execution_id)
    location = execution["QueryExecution"]["ResultConfiguration"]["OutputLocation"]
    bucket, key = _s3_key(location)
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return parse_csv(body.decode("utf-8", errors="replace"), run_at.strftime("%Y-%m-%d"))


def _kpi_rows(insights_table) -> list[dict]:
    rows = []
    for kind in ("kpis#7d", "kpis#30d"):
        item = insights_table.get_item(Key={"pk": kind, "sk": "LATEST"}).get("Item")
        rows.extend(kpi_rows(kind, (item or {}).get("data")))
    return rows
