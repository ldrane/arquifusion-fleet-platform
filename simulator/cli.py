"""CLI del simulador: `python -m simulator {stream,history,fleet}` (RF-01, requerimientos §5.6)."""

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from simulator.fleet import ZONES, build_fleet, select, to_dict
from simulator.generator import FleetSimulator
from simulator.history import generate_history, upload
from simulator.scenarios import SCENARIOS
from simulator.sender import TelemetrySender, batches


def _days(value: str) -> int:
    """Acepta `90` o `90d`."""
    days = int(value.removesuffix("d"))
    if days < 1:
        raise argparse.ArgumentTypeError("debe ser al menos 1 día")
    return days


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m simulator", description="Simulador de flota ArquiFusion")
    parser.add_argument("--seed", type=int, default=42, help="semilla del ruido de las lecturas (default 42)")
    parser.add_argument(
        "--seed-dir", type=Path, default=None, help="carpeta de seeds (default contracts/fixtures/seed)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    stream = sub.add_parser("stream", help="envía telemetría en vivo a POST /telemetry")
    stream.add_argument("--api-url", default=os.environ.get("SIMULATOR_API_URL"))
    stream.add_argument("--api-key", default=os.environ.get("SIMULATOR_API_KEY"))
    stream.add_argument("--scenario", choices=sorted(SCENARIOS), default="normal")
    stream.add_argument("--machine", action="append", help="máquina afectada (repetible), p. ej. EX-001")
    stream.add_argument("--zone", choices=sorted(ZONES), help="zona afectada por el escenario")
    stream.add_argument(
        "--rate",
        type=float,
        default=None,
        help="lecturas por máquina por minuto (default: 60 / expected_interval_s del seed = 1)",
    )
    stream.add_argument("--duration", type=float, default=0, help="minutos a simular; 0 = sin fin")
    stream.add_argument(
        "--speedup", type=float, default=60.0, help="aceleración del escenario (default 60: 1 min real = 1 h simulada)"
    )
    stream.add_argument("--dry-run", action="store_true", help="no envía: imprime los lotes como JSON")
    stream.add_argument("--out", type=Path, help="con --dry-run, guarda los lotes en este archivo JSONL")

    history = sub.add_parser("history", help="genera historial sintético Parquet para el data lake")
    history.add_argument("--days", type=_days, default=90, help="días de historial, p. ej. 90 o 90d")
    history.add_argument("--interval", type=int, default=15, help="minutos entre lecturas (default 15)")
    history.add_argument("--out", type=Path, default=Path("data/lake"))
    history.add_argument("--operation-id", default="OP-01")
    history.add_argument("--upload", metavar="S3_URI", help="sube el resultado a s3://bucket[/prefijo]")

    fleet = sub.add_parser("fleet", help="exporta la flota que simula (cargada de los seeds)")
    fleet.add_argument("--out", type=Path, help="archivo JSON de salida (default: stdout)")
    return parser


def resolve_targets(fleet, scenario, machines, zone):
    targets = select(fleet, machines, zone) or scenario.default_targets(fleet)
    if scenario.name != "normal" and not targets:
        raise SystemExit("Ninguna máquina coincide con --machine/--zone")
    return targets


def run_stream(args, fleet) -> None:
    if not args.dry_run and not (args.api_url and args.api_key):
        raise SystemExit("Faltan --api-url/--api-key (o SIMULATOR_API_URL / SIMULATOR_API_KEY)")
    if args.dry_run and not args.duration:
        raise SystemExit("--dry-run requiere --duration (el reloj simulado no espera)")
    scenario = SCENARIOS[args.scenario]
    targets = resolve_targets(fleet, scenario, args.machine, args.zone)
    # Por defecto se envía al ritmo que espera heartbeat (expected_interval_s del seed, contratos.md §3).
    rate = args.rate or 60.0 / min(m.expected_interval_s for m in fleet)
    interval_s = 60.0 / rate
    # En --dry-run el reloj es simulado: los ticks se generan de inmediato, sin esperar en tiempo real.
    started_at = datetime.now(UTC)
    sim = FleetSimulator(
        fleet,
        scenario.effect,
        {m.machine_id for m in targets},
        started_at=started_at,
        seed=args.seed,
        speedup=args.speedup,
    )
    sender = None if args.dry_run else TelemetrySender(args.api_url, args.api_key)
    out = args.out.open("w") if args.out else sys.stdout
    total_ticks = int(args.duration * rate) if args.duration else None
    print(f"Escenario {scenario.name} sobre {[m.machine_id for m in targets]} cada {interval_s:.0f} s", file=sys.stderr)
    tick = 0
    try:
        while total_ticks is None or tick < total_ticks:
            started = time.monotonic()
            now = started_at + timedelta(seconds=tick * interval_s) if args.dry_run else datetime.now(UTC)
            readings = sim.tick(now)
            if sender:
                ids = sender.send(readings)
                print(f"tick {tick}: {len(readings)} lecturas en {len(ids)} lotes", file=sys.stderr)
            else:
                for batch in batches(readings):
                    out.write(json.dumps({"readings": batch}, ensure_ascii=False) + "\n")
            tick += 1
            if not args.dry_run and (total_ticks is None or tick < total_ticks):
                time.sleep(max(0.0, interval_s - (time.monotonic() - started)))
    except KeyboardInterrupt:
        print("Detenido", file=sys.stderr)
    finally:
        if args.out:
            out.close()


def run_history(args, fleet) -> None:
    summary = generate_history(
        fleet, args.days, args.out, interval_min=args.interval, seed=args.seed, operation_id=args.operation_id
    )
    if args.upload:
        summary["uploaded_files"] = upload(args.out, args.upload)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def run_fleet(args, fleet) -> None:
    text = json.dumps([to_dict(m) for m in fleet], indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(text + "\n")
    else:
        print(text)


COMMANDS = {"stream": run_stream, "history": run_history, "fleet": run_fleet}


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    COMMANDS[args.command](args, build_fleet(args.seed_dir))
