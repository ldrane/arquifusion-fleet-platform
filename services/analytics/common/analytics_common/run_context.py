"""Contexto de una ejecución de Step Functions recibido por cada Lambda de analítica."""

from dataclasses import dataclass
from datetime import UTC, date, datetime


@dataclass(frozen=True)
class RunContext:
    query_execution_id: str | None
    correlation_id: str
    run_at: datetime

    @property
    def today(self) -> date:
        return self.run_at.date()

    @property
    def run_at_iso(self) -> str:
        return self.run_at.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_event(event: dict) -> RunContext:
    """Evento: `{"query_execution_id", "correlation_id", "run_at"}`; `run_at` es `$$.Execution.StartTime`."""
    raw = event.get("run_at")
    run_at = datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else datetime.now(UTC)
    return RunContext(
        query_execution_id=event.get("query_execution_id"),
        correlation_id=event.get("correlation_id") or "analisis-diario",
        run_at=run_at.astimezone(UTC),
    )
