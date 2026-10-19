"""Isolated CI entry: execute trusted harness code, inspect candidate commits as data.

python -I -X utf8 <trusted>/kernel/team_admission.py --candidate <candidate>
    --base <sha> --head <sha>
python -I -X utf8 <trusted>/kernel/team_admission.py --candidate <candidate> --reconcile-all

The integration credential belongs only in this trusted process. Candidate code,
its Python profile and its sitecustomize are never imported by this entry point.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trusted team admission against a separate candidate checkout")
    parser.add_argument("--candidate", type=Path, required=True)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--base", help="Full base commit from the trusted CI event")
    operation.add_argument("--reconcile-all", action="store_true")
    parser.add_argument("--head", help="Full expected candidate commit from the trusted CI event")
    args = parser.parse_args(argv)
    if bool(args.base) != bool(args.head):
        parser.error("--base and --head must be supplied together")
    return args


def _trusted_modules():
    """Select only the entry's checkout, ignoring project-root overrides from a worker."""
    if not sys.flags.isolated:
        raise ValueError("Trusted admission requires Python -I")
    trusted_root = Path(__file__).resolve().parents[1]
    if not (trusted_root / "harness_profile.py").is_file():
        raise ValueError("Trusted checkout has no harness profile")
    os.environ.pop("HARNESS_ROOT", None)
    sys.path.insert(0, str(trusted_root))
    from kernel import profile, team_git

    return profile, team_git


def _candidate(args: argparse.Namespace, team_git) -> Path:
    """Bind the proof to the exact clean checkout the CI event names."""
    from kernel.team_resources import commit_sha

    root = args.candidate.resolve(strict=True)
    if not root.is_dir() or Path(team_git.git_value(root, "rev-parse", "--show-toplevel")).resolve() != root:
        raise ValueError("--candidate must name the root of a Git checkout")
    actual = team_git.git_value(root, "rev-parse", "--verify", "HEAD^{commit}")
    if not args.reconcile_all:
        expected = commit_sha({"head_sha": args.head}, "head_sha")
        commit_sha({"base_sha": args.base}, "base_sha")
        if actual != expected:
            raise ValueError("Candidate HEAD differs from the expected CI commit")
    dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", "--"], cwd=root,
                           capture_output=True, timeout=60)
    if dirty.returncode:
        raise ValueError("Candidate checkout has modified tracked files or cannot be inspected")
    return root


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        profile, team_git = _trusted_modules()
        if not profile.TEAM:
            print(json.dumps({"enabled": False, "source": "trusted-profile"}))
            return 0
        if profile.MERGE_FLOW != "pr":
            raise ValueError("Trusted TEAM configuration requires MERGE_FLOW='pr'")
        root = _candidate(args, team_git)
        result = team_git.reconcile_all(root) if args.reconcile_all else team_git.check(root, args.base, args.head)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        print(f"[TEAM] Trusted admission failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
