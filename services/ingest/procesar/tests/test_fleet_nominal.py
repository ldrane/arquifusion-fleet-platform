"""#2: la flota nominal del seed no dispara la capa 1 y la degradación de EX-023 sí (RF-02.1).

Usa el simulador real (flota cargada de `contracts/fixtures/seed`) para que umbrales y simulador no diverjan.
"""

import dataclasses
import json
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from ingest_procesar import rules
from service import Processor

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))  # raíz del repo: paquete `simulator`

from simulator.fleet import build_fleet  # noqa: E402
from simulator.generator import FleetSimulator  # noqa: E402
from simulator.scenarios import SCENARIOS  # noqa: E402

T0 = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def provider():
    return rules.ThresholdProvider(lambda model: None)


def _ticks(scenario: str, targets: set[str], n: int, minutes: int = 1, speedup: float = 60.0):
    sim = FleetSimulator(build_fleet(), SCENARIOS[scenario].effect, targets, started_at=T0, seed=11, speedup=speedup)
    return [sim.tick(T0 + timedelta(minutes=i * minutes)) for i in range(n)]


def test_every_seed_model_has_thresholds(provider):
    for spec in build_fleet():
        assert provider.get(spec.model, spec.machine_type) is provider.get(spec.model, spec.machine_type)
        assert set(provider.get(spec.model, spec.machine_type)) >= {"temperature_c", "vibration_mm_s", "fuel_rate_lph"}


def test_nominal_fleet_does_not_trigger_layer_one(provider):
    hits = Counter()
    readings = [r for tick in _ticks("normal", set(), 30) for r in tick]
    assert len({r["machine_id"] for r in readings}) == 100
    for r in readings:
        if rules.evaluate(r, provider.get(r["model"], r["type"])):
            hits[r["machine_id"]] += 1
    # 3 000 lecturas nominales: prácticamente ninguna cruza μ±3σ del modelo.
    assert sum(hits.values()) <= 3, hits


def test_degradation_of_ex023_triggers_layer_one(provider):
    ticks = _ticks("degradacion", {"EX-023"}, 49, minutes=1)  # speedup 60: 48 min reales = 48 h simuladas
    ex023 = [r for tick in ticks for r in tick if r["machine_id"] == "EX-023" and r["state"] == "operating"]
    late = ex023[-10:]
    levels = [h.level for r in late for h in rules.evaluate(r, provider.get("CAT-336", "excavator"))]
    assert levels.count(rules.CRIT) >= 10
    early = ex023[:3]
    assert all(not rules.evaluate(r, provider.get("CAT-336", "excavator")) for r in early)


def test_pipeline_flags_only_ex023_in_its_zone(aws, thresholds, settings, no_model, sqs):
    """Capas 1+2 completas sobre la zona norte del seed: solo EX-023 (degradación) emite AnomalyDetected."""
    norte = [m for m in build_fleet() if m.zone == "norte"]
    cfg = dataclasses.replace(settings, warmup_readings=20)
    processor = Processor(cfg, aws["repo"], thresholds, no_model, clock=lambda: T0 + timedelta(hours=2))
    sim = FleetSimulator(norte, SCENARIOS["degradacion"].effect, {"EX-023"}, started_at=T0, seed=5, speedup=60)
    for i in range(40):
        processor.handle(sqs(sim.tick(T0 + timedelta(minutes=i))))

    emitted = [json.loads(e["Detail"])["data"]["machine_id"] for e in aws["events"].entries]
    assert "EX-023" in emitted
    assert len(set(emitted) - {"EX-023"}) <= 1, emitted  # a lo sumo un falso positivo aislado en 920 lecturas
