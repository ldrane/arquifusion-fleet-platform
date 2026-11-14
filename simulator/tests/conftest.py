"""Fixtures compartidas de los tests del simulador."""

from pathlib import Path

import pytest
import yaml

from simulator.fleet import build_fleet

OPENAPI = Path(__file__).resolve().parents[2] / "contracts/openapi.yaml"


@pytest.fixture(scope="session")
def fleet():
    return build_fleet(42)


@pytest.fixture(scope="session")
def schemas() -> dict:
    return yaml.safe_load(OPENAPI.read_text())["components"]["schemas"]
