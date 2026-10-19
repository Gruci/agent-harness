"""Admit unprivileged workflow results using only protected code and Git object data.

Run this module from the default-branch checkout in an isolated Python process.
The candidate checkout supplies Git objects only; its Python, configuration and
artifacts are never imported or executed by this privileged process.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from kernel import profile, team_git
from kernel.team_client import decode_object
from kernel.team_resources import TeamError, commit_sha
from kernel.team_tasks import git_value

WORKFLOW = ".github/workflows/harness.yml"
STATUS = "harness-team-admission"
EVENTS = ("pull_request", "merge_group", "push")
MAX_EVENT, MAX_ARTIFACT = 1_048_576, 4096


def _object(path: Path, limit: int) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("Workflow metadata is missing, oversized or not a regular file")
    try:
        return decode_object(path.read_bytes())
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("Workflow metadata must be one finite JSON object") from exc


def _api(repository: str, endpoint: str, fields: dict | None = None) -> dict:
    command = ["gh", "api", "--method", "POST" if fields else "GET", f"repos/{repository}/{endpoint}"]
    for key, value in (fields or {}).items():
        command += ["-f", f"{key}={value}"]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=60)
    if result.returncode or len(result.stdout.encode("utf-8")) > MAX_EVENT:
        raise ValueError("GitHub could not confirm the workflow or publish its admission status")
    return decode_object(result.stdout.encode("utf-8"))


def _context(event: dict) -> tuple[str, dict]:
    repository, run = event.get("repository"), event.get("workflow_run")
    if not isinstance(repository, dict) or not isinstance(run, dict):
        raise ValueError("A workflow_run event is required")
    name = repository.get("full_name", "")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name):
        raise ValueError("Invalid workflow repository identity")
    if profile.repo_key(str(profile.TEAM["repository"])) != name.lower():
        raise ValueError("The source workflow belongs to another team repository")
    if os.environ.get("GITHUB_REPOSITORY", name).lower() != name.lower():
        raise ValueError("The source workflow differs from the executing repository")
    commit_sha(run, "head_sha")
    return name, run


def _validate_run(repository: str, event: dict, run: dict) -> None:
    identity = event["repository"]
    identifier = identity.get("id")
    if isinstance(identifier, bool) or not isinstance(identifier, int) or identifier <= 0:
        raise ValueError("The workflow repository has no provider identity")
    for key in ("repository", "head_repository"):
        source = run.get(key)
        if (not isinstance(source, dict) or source.get("id") != identifier
                or str(source.get("full_name", "")).lower() != repository.lower()):
            raise ValueError("Fork and cross-repository workflow results cannot attest team candidates")
    if run.get("conclusion") != "success" or run.get("event") not in EVENTS:
        raise ValueError("Admission requires a successful supported source workflow")
    if isinstance(run.get("id"), bool) or not isinstance(run.get("id"), int) or run["id"] <= 0:
        raise ValueError("The source workflow has no valid run identity")
    expected = _api(repository, "actions/workflows/harness.yml")
    if (expected.get("path") != WORKFLOW or expected.get("name") != "harness"
            or expected.get("id") != run.get("workflow_id")
            or str(run.get("path", "")).split("@", 1)[0] != WORKFLOW):
        raise ValueError("The source run is not the protected harness workflow")
    if run["event"] == "push" and run.get("head_branch") != identity.get("default_branch"):
        raise ValueError("Only an integration-branch push may reconcile team tasks")


def _fetch_commit(candidate: Path, sha: str) -> None:
    try:
        resolved = git_value(candidate, "rev-parse", "--verify", f"{sha}^{{commit}}")
    except ValueError:
        git_value(candidate, "fetch", "--quiet", "--no-tags", "origin", sha)
        resolved = git_value(candidate, "rev-parse", "--verify", f"{sha}^{{commit}}")
    if resolved != sha:
        raise ValueError("Workflow metadata does not identify a literal Git commit")


def _binding(candidate: Path, event: dict, run: dict, artifact: dict) -> tuple[str, str]:
    if set(artifact) != {"base_sha", "head_sha", "event"} or artifact["event"] != run["event"]:
        raise ValueError("Candidate artifact does not match its source event")
    base, head = commit_sha(artifact, "base_sha"), commit_sha(artifact, "head_sha")
    for sha in (base, head, run["head_sha"]):
        _fetch_commit(candidate, sha)
    if not team_git._ancestor(candidate, base, head) or not team_git._ancestor(candidate, run["head_sha"], head):
        raise ValueError("Candidate commits do not contain the reported base and source head")
    if run["event"] != "pull_request":
        if head != run["head_sha"]:
            raise ValueError("Queue and push artifacts must identify the exact source run SHA")
    else:
        requests = run.get("pull_requests", [])
        if not isinstance(requests, list) or len(requests) != 1:
            raise ValueError("A pull-request result requires one provider PR binding")
        request = requests[0]
        if (not isinstance(request, dict) or not isinstance(request.get("base"), dict)
                or not isinstance(request.get("head"), dict) or request["base"].get("sha") != base
                or request["head"].get("sha") != run["head_sha"]):
            raise ValueError("Candidate artifact differs from the provider PR base or head")
        if head != run["head_sha"]:
            parents = git_value(candidate, "rev-list", "--parents", "-n", "1", head).split()[1:]
            tree = git_value(candidate, "merge-tree", "--write-tree", base, run["head_sha"]).splitlines()[0]
            if parents != [base, run["head_sha"]] or tree != git_value(candidate, "rev-parse", f"{head}^{{tree}}"):
                raise ValueError("The PR artifact is not its exact deterministic test merge")
    return base, head


def _status(repository: str, run: dict, state: str) -> None:
    _api(repository, f"statuses/{run['head_sha']}", {"state": state, "context": STATUS,
         "description": "Trusted team admission passed" if state == "success" else "Trusted team admission failed"})


def admit(trusted: Path, candidate: Path, event_path: Path, artifact_path: Path) -> dict:
    """Validate data provenance, then attest the real frozen candidate or reconcile a push."""
    if not profile.TEAM:
        return {"enabled": False}
    event = _object(event_path, MAX_EVENT)
    repository, run = _context(event)
    if run.get("event") == "push" and run.get("head_branch") != event["repository"].get("default_branch"):
        return {"enabled": True, "ignored": "non-integration push"}
    try:
        _validate_run(repository, event, run)
        artifact = _object(artifact_path, MAX_ARTIFACT)
        base, head = _binding(candidate, event, run, artifact)
        policy = git_value(trusted, "rev-parse", f"HEAD:{WORKFLOW}")
        if policy != git_value(candidate, "rev-parse", f"{head}:{WORKFLOW}"):
            raise ValueError("The candidate changed protected workflow policy; update trusted policy before admission")
        if run["event"] == "push":
            target = event["repository"]["default_branch"]
            git_value(candidate, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/" + target)
            result = team_git.reconcile_all(candidate)
        else:
            result = team_git.check(candidate, base, head)
    except Exception:
        _status(repository, run, "failure")
        raise
    _status(repository, run, "success")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Admit an unprivileged source workflow using protected code")
    for name in ("trusted", "candidate", "event", "artifact"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.trusted.resolve() != Path(__file__).resolve().parents[1]:
            raise ValueError("The trusted checkout must contain the executing checker")
        if not sys.flags.isolated or os.environ.get("HARNESS_ROOT"):
            raise ValueError("Use python -I and clear HARNESS_ROOT before importing the trusted checker")
        result = admit(args.trusted, args.candidate, args.event, args.artifact)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (TeamError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"[TEAM] Trusted admission failed: {exc}")
        return 1
