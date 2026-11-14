"""incidente: pasos de dominio de la SFN `GestionIncidente` que escriben estructuras anidadas
(RF-06, RF-11.1, RF-11.2, RF-04.6, TRZ-03; contratos.md §8.1-§8.3, §9.1).

La SFN usa integraciones SDK directas para lo simple (reclamar la máquina, crear el incidente, aceptar,
escalar, PutEvents). Esta Lambda hace lo que en ASL sería frágil: armar `candidate_parts`, guardar el
diagnóstico (mapas y listas), derivar `required_specialty`, asignar con `scoring_candidates`, guardar los
task tokens, resolver (downtime + notas de resolución con su autor), leer el chat de Firestore para el resumen IA
(`chat_mensajes`, RF-15/RF-16.8) y cerrar (registro `corrective`, descuento de inventario, liberar la máquina).

Entrada: `{ "action": "<accion>", ... }`. Cada acción es idempotente frente a reintentos de la SFN.
"""
import json
from datetime import UTC, datetime
from decimal import Decimal

# §8.2: variable dominante (top_factors[0]) → especialidad
SPECIALTY_BY_VARIABLE = {
    "temperature_c": "motor",
    "vibration_mm_s": "motor",
    "fuel_rate_lph": "motor",
    "rpm": "motor",
    "pressure_bar": "hidraulica",
    "load_pct": "hidraulica",
    "speed_kmh": "neumaticos",
}
SILENCE_SPECIALTY = "electrica"
DEFAULT_SPECIALTY = "motor"
OPEN_STATUSES = ("detected", "assigned", "in_progress")
RECENT_INCIDENTS = 5


class ConditionFailed(Exception):
    """Estado del incidente incompatible con el paso (la SFN lo captura por nombre)."""


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def to_ddb(value):
    """Python → tipos que acepta DynamoDB (float → Decimal, sin None en mapas)."""
    if isinstance(value, dict):
        return {k: to_ddb(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [to_ddb(v) for v in value]
    if isinstance(value, float):
        return Decimal(str(value))
    return value


def from_ddb(value):
    if isinstance(value, dict):
        return {k: from_ddb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [from_ddb(v) for v in value]
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _code(exc: Exception) -> str:
    return getattr(exc, "response", {}).get("Error", {}).get("Code", "")


def part_ids(parts) -> list[str]:
    """`parts_suggested` puede venir como IDs (fixture) o como objetos `{component_id}` (§8.1)."""
    out = []
    for p in parts or []:
        pid = p.get("component_id") if isinstance(p, dict) else p
        if isinstance(pid, str) and pid:
            out.append(pid)
    return out


def required_specialty(source: str, top_factors: list, parts_suggested, candidate_parts: list) -> str:
    """Regla de contratos.md §8.2."""
    ids = part_ids(parts_suggested)
    by_id = {p.get("component_id"): p.get("specialty") for p in candidate_parts or []}
    if ids and by_id.get(ids[0]):
        return by_id[ids[0]]
    if source == "silence":
        return SILENCE_SPECIALTY
    if top_factors:
        dominant = max(top_factors, key=lambda f: abs(float(f.get("z_score") or 0)))
        return SPECIALTY_BY_VARIABLE.get(dominant.get("variable"), DEFAULT_SPECIALTY)
    return DEFAULT_SPECIALTY


class Incidente:
    def __init__(self, tables: dict, operation_id: str = "OP-01", chat=None):
        self.t = tables
        self.operation_id = operation_id
        self._chat = chat  # FirestoreChat (chat_firestore.py); se crea bajo demanda en run()

    # ---------- utilidades ----------
    def _key(self, incident_id: str) -> dict:
        return {"pk": f"INC#{incident_id}", "sk": "META"}

    def _machine_key(self, machine_id: str) -> dict:
        return {"pk": f"{self.operation_id}#{machine_id}", "sk": "META"}

    def get(self, incident_id: str) -> dict:
        item = self.t["incidents"].get_item(Key=self._key(incident_id)).get("Item")
        if not item:
            raise ConditionFailed(f"Incidente {incident_id} no existe")
        return item

    def _update(self, incident_id: str, expr: str, values: dict, cond: str | None = None, names: dict | None = None):
        kwargs = {
            "Key": self._key(incident_id),
            "UpdateExpression": expr,
            "ExpressionAttributeValues": to_ddb(values),
            "ReturnValues": "ALL_NEW",
        }
        if names:
            kwargs["ExpressionAttributeNames"] = names
        if cond:
            kwargs["ConditionExpression"] = cond
        try:
            return self.t["incidents"].update_item(**kwargs)["Attributes"]
        except Exception as exc:  # noqa: BLE001
            if _code(exc) == "ConditionalCheckFailedException":
                raise ConditionFailed(f"{incident_id}: estado incompatible") from exc
            raise

    def _adjust_load(self, technician_id: str | None, delta: int) -> None:
        if not technician_id:
            return
        try:
            self.t["technicians"].update_item(
                Key={"pk": f"TECH#{technician_id}", "sk": "META"},
                UpdateExpression="SET current_load = if_not_exists(current_load, :z) + :d",
                ConditionExpression="attribute_exists(pk)" + (" AND current_load > :z" if delta < 0 else ""),
                ExpressionAttributeValues={":z": 0, ":d": delta},
            )
        except Exception as exc:  # noqa: BLE001 - técnico inexistente o carga ya en 0
            if _code(exc) != "ConditionalCheckFailedException":
                raise

    # ---------- acciones ----------
    def contexto(self, ev: dict) -> dict:
        """Payload de `diagnose` (§8.1) con `candidate_parts` desde el catálogo."""
        machine = self.t["machines"].get_item(Key=self._machine_key(ev["machine_id"])).get("Item") or {}
        model = machine.get("model")
        candidate_parts = []
        if model:
            mdl = self.t["catalog"].get_item(Key={"pk": f"MODEL#{model}", "sk": "META"}).get("Item") or {}
            ids = list(mdl.get("component_ids") or [])
            for i in range(0, len(ids), 100):
                keys = [{"pk": f"COMPONENT#{cid}", "sk": "META"} for cid in ids[i : i + 100]]
                resp = self.t["resource"].batch_get_item(RequestItems={self.t["catalog"].name: {"Keys": keys}})
                found = {c["component_id"]: c for c in resp.get("Responses", {}).get(self.t["catalog"].name, [])}
                candidate_parts += [
                    {"component_id": cid, "name": found[cid].get("name"), "specialty": found[cid].get("specialty")}
                    for cid in ids[i : i + 100]
                    if cid in found
                ]
        last = self.t["machine_state"].get_item(Key={"pk": ev["machine_id"], "sk": "LAST"}).get("Item") or {}
        reading = last.get("reading") or {}
        latest = {k: reading[k] for k in ("temperature_c", "vibration_mm_s", "pressure_bar", "fuel_rate_lph", "rpm",
                                          "load_pct", "speed_kmh") if k in reading}
        recent = self._recent_incidents(ev["machine_id"], ev["incident_id"])
        location = machine.get("location") or {}
        payload = {
            "machine_id": ev["machine_id"],
            "machine_type": machine.get("type"),
            "model": model,
            "zone": ev.get("zone") or machine.get("zone"),
            "severity": ev.get("severity"),
            "health_score": ev.get("health_score", machine.get("health_score")),
            "top_factors": ev.get("top_factors") or [],
            "latest_reading": latest,
            "recent_incidents": recent,
            "candidate_parts": candidate_parts,
        }
        return from_ddb(
            {
                "diagnose_payload": payload,
                "location": {"lat": location.get("lat"), "lon": location.get("lon"),
                             "zone": location.get("zone") or payload["zone"]},
            }
        )

    def _recent_incidents(self, machine_id: str, incident_id: str) -> list:
        from boto3.dynamodb.conditions import Key

        page = self.t["incidents"].query(
            IndexName="by_machine",
            KeyConditionExpression=Key("machine_id").eq(machine_id),
            ScanIndexForward=False,
            Limit=RECENT_INCIDENTS + 1,
        )
        out = []
        for i in page.get("Items", []):
            if i.get("incident_id") == incident_id:
                continue
            diag = i.get("ai_diagnosis") or {}
            out.append({"incident_id": i.get("incident_id"), "detected_at": i.get("detected_at"),
                        "severity": i.get("severity"), "status": i.get("status"),
                        "probable_cause": diag.get("probable_cause"),
                        "components_replaced": i.get("components_replaced") or []})
        return out[:RECENT_INCIDENTS]

    def enriquecer(self, ev: dict) -> dict:
        """Guarda diagnóstico + correlación, deriva `required_specialty` (§8.2) y revisa stock (rama stock)."""
        diag = ev.get("diagnosis") or {}
        result = diag.get("result") or {}
        candidate_parts = ev.get("candidate_parts") or []
        parts = part_ids(result.get("parts_suggested"))
        specialty = required_specialty(ev.get("source", "anomaly"), ev.get("top_factors") or [], parts, candidate_parts)
        corr = ev.get("correlation") or {}
        machines = corr.get("machines") or [ev["machine_id"]]
        parent = corr.get("parent_incident_id")
        machine_ids = machines if (not parent and len(machines) >= 3) else [ev["machine_id"]]
        ai = {
            "probable_cause": result.get("probable_cause"),
            "suggested_action": result.get("suggested_action"),
            "confidence": result.get("confidence"),
            "parts_suggested": parts,
            "top_factors": ev.get("top_factors") or [],
            "common_cause": (ev.get("common_cause") or {}).get("probable_common_cause"),
            "model_version": ev.get("model_version"),
            "model": diag.get("model"),
            "prompt_version": diag.get("prompt_version"),
            "degraded": bool(diag.get("degraded", not diag)),
        }
        expr = "SET ai_diagnosis = :ai, required_specialty = :sp, machine_ids = :mids"
        values = {":ai": ai, ":sp": specialty, ":mids": machine_ids}
        if parent:
            expr += ", parent_incident_id = :parent"
            values[":parent"] = parent
        self._update(ev["incident_id"], expr, values, "attribute_exists(pk)")
        stock = self._stock(parts[0], ev.get("zone")) if parts else None
        return {
            "required_specialty": specialty,
            "parent_incident_id": parent,
            "part_id": parts[0] if parts else None,
            "stock_in_zone": stock,
            "shortage": stock is not None and stock <= 0,
        }

    def _stock(self, component_id: str, zone: str | None) -> int:
        from boto3.dynamodb.conditions import Key

        items = self.t["inventory"].query(
            IndexName="by_component", KeyConditionExpression=Key("component_id").eq(component_id)
        ).get("Items", [])
        return int(sum(i.get("stock", 0) for i in items if not zone or i.get("zone") == zone))

    def asignar(self, ev: dict) -> dict:
        """detected/assigned → assigned. Guarda `scoring_candidates` y `technician_score` (TRZ-03)."""
        technician_id = ev["technician_id"]
        current = self.get(ev["incident_id"])
        previous = current.get("assigned_technician_id")
        candidates = (ev.get("scoring") or {}).get("candidates")
        score = next((c.get("score") for c in candidates or [] if c.get("technician_id") == technician_id), None)
        sets = ["#st = :assigned", "assigned_technician_id = :tid", "assigned_at = :now"]
        removes = ["ack_token"]
        values = {":assigned": "assigned", ":tid": technician_id, ":now": now_iso(), ":d": "detected", ":a": "assigned"}
        if candidates is not None:
            sets.append("scoring_candidates = :cands")
            values[":cands"] = candidates
        if score is not None:
            sets.append("technician_score = :score")
            values[":score"] = score
        else:  # asignación manual fuera del ranking
            removes.append("technician_score")
        expr = f"SET {', '.join(sets)} REMOVE {', '.join(removes)}"
        self._update(ev["incident_id"], expr, values, "#st IN (:d, :a)", {"#st": "status"})
        if previous != technician_id:
            self._adjust_load(previous, -1)
            self._adjust_load(technician_id, +1)
        return {"from": current.get("status"), "technician_id": technician_id,
                "previous_technician_id": previous, "technician_score": score}

    def guardar_token(self, ev: dict) -> dict:
        """Guarda el task token (`ack_token` o `resolve_token`) solo si el estado coincide (§9.1)."""
        name = ev["token_name"]
        if name not in ("ack_token", "resolve_token"):
            raise ValueError("token_name inválido")
        statuses = ev.get("statuses") or ["assigned"]
        placeholders = {f":s{i}": s for i, s in enumerate(statuses)}
        cond = f"#st IN ({', '.join(placeholders)})"
        self._update(ev["incident_id"], f"SET {name} = :tok, execution_arn = if_not_exists(execution_arn, :arn)",
                     {":tok": ev["token"], ":arn": ev.get("execution_arn") or "-", **placeholders}, cond,
                     {"#st": "status"})
        return {"stored": name}

    def resolver(self, ev: dict) -> dict:
        """in_progress → resolved con downtime, componentes y costo (RF-11.2)."""
        current = self.get(ev["incident_id"])
        res = ev.get("resolution") or {}
        now = now_iso()
        downtime = max(0, round((_parse(now) - _parse(current["detected_at"])).total_seconds() / 60))
        values = {
            ":resolved": "resolved", ":ip": "in_progress", ":now": now, ":dt": downtime,
            ":comp": [c for c in res.get("components_replaced") or [] if isinstance(c, str)],
            ":notes": res.get("resolution_notes") or "",
        }
        expr = ("SET #st = :resolved, resolved_at = :now, downtime_minutes = :dt, components_replaced = :comp, "
                "resolution_notes = :notes")
        actor = res.get("actor") or {}
        if actor.get("user_id"):  # autor de las notas de resolución (el front lo muestra junto a ellas)
            expr += ", resolved_by = :by"
            values[":by"] = {"user_id": actor["user_id"], "role": actor.get("role")}
        if res.get("cost_usd") is not None:
            expr += ", cost_usd = :cost"
            values[":cost"] = float(res["cost_usd"])
        expr += " REMOVE resolve_token, ack_token"
        self._update(ev["incident_id"], expr, values, "#st = :ip", {"#st": "status"})
        return {"from": "in_progress", "downtime_minutes": downtime, "resolved_at": now,
                "technician_id": current.get("assigned_technician_id")}

    def chat_mensajes(self, ev: dict) -> dict:
        """Mensajes del chat del incidente (Firestore) para `summarize_chat`: solo conversación, sin las notas de
        resolución ni mensajes del sistema (RF-15, RF-16.8). El canal es `chat_channel_id` (o el del padre)."""
        current = from_ddb(self.get(ev["incident_id"]))
        channel = current.get("chat_channel_id") or current.get("parent_incident_id") or ev["incident_id"]
        if self._chat is None:  # pragma: no cover - en Lambda
            import os

            import chat_firestore

            self._chat = chat_firestore.from_env(os.environ)
        return {"channel": channel, "messages": self._chat.messages(channel)}

    def cerrar(self, ev: dict) -> dict:
        """resolved → closed: resumen IA, registro `corrective`, descuento de inventario y liberar la máquina.

        `resolution_summary` es SOLO el resumen del chat (summarize_chat); las notas de resolución quedan en
        `resolution_notes` y el front las muestra en un bloque aparte."""
        current = from_ddb(self.get(ev["incident_id"]))
        if current.get("status") == "closed":  # reintento
            return {"from": "closed", "shortage": False, "low_stock": []}
        summary = ((ev.get("summary") or {}).get("result") or {})
        text = summary.get("summary") or None
        notes = current.get("resolution_notes") or ""
        now = now_iso()
        machine_id = current["machine_id"]
        machine = self.t["machines"].get_item(Key=self._machine_key(machine_id)).get("Item") or {}
        tech_id = current.get("assigned_technician_id")
        components = current.get("components_replaced") or []
        record_id = f"MR-{ev['incident_id'].removeprefix('INC-')}"
        record = {
            "pk": machine_id,
            "sk": f"{now}#{record_id}",
            "record_id": record_id,
            "machine_id": machine_id,
            "zone": current.get("zone"),
            "type": "corrective",
            "performed_at": now,
            "technician_id": tech_id,
            "incident_id": ev["incident_id"],
            "operating_hours": machine.get("operating_hours"),
            "components": [{"component_id": c, "quantity": 1} for c in components],
            "cost_usd": current.get("cost_usd") or 0,
            "notes": (notes or text or "")[:1000] or None,
        }
        self.t["maintenance_records"].put_item(Item=to_ddb(record))
        low_stock = self._discount(components, tech_id, current.get("zone"))
        # Sin resumen del chat (falló la IA): resolution_summary queda vacío; las notas NO lo reemplazan.
        self._update(
            ev["incident_id"],
            "SET #st = :closed, closed_at = :now, root_cause = :rc"
            + (", resolution_summary = :sum REMOVE ack_token, resolve_token" if text
               else " REMOVE ack_token, resolve_token, resolution_summary"),
            {":closed": "closed", ":now": now, ":rc": summary.get("root_cause") or "-", ":r": "resolved",
             **({":sum": text} if text else {})},
            "#st = :r",
            {"#st": "status"},
        )
        self.liberar({"incident_id": ev["incident_id"], "machine_id": machine_id})
        self._adjust_load(tech_id, -1)
        return {"from": "resolved", "record_id": record_id, "low_stock": low_stock, "shortage": bool(low_stock)}

    def _discount(self, components: list[str], tech_id: str | None, zone: str | None) -> list[str]:
        """Descuenta 1 unidad por componente en el almacén de la zona. Devuelve los que quedan bajo `stock_min`."""
        if not components:
            return []
        warehouse = None
        if tech_id:
            tech = self.t["technicians"].get_item(Key={"pk": f"TECH#{tech_id}", "sk": "META"}).get("Item") or {}
            warehouse = tech.get("home_warehouse_id")
        low = []
        for cid in components:
            wh = warehouse or self._warehouse_for(cid, zone)
            if not wh:
                continue
            try:
                attrs = self.t["inventory"].update_item(
                    Key={"pk": wh, "sk": cid},
                    UpdateExpression="SET stock = stock - :one",
                    ConditionExpression="attribute_exists(pk) AND stock >= :one",
                    ExpressionAttributeValues={":one": 1},
                    ReturnValues="ALL_NEW",
                )["Attributes"]
                if attrs.get("stock", 0) < attrs.get("stock_min", 0):
                    low.append(cid)
            except Exception as exc:  # noqa: BLE001
                if _code(exc) != "ConditionalCheckFailedException":
                    raise
                low.append(cid)
        return low

    def _warehouse_for(self, component_id: str, zone: str | None) -> str | None:
        from boto3.dynamodb.conditions import Key

        items = self.t["inventory"].query(
            IndexName="by_component", KeyConditionExpression=Key("component_id").eq(component_id)
        ).get("Items", [])
        match = [i for i in items if i.get("zone") == zone] or items
        return match[0]["pk"] if match else None

    def liberar(self, ev: dict) -> dict:
        """Quita `open_incident_id` de la máquina (solo si sigue apuntando a este incidente)."""
        try:
            self.t["machines"].update_item(
                Key=self._machine_key(ev["machine_id"]),
                UpdateExpression="REMOVE open_incident_id",
                ConditionExpression="open_incident_id = :id",
                ExpressionAttributeValues={":id": ev["incident_id"]},
            )
            return {"released": True}
        except Exception as exc:  # noqa: BLE001
            if _code(exc) == "ConditionalCheckFailedException":
                return {"released": False}
            raise


ACTIONS = ("contexto", "enriquecer", "asignar", "guardar_token", "resolver", "chat_mensajes", "cerrar", "liberar")


def _default_tables() -> dict:  # pragma: no cover
    import boto3
    from arquifusion_shared import config

    ddb = boto3.resource("dynamodb")
    names = {
        "incidents": "incidents", "machines": "machines", "machine_state": "machine-state", "catalog": "catalog",
        "inventory": "inventory", "technicians": "technicians", "maintenance_records": "maintenance-records",
    }
    tables = {k: ddb.Table(config.table(v)) for k, v in names.items()}
    tables["resource"] = ddb
    return tables


_TABLES: dict | None = None


_CHAT = None


def run(event: dict, tables: dict | None = None, chat=None) -> dict:
    global _TABLES, _CHAT
    from arquifusion_shared import config

    if tables is None:
        _TABLES = _TABLES or _default_tables()
        tables = _TABLES
    action = event.get("action")
    if action not in ACTIONS:
        raise ValueError(f"Acción desconocida: {action}")
    inc = Incidente(tables, config.default_operation_id(), chat or _CHAT)
    result = getattr(inc, action)(event)
    if chat is None and inc._chat is not None:
        _CHAT = inc._chat  # reutiliza el token de GCP entre invocaciones del contenedor
    return json.loads(json.dumps(from_ddb(result)))
