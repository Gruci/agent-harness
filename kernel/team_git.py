"""Trusted Git admission for team submissions and reconciliation after remote integration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

from kernel import profile
from kernel.isolation import GENERATED
from kernel.team_tasks import changed_paths, check_repository, git_value
from kernel.team_store import TeamError


def _client(integration: bool = False):
    from kernel.team_client import Client

    config = dict(profile.TEAM)
    if integration and os.environ.get("HARNESS_TEAM_CI_TOKEN"):
        config["token_env"] = "HARNESS_TEAM_CI_TOKEN"
    return Client(config)


def _ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(["git", "merge-base", "--is-ancestor", ancestor, descendant], cwd=root,
                            capture_output=True, timeout=30)
    return result.returncode == 0


def _tasks(connection) -> list[dict]:
    result, cursor = [], ""
    while True:
        page = connection.request("list", {"cursor": cursor})
        result.extend(page["tasks"])
        cursor = page.get("next_cursor", "")
        if not cursor:
            return result


def _policy(_candidate: Path) -> str:
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    paths = [path for folder in (root / "kernel", root / "profiles", root / ".github/workflows")
             if folder.exists() for path in folder.rglob("*") if path.suffix in (".py", ".yml", ".yaml")]
    paths.append(root / "harness_profile.py")
    for path in sorted(paths):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def _expected_tree(root: Path, base: str, head: str, tasks: list[dict]) -> str:
    """Reconstruct frozen submissions; path overlap alone cannot exclude extra unsubmitted edits."""
    history = git_value(root, "rev-list", "--topo-order", "--reverse", f"{base}..{head}").splitlines()
    positions = {sha: index for index, sha in enumerate(history)}
    current = base
    for task in sorted(tasks, key=lambda item: positions.get(item["head_sha"], -1)):
        tree = git_value(root, "merge-tree", "--write-tree", current, task["head_sha"]).splitlines()[0]
        current = git_value(root, "-c", "user.name=Harness integration", "-c", "user.email=harness@localhost",
                            "commit-tree", tree, "-p", current, "-p", task["head_sha"], "-m", "Team candidate")
    return git_value(root, "rev-parse", f"{current}^{{tree}}")


def check(root: Path, base: str, head: str) -> dict:
    """Run in trusted CI after required tests; inspect real commits, never a worker-supplied path list."""
    if not profile.TEAM:
        return {"enabled": False}
    check_repository(root)
    base = git_value(root, "rev-parse", "--verify", f"{base}^{{commit}}")
    head = git_value(root, "rev-parse", "--verify", f"{head}^{{commit}}")
    connection = _client(integration=True)
    tasks = _tasks(connection)
    selected = [task for task in tasks if task["state"] in ("submitted", "verified")
                and _ancestor(root, task["head_sha"], head) and not _ancestor(root, task["head_sha"], base)]
    if not selected:
        raise ValueError("No current team submissions cover this integration candidate")
    if _expected_tree(root, base, head, selected) != git_value(root, "rev-parse", f"{head}^{{tree}}"):
        raise ValueError("Candidate tree differs from the exact frozen team submissions")
    covered: set[str] = set()
    inspected = []
    for task in selected:
        paths = changed_paths(root, task["base_sha"], task["head_sha"])
        covered.update(paths)
        inspected.append((task, paths))
    outside = set(changed_paths(root, base, head)) - covered
    if outside:
        raise ValueError("Candidate contains changes without a current team submission: " + ", ".join(sorted(outside)))
    proof = {"tested_sha": head, "tree_sha": git_value(root, "rev-parse", f"{head}^{{tree}}"),
             "policy_digest": _policy(root)}
    for task, paths in inspected:
        connection.request("verify", {"task_id": task["task_id"], "epoch": task["epoch"],
                                      "base_sha": task["base_sha"], "head_sha": task["head_sha"],
                                      "changed_paths": paths, "proof": proof})
    return {"enabled": True, "tested_sha": head, "tasks": [task["task_id"] for task in selected]}


def _pull_request(root: Path, task: dict) -> dict:
    done = subprocess.run(["gh", "pr", "view", task["branch"], "--json", "state,headRefOid,mergeCommit,baseRefName"],
                          cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=60)
    if done.returncode:
        raise ValueError("Could not confirm the submitted pull request with GitHub")
    result = json.loads(done.stdout)
    if result.get("state") != "MERGED" or result.get("headRefOid") != task["head_sha"]:
        raise ValueError("The exact submitted commit has not been merged")
    return result


def reconcile(root: Path, task_id: str) -> dict:
    """An integration-role credential and provider merge evidence are required to release reservations."""
    check_repository(root)
    connection = _client(integration=True)
    task = connection.request("status", {"task_id": task_id})
    if task["state"] == "merged":
        return task
    result = _pull_request(root, task)
    target = git_value(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").removeprefix("origin/")
    if result.get("baseRefName") != target:
        raise ValueError("The pull request was not merged into the repository integration branch")
    merge_sha = (result.get("mergeCommit") or {}).get("oid")
    if not merge_sha:
        raise ValueError("GitHub did not return a merge commit")
    git_value(root, "fetch", "--quiet", "origin", result["baseRefName"])
    if not _ancestor(root, merge_sha, f"origin/{result['baseRefName']}"):
        raise ValueError("The confirmed merge is not present in the remote target branch")
    return connection.request("merged", {"task_id": task_id, "epoch": task["epoch"],
                                         "base_sha": task["base_sha"], "head_sha": task["head_sha"],
                                         "merge_sha": merge_sha})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trusted team admission and merge reconciliation")
    commands = parser.add_subparsers(dest="command", required=True)
    checker = commands.add_parser("check")
    checker.add_argument("--base", required=True)
    checker.add_argument("--head", default="HEAD")
    merged = commands.add_parser("reconcile")
    merged.add_argument("--task-id", required=True)
    commands.add_parser("reconcile-all")
    args = parser.parse_args(argv)
    try:
        root = Path.cwd()
        if args.command == "check":
            result = check(root, args.base, args.head)
        elif args.command == "reconcile":
            result = reconcile(root, args.task_id)
        else:
            result = reconcile_all(root)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (TeamError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"[TEAM] {exc}")
        return 1


def reconcile_all(root: Path) -> dict:
    if not profile.TEAM:
        return {"enabled": False}
    tasks = _tasks(_client(integration=True))
    results = []
    for task in tasks:
        if task["state"] != "verified":
            continue
        try:
            results.append(reconcile(root, task["task_id"])["task_id"])
        except ValueError:
            continue  # Other queued candidates may not have merged yet; their reservations remain held.
    return {"enabled": True, "merged": results}


if __name__ == "__main__":
    raise SystemExit(main())
