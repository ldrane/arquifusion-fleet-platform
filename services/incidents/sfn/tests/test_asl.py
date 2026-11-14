"""Validación estructural de GestionIncidente (sin AWS): JSON válido, placeholders de Terraform,
transiciones existentes, estados alcanzables, Retry/Timeout en Tasks y eventos del §10."""

import json
import re
from pathlib import Path

ASL = Path(__file__).parents[1] / "gestion_incidente.asl.json"
RAW = ASL.read_text()
DEF = json.loads(RAW)
PLACEHOLDER = re.compile(r"\$\{(\w+)\}")
EXPECTED_VARS = {
    "operation_id",
    "table_machines",
    "table_incidents",
    "event_bus_name",
    "fn_incidente",
    "fn_scoring",
    "fn_correlacion",
    "fn_notificar",
    "fn_ia_gemini",
    "ack_timeout_s",
    "ack_timeout_critical_s",
    "resolve_timeout_s",
    "manual_timeout_s",
    "max_escalations",
}


def walk(states):
    for name, st in states.items():
        yield name, st, states
        for b in st.get("Branches", []):
            yield from walk(b["States"])


def targets(st):
    out = [st.get("Next"), st.get("Default")]
    out += [c["Next"] for c in st.get("Choices", []) + st.get("Catch", [])]
    return [t for t in out if t]


def test_placeholders_y_jsonata():
    assert set(PLACEHOLDER.findall(RAW)) == EXPECTED_VARS
    assert DEF["QueryLanguage"] == "JSONata"
    assert "%{" not in RAW  # templatefile de Terraform
    for name, st, _ in walk(DEF["States"]):
        for jsonpath_field in ("Parameters", "ResultPath", "ResultSelector", "InputPath", "OutputPath"):
            assert jsonpath_field not in st, f"{name} usa {jsonpath_field} (JSONPath)"


def test_expresiones_jsonata_balanceadas():
    for expr in re.findall(r'"\{% (.*?) %\}"', RAW):
        expr = expr.replace("\\'", "")
        stripped = re.sub(r"'[^']*'", "''", expr)
        for o, c in ("()", "[]", "{}"):
            assert stripped.count(o) == stripped.count(c), f"{o}{c} desbalanceado en: {expr}"


def test_transiciones_y_alcanzabilidad():
    for name, st, scope in walk(DEF["States"]):
        for t in targets(st):
            assert t in scope, f"{name} → {t} no existe"
        if st["Type"] == "Task":
            assert st.get("Retry"), f"{name} sin Retry"
            assert "TimeoutSeconds" in st, f"{name} sin TimeoutSeconds"
    reached, todo = set(), [DEF["StartAt"]]
    while todo:
        cur = todo.pop()
        if cur in reached:
            continue
        reached.add(cur)
        todo += targets(DEF["States"][cur])
    assert reached == set(DEF["States"]), f"inalcanzables: {set(DEF['States']) - reached}"


def test_esperas_con_task_token_y_timeout():
    s = DEF["States"]
    for name, token in (
        ("EsperarAceptacion", "ack_token"),
        ("EsperarResolucion", "resolve_token"),
        ("EsperarAsignacionManual", "ack_token"),
    ):
        assert s[name]["Resource"].endswith(".waitForTaskToken")
        assert f"'token_name': '{token}'" in s[name]["Arguments"]["Payload"]
        assert "$states.context.Task.Token" in s[name]["Arguments"]["Payload"]
        assert s[name]["Catch"]
    assert "'detected'" in s["EsperarAsignacionManual"]["Arguments"]["Payload"]  # #16


def test_emite_todos_los_event_type_de_incidente():
    emitted = set()
    for _, st, _ in walk(DEF["States"]):
        if st.get("Resource") == "arn:aws:states:::events:putEvents":
            entry = st["Arguments"]["Entries"][0]
            assert entry["Source"] == "arquifusion.incident" and entry["DetailType"] == "IncidentStateChanged"
            detail = entry["Detail"]
            for key in (
                "'incident_id'",
                "'from'",
                "'to'",
                "'event_type'",
                "'actor'",
                "'machine_id'",
                "'zone'",
                "'severity'",
                "'technician_id'",
                "'correlation_id'",
                "'version': 1",
            ):
                assert key in detail
            emitted |= set(re.findall(r"'event_type': '([a-z._]+)'", detail))
            if "$eventTypeDetected" in detail:
                emitted |= {"incident.detected", "machine.silent"}
    assert emitted == {
        "incident.detected",
        "machine.silent",
        "incident.assigned",
        "incident.in_progress",
        "incident.resolved",
        "incident.closed",
        "incident.escalated",
    }
