import importlib.util
import json
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
    with pytest.raises(ValueError, match="not listed"):
        checker.check_job(job)


def test_hosted_fallback_fails():
    job = {"runs-on": "${{ vars.CI_RUNS_ON || 'ubuntu-latest' }}", "steps": [{"run": "true"}]}
    with pytest.raises(ValueError, match="runner"):
        checker.check_job(job)


DOCKER_FORM = """${{ fromJSON(vars.CI_DOCKER_RUNS_ON || '["ubuntu-latest"]') }}"""


def test_listed_docker_runner_passes():
    job = {"runs-on": DOCKER_FORM, "steps": [{"run": "uv run pytest"}]}
    assert checker.check_job(job, listed=True)[0] == []


@pytest.mark.parametrize("run", ["echo docker", "docker build ."])
def test_unlisted_docker_form_fails(run):
    # Review ccxt58-r1: a word in a step must never admit the Docker form.
    job = {"runs-on": DOCKER_FORM, "steps": [{"run": run}]}
    with pytest.raises(ValueError, match="outside"):
        checker.check_job(job)


def test_listed_job_with_generic_runner_fails():
    job = {"runs-on": "${{ vars.CI_RUNS_ON }}", "steps": [{"run": "true"}]}
    with pytest.raises(ValueError, match="without the Docker runner form"):
        checker.check_job(job, listed=True)


@pytest.mark.parametrize(
    "field", [{"services": {"db": {"image": "redis"}}}, {"container": "python:3.12"}]
)
def test_unlisted_structural_docker_fails(field):
    job = {"runs-on": "${{ vars.CI_RUNS_ON }}", "steps": [{"run": "true"}], **field}
    with pytest.raises(ValueError, match="not listed"):
        checker.check_job(job)


def test_docker_word_on_generic_runner_passes():
    job = {"runs-on": "${{ vars.CI_RUNS_ON }}", "steps": [{"run": "echo docker"}]}
    assert checker.check_job(job)[0] == []


def test_literal_gbg_ci_docker_runner_fails():
    # F-488: gbg-ci also matches sg-ci, which has no Docker.
    job = {"runs-on": ["self-hosted", "gbg-ci"], "steps": [{"run": "docker build ."}]}
    with pytest.raises(ValueError, match="runner"):
        checker.check_job(job)


def test_docker_namespace_action_counts_as_docker(monkeypatch):
    monkeypatch.setattr(checker, "action_type", lambda uses: "node")
    job = {"runs-on": "${{ vars.CI_RUNS_ON }}", "steps": [{"uses": "docker/build-push-action@v5"}]}
    with pytest.raises(ValueError, match="not listed"):
        checker.check_job(job)


def test_unresolved_local_composite_action_is_docker(monkeypatch):
    def resolve(uses, origin=None):
        if origin:
            raise ValueError("unavailable generated action")
        return "composite"

    monkeypatch.setattr(checker, "action_type", resolve)
    reasons, _ = checker.check_steps([{"uses": "./generated"}], ("owner/repo", "v1"))
    assert reasons == ["action: ./generated (docker)"]


ENTRY = {"workflow": "ci.yml", "job": "docker"}


@pytest.mark.parametrize(
    "text",
    [
        "{",
        json.dumps(ENTRY),
        json.dumps([{**ENTRY, "why": "x"}]),
        json.dumps([{**ENTRY, "job": 1}]),
        json.dumps([{**ENTRY, "workflow": ""}]),
        json.dumps([ENTRY, ENTRY]),
    ],
)
def test_invalid_allowlist_fails(tmp_path, text):
    path = tmp_path / "docker-jobs.json"
    path.write_text(text)
    with pytest.raises(ValueError):
        checker.docker_jobs(path)


def test_stale_allowlist_entry_fails(tmp_path, monkeypatch, capsys):
    workflows = tmp_path / ".github/workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        f"jobs:\n  docker:\n    runs-on: {DOCKER_FORM}\n    steps:\n      - run: true\n"
    )
    allowlist = tmp_path / ".github/docker-jobs.json"
    allowlist.write_text(json.dumps([ENTRY, {"workflow": "old.yml", "job": "gone"}]))
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(checker, "DOCKER_JOBS_FILE", allowlist)
    monkeypatch.setattr(checker.docker_jobs, "__defaults__", (allowlist,))
    assert checker.main() == 1
    out = capsys.readouterr().out
    assert "old.yml:gone ERROR: listed job does not exist" in out
    assert "ci.yml:docker runs-on=" in out
