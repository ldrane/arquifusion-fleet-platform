import json
from pathlib import Path

import pytest
import service

FIX = Path(__file__).parents[4] / "contracts" / "fixtures"
CFG = {"bot_token": "123:abc", "chat_ids": ["-100", "42"]}
INCIDENT = {
    "incident_id": "INC-01JC8ZK",
    "assigned_technician_id": "TEC-07",
    "ai_diagnosis": {
        "probable_cause": "desgaste de rodamiento <B2>",
        "suggested_action": "inspeccionar rodamientos",
        "top_factors": [{"variable": "vibration_mm_s", "z_score": 3.1}],
    },
}


def bridge_event(**data):
    entry = json.loads((FIX / "events/incident_state_changed.json").read_text())[0]
    detail = json.loads(entry["Detail"])
    detail["data"].update(data)
    return {"id": "eb-1", "detail-type": entry["DetailType"], "source": entry["Source"], "detail": detail}


def make_deps(cfg=CFG, fail_chats=(), claimed=()):
    state = {"sent": [], "claims": set(claimed), "released": []}

    def claim(key):
        if key in state["claims"]:
            return False
        state["claims"].add(key)
        return True

    def release(key):
        state["claims"].discard(key)
        state["released"].append(key)

    def send(token, chat, text, markup):
        if chat in fail_chats:
            raise RuntimeError("HTTP 400")
        state["sent"].append({"token": token, "chat": chat, "text": text, "markup": markup})

    deps = {"config": lambda: cfg, "claim": claim, "release": release, "incident": lambda _id: INCIDENT,
            "send": send}
    return deps, state


def test_envia_critico_a_todos_los_chats():
    deps, state = make_deps()
    res = service.TelegramNotifier(deps).run(bridge_event(severity="critical", event_type="incident.detected"))
    assert res["sent"] == 2
    assert [s["chat"] for s in state["sent"]] == ["-100", "42"]
    text = state["sent"][0]["text"]
    assert "CRÍTICO" in text and "EX-023" in text and "INC-01JC8ZK" in text
    assert "&lt;B2&gt;" in text  # HTML escapado
    assert "3.1σ" in text


@pytest.mark.parametrize("severity", ["high", "medium", None])
def test_ignora_no_criticos(severity):
    deps, state = make_deps()
    res = service.TelegramNotifier(deps).run(bridge_event(severity=severity))
    assert res["skipped"] == "severity" and not state["sent"]


def test_ignora_event_type_fuera_de_la_lista():
    deps, state = make_deps()
    res = service.TelegramNotifier(deps, ["incident.detected"]).run(
        bridge_event(severity="critical", event_type="incident.assigned"))
    assert res["skipped"] == "event_type" and not state["sent"]


def test_sin_configuracion_no_falla():
    deps, state = make_deps(cfg=None)
    res = service.TelegramNotifier(deps).run(bridge_event(severity="critical"))
    assert res["skipped"] == "sin configuración"


def test_reintento_de_eventbridge_no_duplica():
    deps, state = make_deps()
    n = service.TelegramNotifier(deps)
    ev = bridge_event(severity="critical")
    n.run(ev)
    res = n.run(ev)
    assert res["sent"] == 0 and res["duplicates"] == 2 and len(state["sent"]) == 2


def test_fallo_parcial_libera_reserva_y_no_relanza():
    deps, state = make_deps(fail_chats=("42",))
    res = service.TelegramNotifier(deps).run(bridge_event(severity="critical"))
    assert res["sent"] == 1 and res["failed"] == 1
    assert len(state["released"]) == 1 and state["released"][0].endswith("#42")


def test_fallo_total_relanza_para_reintento():
    deps, state = make_deps(fail_chats=("-100", "42"))
    with pytest.raises(RuntimeError):
        service.TelegramNotifier(deps).run(bridge_event(severity="critical"))
    assert not state["claims"]  # el reintento podrá volver a enviar


def test_boton_solo_con_app_url_https():
    deps, state = make_deps()
    service.TelegramNotifier(deps, app_url="https://app.example.com/").run(bridge_event(severity="critical"))
    btn = state["sent"][0]["markup"]["inline_keyboard"][0][0]
    assert btn["url"] == "https://app.example.com/incidents/INC-01JC8ZK"

    deps, state = make_deps()
    service.TelegramNotifier(deps, app_url="http://localhost:5173").run(bridge_event(severity="critical"))
    assert state["sent"][0]["markup"] is None


@pytest.mark.parametrize("raw,expected", [
    ('{"bot_token": "t", "chat_ids": "1, -2"}', ["1", "-2"]),
    ('{"bot_token": "t", "chat_id": 123}', ["123"]),
    ('{"bot_token": "t", "chat_ids": ["7"]}', ["7"]),
])
def test_parse_config(raw, expected):
    assert service.parse_config(raw)["chat_ids"] == expected


@pytest.mark.parametrize("raw", [None, "", "no-json", '{"bot_token": ""}', '{"bot_token": "t", "chat_ids": ""}'])
def test_parse_config_invalida(raw):
    assert service.parse_config(raw) is None
