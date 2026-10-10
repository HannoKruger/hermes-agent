"""The homelab HEALTHCHECK script fails exactly when the gateway heartbeat is stale."""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "docker" / "homelab-healthcheck.sh"


def run_healthcheck(hermes_home: Path, **extra_env: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HERMES_HOME": str(hermes_home), **extra_env}
    return subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=10)


def write_heartbeat(hermes_home: Path, age_seconds: float) -> None:
    heartbeat = hermes_home / "state" / "gateway.heartbeat"
    heartbeat.parent.mkdir(parents=True, exist_ok=True)
    heartbeat.write_text("{}")
    modified_at = time.time() - age_seconds
    os.utime(heartbeat, (modified_at, modified_at))


def test_fresh_heartbeat_is_healthy(tmp_path):
    write_heartbeat(tmp_path, age_seconds=5)
    assert run_healthcheck(tmp_path).returncode == 0


def test_stale_heartbeat_is_unhealthy(tmp_path):
    write_heartbeat(tmp_path, age_seconds=300)
    result = run_healthcheck(tmp_path)
    assert result.returncode == 1
    assert "heartbeat is" in result.stderr


def test_missing_heartbeat_is_unhealthy(tmp_path):
    result = run_healthcheck(tmp_path)
    assert result.returncode == 1
    assert "missing" in result.stderr


@pytest.mark.parametrize("age_seconds, expected_exit", [(100, 0), (200, 1)])
def test_age_limit_is_configurable(tmp_path, age_seconds, expected_exit):
    write_heartbeat(tmp_path, age_seconds=age_seconds)
    result = run_healthcheck(tmp_path, HERMES_HEALTHCHECK_MAX_AGE_SECONDS="150")
    assert result.returncode == expected_exit
