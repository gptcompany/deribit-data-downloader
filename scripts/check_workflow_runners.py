#!/usr/bin/env python3
"""Check workflow runner assignments; requires PyYAML and authenticated gh."""

import functools
import subprocess
from typing import Literal
import sys
from pathlib import Path
from urllib.parse import quote

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictStr, TypeAdapter

ROOT = Path(__file__).resolve().parents[1]
GENERIC = "${{ vars.CI_RUNS_ON }}"
# F-488: no self-hosted runner can run Docker for PR jobs (gbg-ci also matches sg-ci, which has none), so Docker
# jobs declare a hosted fallback. The form is admitted only for the jobs in DOCKER_JOBS_FILE: recognizing Docker
# from step text is a blocklist that any new spelling bypasses.
DOCKER_EXPR = '${{ fromJSON(vars.CI_DOCKER_RUNS_ON || \'["ubuntu-latest"]\') }}'
DOCKER_JOBS_FILE = ROOT / ".github/docker-jobs.json"
# F-491: the org runner group holding sg-ci and dell-ci excludes public repositories, so a public repository job on a
# self-hosted selector or on CI_RUNS_ON stays queued forever without an error; public repositories get free hosted
# minutes instead. The visibility is declared in a versioned file, not read at runtime.
POLICY_NAME = ".github/runner-policy.json"
PUBLIC_RUNNER = "ubuntu-latest"
# Job-level keys from the GitHub Actions workflow syntax; anything else fails closed.
JOB_KEYS = {
    "name", "permissions", "needs", "if", "runs-on", "snapshot", "environment", "concurrency", "outputs", "env",
    "defaults", "steps", "timeout-minutes", "strategy", "continue-on-error", "container", "services", "uses", "with",
    "secrets",
}
LOCAL_PREFIX = "./.github/workflows/"


class RunnerPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    visibility: Literal["public", "private"]


def visibility(path):
    return RunnerPolicy.model_validate_json(path.read_bytes()).visibility


class DockerJob(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    workflow: StrictStr = Field(min_length=1)
    job: StrictStr = Field(min_length=1)


def docker_jobs(path=DOCKER_JOBS_FILE):
    """Load the versioned allowlist of jobs that may use the Docker runner form."""
    entries = TypeAdapter(list[DockerJob]).validate_json(path.read_bytes())
    keys = {(entry.workflow, entry.job) for entry in entries}
    if len(keys) != len(entries):
        raise ValueError(f"{path.name}: duplicate entries")
    return keys


@functools.lru_cache(maxsize=None)
def action_type(uses, origin=None):
    if uses.startswith("docker://"):
        return "docker"
    if uses.startswith("./") and origin:
        uses = f"{origin[0]}/{uses[2:]}@{origin[1]}"
    if uses.startswith("./") or "@" not in uses:
        raise ValueError(f"unsupported action reference: {uses}")
    name, ref = uses.rsplit("@", 1)
    parts = name.split("/")
    if len(parts) < 2 or not all(parts) or not ref:
        raise ValueError(f"invalid action reference: {uses}")
    prefix = f"repos/{parts[0]}/{parts[1]}/contents/"
    directory = "/".join(parts[2:])
    for filename in ("action.yml", "action.yaml"):
        path = "/".join(filter(None, (directory, filename)))
        endpoint = f"{prefix}{path}?ref={quote(ref, safe='')}"
        result = subprocess.run(
            ["gh", "api", "-H", "Accept: application/vnd.github.raw+json", endpoint],
            capture_output=True, text=True, check=False,
        )
        if result.returncode == 0:
            break
    else:
        raise ValueError(f"cannot read action metadata: {uses}")
    metadata = yaml.safe_load(result.stdout)
    if not isinstance(metadata, dict) or not isinstance(metadata.get("runs"), dict):
        raise ValueError(f"invalid action metadata: {uses}")
    runs = metadata["runs"]
    kind = runs.get("using")
    if kind == "docker":
        return "docker"
    if kind in ("node12", "node16", "node20", "node24"):
        return "node"
    if kind == "composite":
        reasons, _ = check_steps(runs.get("steps"), ("/".join(parts[:2]), ref))
        return "composite (Docker: " + ", ".join(reasons) + ")" if reasons else "composite"
    raise ValueError(f"unknown action runtime for {uses}: {kind}")


def check_steps(steps, origin=None):
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps must be a nonempty list")
    reasons, actions = [], []
    for step in steps:
        if not isinstance(step, dict) or ("uses" in step) == ("run" in step):
            raise ValueError("step must contain exactly one of uses or run")
        if "uses" in step:
            uses = step["uses"]
            if not isinstance(uses, str):
                raise ValueError("action reference must be a string")
            try:
                kind = action_type(uses, origin) if origin else action_type(uses)
            except ValueError:
                if not (origin and uses.startswith("./")):
                    raise
                kind = "docker"  # An unresolved local composite action may be generated.
            actions.append((uses, kind))
            if kind == "docker" or kind.startswith("composite (Docker:") or uses.startswith("docker/"):
                reasons.append(f"action: {uses} ({kind})")
        elif not isinstance(step["run"], str):
            raise ValueError("run must be a string")
    return reasons, actions


def check_job(job, listed=False):
    """Structural Docker use (reasons) only flags an unlisted job; it never admits the Docker form."""
    if not isinstance(job, dict) or "runs-on" not in job:
        raise ValueError("job must have a runs-on selector")
    runner = job["runs-on"]
    docker_runner = runner == DOCKER_EXPR
    if not docker_runner and runner != GENERIC:
        raise ValueError(f"unverified or hosted runner: {runner}")
    reasons, actions = check_steps(job.get("steps"))
    for field in ("container", "services"):
        if field in job:
            if not isinstance(job[field], (str, dict)) or not job[field]:
                raise ValueError(f"invalid {field}")
            reasons.insert(0, field)
    if docker_runner and not listed:
        raise ValueError(f"Docker runner form outside {DOCKER_JOBS_FILE.name}")
    if listed and not docker_runner:
        raise ValueError(f"listed in {DOCKER_JOBS_FILE.name} without the Docker runner form")
    if reasons and not listed:
        raise ValueError(f"Docker job not listed in {DOCKER_JOBS_FILE.name}: {', '.join(reasons)}")
    return reasons, actions


def check_public_job(job, local_workflows):
    """A reusable workflow is admitted only as a local file that this check also analyzes (F-492: an external one,
    gptcompany/.github included, can route a public repository job to a self-hosted runner)."""
    if not isinstance(job, dict):
        raise ValueError("job must be a mapping")
    unknown = set(job) - JOB_KEYS
    if unknown:
        raise ValueError(f"unknown job keys: {sorted(unknown)}")
    if "uses" in job:
        uses = job["uses"]
        if "runs-on" in job:
            raise ValueError("a reusable workflow call cannot have runs-on")
        if not isinstance(uses, str) or not uses.startswith(LOCAL_PREFIX) or uses[len(LOCAL_PREFIX):] not in local_workflows:
            raise ValueError(f"reusable workflow must be a local analyzed file {LOCAL_PREFIX}<file>, found {uses!r}")
        return f"uses={uses}"
    if job.get("runs-on") != PUBLIC_RUNNER:
        raise ValueError(f"public repository requires runs-on: {PUBLIC_RUNNER}")
    return f"runs-on={PUBLIC_RUNNER}"


def check_public(paths):
    """Public repository: every job runs on the literal hosted runner, and no Docker allowlist exists."""
    failed = DOCKER_JOBS_FILE.exists()
    if failed:
        print(f"{DOCKER_JOBS_FILE.name} ERROR: the Docker runner form is not allowed in a public repository")
    local_workflows = {path.name for path in paths}
    for path in paths:
        workflow = yaml.safe_load(path.read_text())
        if not isinstance(workflow, dict) or not isinstance(workflow.get("jobs"), dict):
            raise ValueError(f"invalid workflow: {path}")
        for name, job in workflow["jobs"].items():
            try:
                print(f"{path.name}:{name} {check_public_job(job, local_workflows)} ok (public)")
            except ValueError as error:
                runner = job.get("runs-on") if isinstance(job, dict) else None
                print(f"{path.name}:{name} runs-on={runner} ERROR: {error}")
                failed = True
    return int(failed)


def main():
    paths = sorted((ROOT / ".github/workflows").glob("*.y*ml"))
    if not paths:
        raise ValueError("no workflows found")
    if visibility(ROOT / POLICY_NAME) == "public":
        return check_public(paths)
    failed = False
    allowed = docker_jobs()
    seen = set()
    for path in paths:
        workflow = yaml.safe_load(path.read_text())
        if not isinstance(workflow, dict) or not isinstance(workflow.get("jobs"), dict):
            raise ValueError(f"invalid workflow: {path}")
        for name, job in workflow["jobs"].items():
            seen.add((path.name, name))
            try:
                reasons, actions = check_job(job, (path.name, name) in allowed)
                print(f"{path.name}:{name} runs-on={job['runs-on']} docker={bool(reasons)} reasons={reasons} actions={actions}")
            except (ValueError, yaml.YAMLError) as error:
                print(f"{path.name}:{name} runs-on={job.get('runs-on')} ERROR: {error}")
                failed = True
    for workflow_name, job_name in sorted(allowed - seen):
        print(f"{DOCKER_JOBS_FILE.name}: {workflow_name}:{job_name} ERROR: listed job does not exist")
        failed = True
    return int(failed)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
