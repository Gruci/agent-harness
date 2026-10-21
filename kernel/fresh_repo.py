"""kernel/fresh_repo.py — README 빠른 시작의 한 줄(`python -X utf8 harness_install.py --new`): clone 한 하네스를 내 프로젝트의 첫 커밋으로.

`rm -rf .git && git init && …` 는 bash 에서만 돈다 — PowerShell 5.1 은 `&&` 와 `rm -rf` 둘 다 실패했다. 이 명령은 어느 셸에서든
같다. 지우는 것은 원류에서 막 clone 한 이력뿐이다: origin 이 원류이고, 작업 트리가 깨끗하고, HEAD 가 받아 온 것과 같을 때만.
git 사용자 정보가 없으면 아무것도 바꾸기 전에 멈춘다 — 첫 커밋과 과업 끝내기가 커밋을 만든다.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from kernel import UPSTREAM, profile

COMMIT_MESSAGE = "init: dev-harness"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")


def missing_identity(root: Path) -> list[str]:
    """비어 있는 git 사용자 설정 이름(`user.name`·`user.email`)."""
    return [key for key in ("user.name", "user.email") if not _git(root, "config", key).stdout.strip()]


def _not_fresh(root: Path) -> str:
    """원류에서 막 clone 한 이력이 아니면 그 사유. 남의 이력을 지우지 않는 것이 이 명령의 유일한 위험 관리다."""
    origin = _git(root, "remote", "get-url", "origin").stdout.strip()
    if not origin or profile.repo_key(origin) != profile.repo_key(UPSTREAM):
        return "this folder's git history is not a fresh clone of the harness — run `python -X utf8 harness_install.py` without --new"
    if _git(root, "status", "--porcelain").stdout.strip():
        return "there are uncommitted changes — --new only re-initializes an untouched clone"
    ahead = _git(root, "rev-list", "--count", "@{upstream}..HEAD")
    if ahead.returncode or ahead.stdout.strip() != "0":
        return "this clone has commits of its own — --new only re-initializes an untouched clone"
    return ""


def _writable(func, path, _info) -> None:   # shutil.rmtree 오류 처리기 서식 — Windows 의 읽기 전용 pack 파일
    os.chmod(path, stat.S_IWRITE)
    func(path)


def prepare(root: Path) -> int:
    """원류 이력을 지우고 새 저장소를 만든다. 0 이면 이어서 설치하고 `commit` 한다."""
    if (root / ".git").exists():
        why = _not_fresh(root)
        if why:
            print(f"[NEW] {why}")
            return 2
    missing = missing_identity(root)
    if missing:
        print(f"[NEW] git does not know who you are ({', '.join(missing)} unset) — nothing was changed. Run once:")
        print('    git config --global user.name "Your Name"')
        print('    git config --global user.email "you@example.com"')
        print("then run this command again.")
        return 2
    if (root / ".git").exists():
        handler = {"onexc": _writable} if sys.version_info >= (3, 12) else {"onerror": _writable}
        shutil.rmtree(root / ".git", **handler)   # type: ignore[arg-type]  # 3.12 이전은 onerror 만 받는다
    done = _git(root, "init", "-q")
    if done.returncode:
        print(f"[NEW] git init failed — {done.stderr.strip()[:300]}")
        return 2
    print("[NEW] Started a fresh git history for this project (the harness's own history was removed).")
    return 0


def commit(root: Path) -> int:
    """설치가 만든 파일까지 담아 첫 커밋을 만든다."""
    _git(root, "add", "-A")
    done = _git(root, "commit", "-q", "-m", COMMIT_MESSAGE)
    if done.returncode:
        print(f"[NEW] first commit failed — {(done.stderr or done.stdout).strip()[:300]}")
        return 2
    print(f"[NEW] First commit created ({COMMIT_MESSAGE}). Next: open Claude Code here and say \"set up the harness\".")
    return 0
