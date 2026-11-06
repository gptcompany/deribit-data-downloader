"""Hardening of the shipped systemd units (parsed, not grepped)."""

import configparser
from pathlib import Path

import pytest

UNIT_DIR = Path(__file__).resolve().parent.parent / "deploy" / "systemd"


def _service(name: str) -> configparser.ConfigParser:
    # systemd allows repeated keys (Environment=): strict=False keeps the last.
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read(UNIT_DIR / name, encoding="utf-8")
    return parser


@pytest.mark.parametrize("unit", ["deribit-sync.service", "deribit-sync-metrics.service"])
def test_service_runs_unprivileged(unit: str) -> None:
    # The unit executes a .venv binary that user sam can modify: running as
    # root would be a local privilege escalation.
    assert _service(unit)["Service"].get("User") == "sam"
