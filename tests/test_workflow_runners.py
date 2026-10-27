import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "check_workflow_runners", Path(__file__).parents[1] / "scripts/check_workflow_runners.py"
)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def test_docker_action_on_generic_runner_fails(monkeypatch):
    monkeypatch.setattr(checker, "action_type", lambda uses: "docker")
    job = {"runs-on": "${{ vars.CI_RUNS_ON }}", "steps": [{"uses": "pypa/action@v1"}]}
    with pytest.raises(ValueError, match="Docker job"):
        checker.check_job(job)


def test_hosted_fallback_fails():
    job = {"runs-on": "${{ vars.CI_RUNS_ON || 'ubuntu-latest' }}", "steps": [{"run": "true"}]}
    with pytest.raises(ValueError, match="runner"):
        checker.check_job(job)


def test_docker_runner_passes():
    job = {"runs-on": ["self-hosted", "gbg-ci"], "steps": [{"run": "docker build ."}]}
    assert checker.check_job(job)[0] == ["run: docker"]


def test_unresolved_local_composite_action_is_docker(monkeypatch):
    def resolve(uses, origin=None):
        if origin:
            raise ValueError("unavailable generated action")
        return "composite"

    monkeypatch.setattr(checker, "action_type", resolve)
    reasons, _ = checker.check_steps([{"uses": "./generated"}], ("owner/repo", "v1"))
    assert reasons == ["action: ./generated (docker)"]
