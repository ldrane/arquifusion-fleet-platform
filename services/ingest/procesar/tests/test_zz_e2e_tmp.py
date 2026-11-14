import sys, json, dataclasses
from pathlib import Path
sys.path.insert(0, "/home/sircloudz/Cloud/hackathon/arquifusion-fleet-platform")
sys.path.insert(0, "/home/sircloudz/Cloud/hackathon/arquifusion-fleet-platform/services/ingest/procesar/tests")
from datetime import timedelta
from collections import Counter
from conftest import SETTINGS, NoModel, sqs_event
from service import Processor
from simulator.fleet import build_fleet
from simulator.generator import FleetSimulator
from simulator.scenarios import SCENARIOS
from test_fleet_nominal import T0

def test_e2e(aws, thresholds):
    s = dataclasses.replace(SETTINGS, warmup_readings=20)
    p = Processor(s, aws["repo"], thresholds, NoModel(), clock=lambda: T0 + timedelta(hours=2))
    sim = FleetSimulator(build_fleet(), SCENARIOS["degradacion"].effect, {"EX-023"}, started_at=T0, seed=3, speedup=60)
    for i in range(60):
        rs = sim.tick(T0 + timedelta(minutes=i))
        p.handle(sqs_event(rs[:50], rs[50:]))
    ev = [json.loads(e["Detail"])["data"] for e in aws["events"].entries]
    an = aws["ddb"].Table(s.table_anomalies).scan()["Items"]
    print("\nEVENTS", [(e["machine_id"], e["severity"]) for e in ev])
    print("ANOM", Counter(a["machine_id"] for a in an))
