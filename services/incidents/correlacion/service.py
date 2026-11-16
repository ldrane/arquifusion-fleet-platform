"""correlacion-zona (RF-12.1, RF-12.2). Contrato: contratos.md §8.4, fixtures `internal/correlacion_*.json`.

Request `{incident_id, zone, reading_ts, machine_id?}` → Response `{parent_incident_id | null, machines[]}`.

1. Consulta `anomalies` por el GSI `by_zone` (`zone` = Z, `detected_at` entre `reading_ts − 15 min` y `reading_ts`).
2. Si hay menos de 3 máquinas distintas → no hay correlación (`parent_incident_id = null`).
3. Si hay ≥ 3: el **incidente padre** es el incidente abierto más antiguo de otra máquina del grupo que no sea hijo
   de otro. Se le agregan este incidente en `child_incident_ids` y la máquina en `machine_ids`.
   Si ninguna otra máquina tiene incidente abierto, este incidente queda como padre (`parent_incident_id = null`)
   y la SFN guarda `machine_ids = machines`.

Atomicidad (RF-12.1): hijo→padre se enlaza en UNA transacción (`TransactWriteItems`) con
`attribute_not_exists(parent_incident_id)` en el hijo **y** en el padre. `incidente` (SFN) escribía el
`parent_incident_id` después, así que dos correlaciones simultáneas podían verse mutuamente "sin padre" y
enlazarse entre sí (ciclo). Con la transacción, la segunda se cancela y ese incidente queda como padre.
"""
from datetime import UTC, datetime, timedelta

WINDOW_MIN = 15
MIN_MACHINES = 3
OPEN_STATUSES = {"detected", "assigned", "in_progress"}


class LinkRejected(Exception):
    """El candidato dejó de ser elegible como padre (otra correlación lo enlazó antes). Se prueba el siguiente."""


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def window(reading_ts: str) -> tuple[str, str]:
    end = _parse(reading_ts)
    # +1 s en el borde superior: incluye la propia lectura aunque venga con milisegundos
    return _iso(end - timedelta(minutes=WINDOW_MIN)), _iso(end + timedelta(seconds=1))


class Repo:
    """Acceso a DynamoDB (se reemplaza por un fake en los tests)."""

    def __init__(self, anomalies, incidents, transact=None):
        self.anomalies = anomalies
        self.incidents = incidents
        self._transact = transact  # inyectable para tests; por defecto, boto3 transact_write_items

    def machines_in_window(self, zone: str, start: str, end: str) -> list[str]:
        from boto3.dynamodb.conditions import Key

        kwargs = {
            "IndexName": "by_zone",
            "KeyConditionExpression": Key("zone").eq(zone) & Key("detected_at").between(start, end),
            "ProjectionExpression": "machine_id",
        }
        seen: list[str] = []
        while True:
            page = self.anomalies.query(**kwargs)
            for item in page.get("Items", []):
                if item.get("machine_id") and item["machine_id"] not in seen:
                    seen.append(item["machine_id"])
            if "LastEvaluatedKey" not in page:
                return seen
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def latest_incident(self, machine_id: str) -> dict | None:
        from boto3.dynamodb.conditions import Key

        page = self.incidents.query(
            IndexName="by_machine",
            KeyConditionExpression=Key("machine_id").eq(machine_id),
            ScanIndexForward=False,
            Limit=1,
        )
        items = page.get("Items", [])
        return items[0] if items else None

    def link_child(self, parent_id: str, child_id: str, machine_id: str | None) -> str:
        """Enlaza `child_id` bajo `parent_id` de forma atómica. Devuelve el padre efectivo.

        - Condición del hijo: aún sin `parent_incident_id` (si ya lo tiene, es un reintento → se devuelve el padre
          que ya tenía).
        - Condición del padre: existe, sigue sin padre (nunca fue hijo de otro) y no contiene ya al hijo.
        Si el padre dejó de ser elegible, lanza `LinkRejected` para que `correlate` pruebe el siguiente candidato.
        """
        parent_key = {"pk": f"INC#{parent_id}", "sk": "META"}
        child_key = {"pk": f"INC#{child_id}", "sk": "META"}
        values: dict = {":empty": [], ":child": [child_id], ":cid": child_id}
        expr = "SET child_incident_ids = list_append(if_not_exists(child_incident_ids, :empty), :child)"
        if machine_id:
            expr += ", machine_ids = list_append(if_not_exists(machine_ids, :empty), :m)"
            values[":m"] = [machine_id]
        items = [
            {
                "Update": {
                    "TableName": self.incidents.table_name,
                    "Key": child_key,
                    "UpdateExpression": "SET parent_incident_id = :parent",
                    "ConditionExpression": "attribute_exists(pk) AND attribute_not_exists(parent_incident_id)",
                    "ExpressionAttributeValues": {":parent": parent_id},
                }
            },
            {
                "Update": {
                    "TableName": self.incidents.table_name,
                    "Key": parent_key,
                    "UpdateExpression": expr,
                    "ConditionExpression": (
                        "attribute_exists(pk) AND attribute_not_exists(parent_incident_id) "
                        "AND NOT contains(child_incident_ids, :cid)"
                    ),
                    "ExpressionAttributeValues": values,
                }
            },
        ]
        try:
            self._transact_write(items)
        except Exception as exc:  # noqa: BLE001 - TransactionCanceledException es el caso esperado
            if getattr(exc, "response", {}).get("Error", {}).get("Code") != "TransactionCanceledException":
                raise
            reasons = getattr(exc, "response", {}).get("CancellationReasons") or []
            child_failed = bool(reasons) and reasons[0].get("Code") == "ConditionalCheckFailed"
            if child_failed:
                # Reintento de la SFN: el hijo ya quedó enlazado; devolver el mismo padre (idempotente).
                existing = (self.incidents.get_item(Key=child_key).get("Item") or {}).get("parent_incident_id")
                if existing:
                    return existing
            raise LinkRejected(parent_id) from exc
        return parent_id

    def _transact_write(self, items: list[dict]) -> None:
        if self._transact is not None:
            self._transact(items)
            return
        self.incidents.meta.client.transact_write_items(TransactItems=items)


def correlate(request: dict, repo) -> dict:
    incident_id = request["incident_id"]
    own = request.get("machine_id")
    start, end = window(request["reading_ts"])
    machines = repo.machines_in_window(request["zone"], start, end)
    if own and own not in machines:
        machines.insert(0, own)
    if own:  # principal primero (contratos.md §9.1, machine_ids)
        machines = [own] + [m for m in machines if m != own]
    if len(machines) < MIN_MACHINES:
        return {"parent_incident_id": None, "machines": machines}

    candidates = []
    for machine_id in machines:
        if machine_id == own:
            continue
        inc = repo.latest_incident(machine_id)
        if (
            inc
            and inc.get("incident_id") != incident_id
            and inc.get("status") in OPEN_STATUSES
            and not inc.get("parent_incident_id")
        ):
            candidates.append(inc)
    if not candidates:
        return {"parent_incident_id": None, "machines": machines}

    # Más antiguo primero; si esa carrera la ganó otro, se prueba el siguiente candidato.
    for parent in sorted(candidates, key=lambda i: str(i.get("detected_at", ""))):
        try:
            linked = repo.link_child(parent["incident_id"], incident_id, own)
        except LinkRejected:
            continue
        return {"parent_incident_id": linked, "machines": machines}
    return {"parent_incident_id": None, "machines": machines}


def _default_repo() -> Repo:
    import boto3
    from arquifusion_shared import config

    ddb = boto3.resource("dynamodb")
    return Repo(ddb.Table(config.table("anomalies")), ddb.Table(config.table("incidents")))


def run(event: dict, repo=None) -> dict:
    return correlate(event, repo or _default_repo())
