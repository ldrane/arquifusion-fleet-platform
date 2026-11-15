from datetime import UTC, datetime, timedelta

import service

BASE = datetime(2026, 11, 14, 12, 0, 0, tzinfo=UTC)


def _iso(hours: float) -> str:
    return (BASE + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def incident(idx: int) -> dict:
    """Incidente cerrado de la máquina CM-<idx> detectado en BASE; su anomalía previa se arma aparte."""
    return {
        "incident_id": f"INC-{idx}",
        "machine_id": f"CM-{idx}",
        "status": "closed",
        "detected_at": _iso(0),
        "model": "CAT-336",
    }


def anomaly(machine: str, hours_before: float, variable: str, z: float = 1.7) -> dict:
    return {
        "machine_id": machine,
        "detected_at": _iso(-hours_before),
        "model": "CAT-336",
        "top_factors": [{"variable": variable, "z_score": z, "direction": "high"}],
    }


def test_firmas_prefalla_share_y_mediana():
    incidents = [incident(i) for i in range(4)]
    anomalies = {
        "CM-0": [anomaly("CM-0", 20, "vibration_mm_s")],
        "CM-1": [anomaly("CM-1", 18, "vibration_mm_s")],
        "CM-2": [anomaly("CM-2", 16, "vibration_mm_s")],
        "CM-3": [anomaly("CM-3", 5, "temperature_c")],
    }
    out = service.build_precursors(incidents, anomalies)
    assert len(out) == 1
    group = out[0]
    assert group["model"] == "CAT-336" and group["n_incidents"] == 4
    vib = group["signatures"][0]
    assert vib["variable"] == "vibration_mm_s"
    assert vib["share"] == 0.75 and vib["median_lead_time_h"] == 18.0
    assert "75 %" in group["headline"] and "18 h" in group["headline"]


def test_ignora_modelos_con_menos_de_tres_incidentes():
    incidents = [incident(i) for i in range(2)]
    out = service.build_precursors(incidents, {"CM-0": [anomaly("CM-0", 10, "vibration_mm_s")]})
    assert out == []


def test_sin_anomalia_previa_no_hay_firma():
    incidents = [incident(i) for i in range(3)]
    out = service.build_precursors(incidents, {"CM-0": []})
    assert out == []  # 3 incidentes pero sin señal previa → nada que mostrar


def test_anomalia_fuera_de_la_ventana_de_72h_se_ignora():
    incidents = [incident(i) for i in range(3)]
    out = service.build_precursors(incidents, {"CM-0": [anomaly("CM-0", 100, "vibration_mm_s")]})
    assert out == []
