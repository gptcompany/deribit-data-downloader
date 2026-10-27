#!/usr/bin/env python3
"""Check workflow runner assignments; requires PyYAML and authenticated gh."""

import functools
import shlex
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import yaml

ROOT = Path(__file__).resolve().parents[1]
GENERIC = "${{ vars.CI_RUNS_ON }}"
# F-488: no self-hosted runner can run Docker for PR jobs (gbg-ci also matches sg-ci, which has none), so Docker
# jobs declare a hosted fallback; the form is reserved for jobs that use Docker.
DOCKER_EXPR = '${{ fromJSON(vars.CI_DOCKER_RUNS_ON || \'["ubuntu-latest"]\') }}'


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
        else:
            run = step["run"]
            if not isinstance(run, str):
                raise ValueError("run must be a string")
            try:
                lexer = shlex.shlex(run, posix=True, punctuation_chars=True)
                lexer.whitespace_split = True
                tokens = list(lexer)
            except ValueError as error:
                raise ValueError(f"cannot parse run: {error}") from error
            if any(token.rsplit("/", 1)[-1] == "docker" for token in tokens):
                reasons.append("run: docker")
    return reasons, actions


def check_job(job):
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
    if reasons and not docker_runner:
        raise ValueError(f"Docker job requires CI_DOCKER_RUNS_ON: {', '.join(reasons)}")
    if docker_runner and not reasons:
        raise ValueError("CI_DOCKER_RUNS_ON is reserved for jobs that use Docker")
    return reasons, actions


def main():
    failed = False
    paths = sorted((ROOT / ".github/workflows").glob("*.y*ml"))
    if not paths:
        raise ValueError("no workflows found")
    for path in paths:
        workflow = yaml.safe_load(path.read_text())
        if not isinstance(workflow, dict) or not isinstance(workflow.get("jobs"), dict):
            raise ValueError(f"invalid workflow: {path}")
        for name, job in workflow["jobs"].items():
            try:
                reasons, actions = check_job(job)
                print(f"{path.name}:{name} runs-on={job['runs-on']} docker={bool(reasons)} reasons={reasons} actions={actions}")
            except (ValueError, yaml.YAMLError) as error:
                print(f"{path.name}:{name} runs-on={job.get('runs-on')} ERROR: {error}")
                failed = True
    return int(failed)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
