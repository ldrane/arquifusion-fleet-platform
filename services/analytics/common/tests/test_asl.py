"""Validación estructural de las definiciones ASL (sin AWS)."""

import json
import re
from pathlib import Path

import pytest

SFN_DIR = Path(__file__).parents[2] / "sfn"
PLACEHOLDER = re.compile(r"\$\{(\w+)\}")
EXPECTED_VARS = {
    "analisis_diario.asl.json": {
        "sql_daily_stats",
        "workgroup",
        "database",
        "fn_preventivo",
        "fn_repuestos",
        "fn_combustible",
        "fn_productividad",
        "fn_kpis_report",
    },
    "reentrenamiento.asl.json": {
        "active_version_param",
        "sql_training",
        "workgroup",
        "database",
        "fn_retrain",
        "fn_promote",
    },
}


def walk_states(states: dict):
    for name, state in states.items():
        yield name, state, states
        for branch in state.get("Branches", []):
            yield from walk_states(branch["States"])


@pytest.mark.parametrize("file", sorted(EXPECTED_VARS))
def test_asl_is_valid_and_consistent(file):
    raw = (SFN_DIR / file).read_text()
    assert set(PLACEHOLDER.findall(raw)) == EXPECTED_VARS[file]
    definition = json.loads(raw)
    assert definition["StartAt"] in definition["States"]
    for name, state, scope in walk_states(definition["States"]):
        targets = [state.get("Next"), state.get("Default")]
        targets += [c["Next"] for c in state.get("Choices", []) + state.get("Catch", [])]
        for target in filter(None, targets):
            assert target in scope, f"{name} apunta a {target}, que no existe"
        if state["Type"] == "Task":
            assert state.get("Retry") or "ssm" in state["Resource"], f"{name} sin Retry"
            assert "TimeoutSeconds" in state or "ssm" in state["Resource"] or name == "Promover"


def test_daily_runs_four_branches_then_report():
    states = json.loads((SFN_DIR / "analisis_diario.asl.json").read_text())["States"]
    assert len(states["Ramas"]["Branches"]) == 4
    assert states["Ramas"]["Next"] == "KpisYReporte"


SQL_FILES = {
    "analisis_diario.asl.json": (
        "sql_daily_stats",
        SFN_DIR.parent / "common/analytics_common/sql/daily_machine_stats.sql",
    ),
    "reentrenamiento.asl.json": ("sql_training", SFN_DIR.parent / "retrain/training.sql"),
}


@pytest.mark.parametrize("file", sorted(SQL_FILES))
def test_rendered_definition_is_valid_json(file):
    """Imita `templatefile` + `trimprefix(jsonencode(sql))` de Terraform: el JSON resultante debe ser válido."""
    var, sql_path = SQL_FILES[file]
    sql = sql_path.read_text()
    values = {name: "x" for name in EXPECTED_VARS[file]}
    values[var] = json.dumps(sql)[1:-1]
    rendered = PLACEHOLDER.sub(lambda m: values[m.group(1)], (SFN_DIR / file).read_text())
    states = json.loads(rendered)["States"]
    task = "EstadisticasDiarias" if var == "sql_daily_stats" else "ExtraerDatos"
    assert states[task]["Parameters"]["QueryString"] == sql


@pytest.mark.parametrize(
    "sql", [Path(__file__).parents[1] / "analytics_common/sql/daily_machine_stats.sql",
            Path(__file__).parents[2] / "retrain/training.sql"]
)
def test_sql_filters_injected_operation_partition(sql):
    """#10: `operation_id` tiene proyección `injected`; sin filtro de igualdad Athena falla."""
    assert "operation_id = 'OP-01'" in sql.read_text()
