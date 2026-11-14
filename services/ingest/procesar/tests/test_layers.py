"""Capas 1 y 2 y su combinación (RF-02.1, RF-02.2, RF-02.5, RF-09)."""

import json

import pytest
from ingest_procesar import message, rules, scoring
from ingest_procesar.baseline import Baseline


# ---------------------------------------------------------------- mensaje
def test_parse_valid_envelope(base_reading):
    env = message.parse(
        json.dumps({"correlation_id": "cid", "batch": {"readings": [base_reading, {"machine_id": "X"}]}})
    )
    assert env.correlation_id == "cid"
    assert len(env.readings) == 1 and env.invalid == 1


def test_parse_rejects_body_without_batch():
    with pytest.raises(message.InvalidMessage):
        message.parse('{"hola": 1}')


# ---------------------------------------------------------------- capa 1
def test_rules_levels():
    limits = {"temperature_c": {"warn_high": 100, "crit_high": 110}, "pressure_bar": {"warn_low": 150, "crit_low": 100}}
    hits = rules.evaluate({"temperature_c": 112, "pressure_bar": 140}, limits)
    assert rules.RuleHit("temperature_c", "crit", "high") in hits
    assert rules.RuleHit("pressure_bar", "warn", "low") in hits
    assert rules.evaluate({"temperature_c": 90, "pressure_bar": 200}, limits) == []


def test_threshold_provider_uses_ssm_then_cache_then_defaults():
    calls = []

    def fetch(model):
        calls.append(model)
        return '{"rpm": {"warn_high": 1}}' if model == "EPI-PV271" else None

    clock = iter([0, 10, 400, 500]).__next__
    provider = rules.ThresholdProvider(fetch, ttl_s=300, clock=clock)
    assert provider.get("EPI-PV271", "drill") == {"rpm": {"warn_high": 1}}
    provider.get("EPI-PV271", "drill")  # dentro del TTL: no consulta SSM
    assert provider.get("CAT-336", "excavator")["temperature_c"] == {"warn_high": 97.0, "crit_high": 100.0}
    assert "temperature_c" in provider.get("XX-1", "excavator")  # modelo desconocido: respaldo por tipo
    assert calls == ["EPI-PV271", "CAT-336", "XX-1"]


def test_low_rules_only_when_operating():
    limits = {"pressure_bar": {"warn_low": 150, "crit_low": 100}}
    assert rules.evaluate({"pressure_bar": 0, "state": "stopped"}, limits) == []
    assert rules.evaluate({"pressure_bar": 0, "state": "operating"}, limits) == [
        rules.RuleHit("pressure_bar", "crit", "low")
    ]


def test_derived_thresholds_follow_nominal():
    t = rules.derive_thresholds({"temperature_c": [88, 3], "pressure_bar": [300, 15], "load_pct": [70, 10]})
    assert t["temperature_c"] == {"warn_high": 97.0, "crit_high": 100.0}
    assert t["pressure_bar"] == {"warn_high": 345.0, "crit_high": 360.0, "warn_low": 255.0, "crit_low": 240.0}
    assert "load_pct" not in t  # carga y velocidad son de productividad (RF-08), no de falla


def test_defaults_file_is_in_sync_with_seed():
    """`thresholds_default.json` = derivado del seed v2 (regenerar con `python .../rules.py`)."""
    seed_models = json.loads(rules.seed_models_file().read_text())
    assert json.loads(rules.DEFAULTS_FILE.read_text()) == rules.build_defaults(seed_models)


# ---------------------------------------------------------------- capa 2
def test_ewma_zscore_after_warmup():
    b = Baseline()
    assert b.zscore("t", 100.0, warmup=5) == 0.0  # sin historia: warm-up
    for x in (80, 81, 79, 80, 82, 78, 80, 81):
        b.update({"t": float(x)}, alpha=0.05)
    assert abs(b.zscore("t", 80.0, warmup=5)) < 1
    assert b.zscore("t", 95.0, warmup=5) > 5


def test_baseline_roundtrip():
    b = Baseline()
    b.update({"t": 1.0}, 0.1)
    b.update({"t": 3.0}, 0.1)
    again = Baseline.from_item(b.to_item())
    assert again.stats["t"].n == 2 and again.stats["t"].mean == pytest.approx(2.0)


# ---------------------------------------------------------------- combinación
def test_joint_moderate_deviations_weigh_more_than_one():
    reading = {"state": "operating"}
    single = scoring.assess(reading, [], {"temperature_c": 3.0, "vibration_mm_s": 0, "fuel_rate_lph": 0}, {}, None)
    joint = scoring.assess(reading, [], {"temperature_c": 3.0, "vibration_mm_s": 3.0, "fuel_rate_lph": 3.0}, {}, None)
    assert joint.risk > single.risk
    assert joint.health_score < single.health_score
    assert scoring.is_alert(joint.severity) and not scoring.is_alert(single.severity)


def test_critical_rules_set_severity_floor():
    reading = {"state": "operating"}
    one = scoring.assess(reading, [rules.RuleHit("temperature_c", "crit", "high")], {}, {}, None)
    two = scoring.assess(
        reading,
        [rules.RuleHit("temperature_c", "crit", "high"), rules.RuleHit("vibration_mm_s", "crit", "high")],
        {},
        {},
        None,
    )
    assert one.severity == "high"
    assert two.severity == "critical" and two.status == "needs_intervention"


def test_top_factors_shape_and_order():
    a = scoring.assess(
        {"state": "operating"},
        [],
        {"temperature_c": 2.5, "vibration_mm_s": -4.0, "rpm": 0.1},
        {"temperature_c": 3.5},
        None,
    )
    assert [f["variable"] for f in a.top_factors] == ["vibration_mm_s", "temperature_c", "rpm"]
    assert a.top_factors[0] == {"variable": "vibration_mm_s", "z_score": -4.0, "direction": "low"}


def test_healthy_reading_is_info():
    a = scoring.assess({"state": "operating"}, [], {"temperature_c": 0.3}, {}, None)
    assert a.severity == "info" and a.health_score == 100 and a.status == "operational"
