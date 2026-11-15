"""export_gcp (TAREA-13): multipart, CSV -> NDJSON, proyección sin tokens y tolerancia a fallos de GCP."""

import json

import service

CSV = "operation_id,machine_id,readings,avg_load_pct\nOP-01,EX-023,96,71.5\n"


class FakeAthena:
    def get_query_execution(self, QueryExecutionId):
        return {"QueryExecution": {"ResultConfiguration": {"OutputLocation": "s3://lake-queries/out/q1.csv"}}}


class FakeS3:
    def __init__(self, text=CSV):
        self.text = text
        self.calls = []

    def get_object(self, Bucket, Key):
        self.calls.append((Bucket, Key))
        return {"Body": type("B", (), {"read": lambda _self: self.text.encode()})()}


class FakeTable:
    def __init__(self, items=None):
        self.items = items or []
        self.scan_kwargs = None

    def scan(self, **kwargs):
        self.scan_kwargs = kwargs
        return {"Items": self.items}

    def get_item(self, Key):
        if Key["sk"] != "LATEST":
            return {}
        return {"Item": next((i for i in self.items if i.get("pk") == Key["pk"]), None)}


class RecordingTransport:
    """Registra las llamadas y responde POST (jobId) + GET (DONE)."""

    def __init__(self, post_status=200, done=True):
        self.calls = []
        self.post_status = post_status
        self.done = done

    def __call__(self, method, url, body, content_type):
        self.calls.append({"method": method, "url": url, "body": body, "content_type": content_type})
        if method == "POST":
            if self.post_status >= 300:
                return self.post_status, {"error": {"message": "quota"}}
            return 200, {"jobReference": {"jobId": "job-1"}}
        return 200, {"status": {"state": "DONE" if self.done else "RUNNING"}}


def test_multipart_body_tiene_dos_partes_y_config():
    config = service.load_config("p1", "ds", "incidents")
    body = service.multipart_body(config, '{"a":1}\n', "BND")
    text = body.decode()
    assert text.startswith("--BND\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n")
    assert json.loads(text.split("\r\n\r\n", 1)[1].split("\r\n--BND\r\n")[0]) == config
    assert 'Content-Type: application/octet-stream\r\n\r\n{"a":1}\n\r\n--BND--\r\n' in text
    load = config["configuration"]["load"]
    assert load["sourceFormat"] == "NEWLINE_DELIMITED_JSON" and load["autodetect"] is True
    assert load["destinationTable"] == {"projectId": "p1", "datasetId": "ds", "tableId": "incidents"}


def test_csv_a_ndjson_con_run_date():
    rows = service.parse_csv(CSV, "2026-11-14")
    assert rows == [{
        "operation_id": "OP-01", "machine_id": "EX-023", "readings": "96",
        "avg_load_pct": "71.5", "run_date": "2026-11-14",
    }]
    assert service.to_ndjson(rows) == json.dumps(rows[0]) + "\n"


def test_incidentes_proyectan_sin_tokens_ni_claves_internas():
    items = [
        {"pk": "INC#A", "sk": "META", "incident_id": "A", "machine_id": "EX-023", "status": "closed",
         "closed_at": "2026-11-14T10:00:00Z", "ack_token": "x", "resolve_token": "x", "execution_arn": "arn:x"},
        {"pk": "INC#B", "sk": "META", "incident_id": "B", "closed_at": "2026-11-01T00:00:00Z"},
        {"pk": "INC#C", "sk": "EVT#1", "incident_id": "C", "closed_at": "2026-11-14T10:00:00Z"},
    ]
    rows = service.incident_rows(items, "2026-11-14T00:00:00Z")
    assert [r["incident_id"] for r in rows] == ["A"]
    assert "ack_token" not in rows[0] and "resolve_token" not in rows[0] and "pk" not in rows[0]


def test_kpi_rows_agrega_periodo():
    assert service.kpi_rows("kpis#30d", {"availability_pct": 91.0}) == [{"availability_pct": 91.0, "period": "30d"}]
    assert service.kpi_rows("kpis#7d", None) == []


def test_bigquery_load_exitoso_envia_multipart_y_espera_done():
    transport = RecordingTransport()
    bq = service.BigQuery("p1", "ds", transport, sleep=lambda _s: None)
    result = bq.load("kpis_daily", [{"period": "7d"}])
    assert result == {"job_id": "job-1", "rows": 1, "state": "DONE"}
    assert transport.calls[0]["method"] == "POST"
    assert transport.calls[0]["content_type"].startswith("multipart/related; boundary=bq-")
    assert transport.calls[0]["url"].endswith("/upload/bigquery/v2/projects/p1/jobs?uploadType=multipart")
    assert transport.calls[1]["method"] == "GET" and transport.calls[1]["url"].endswith("/jobs/job-1")


def test_bigquery_error_se_devuelve_sin_lanzar():
    bq = service.BigQuery("p1", "ds", RecordingTransport(post_status=403), sleep=lambda _s: None)
    assert "BigQuery 403" in bq.load("incidents", [{"a": 1}])["error"]


def test_bigquery_timeout_no_lanza():
    ticks = iter([0, 100])  # deadline = 0 + 40; el segundo tic ya lo supera
    bq = service.BigQuery("p1", "ds", RecordingTransport(done=False), sleep=lambda _s: None, poll_s=0,
                          clock=lambda: next(ticks, 100))
    assert bq.load("incidents", [{"a": 1}]) == {
        "job_id": "job-1", "rows": 1, "state": "RUNNING", "note": "sin DONE en 40 s"
    }


def test_run_ensambla_las_tres_tablas():
    incidents = FakeTable([{"pk": "INC#A", "sk": "META", "incident_id": "A", "closed_at": "2026-11-14T10:00:00Z"}])
    insights = FakeTable([{"pk": "kpis#7d", "sk": "LATEST", "data": {"open_incidents": 2}}])
    transport = RecordingTransport()
    event = {"query_execution_id": "q1", "run_at": "2026-11-14T12:00:00Z", "correlation_id": "c1"}
    result = service.run(event, athena=FakeAthena(), s3=FakeS3(), incidents_table=incidents, insights_table=insights,
                         bigquery=service.BigQuery("p1", "ds", transport, sleep=lambda _s: None))
    assert result["tables"] == {"daily_machine_stats": 1, "incidents": 1, "kpis_daily": 1}
    assert result["errors"] == {} and len(result["job_ids"]) == 3
    # el scan de incidentes filtra por sk=META y última ventana (Attr gte)
    assert "FilterExpression" in incidents.scan_kwargs
