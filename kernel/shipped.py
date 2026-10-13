"""kernel/shipped.py — clone 이 싣고 온 하네스 레포 상태 정리.

README 흐름(clone → `.git` 삭제 → 첫 커밋)으로 가져온 레포에는 하네스 레포 **자신의** 것이 딸려 온다 —
자체 테스트·참조 예제·원류 전용 로컬 게이트, 하네스 레포 세션의 관찰 기록, 하네스 레포의 정비 기록.
`LANG` 을 고르는 순간 `tests/` 가 제품 코드로 잡혀 위반 수백 건이 나고, 정비 알림은 남의 날짜로 뜬다.

설치가 하네스 자신의 프로파일을 교체하는 그 한 번에 여기의 `reset` 을 부른다. 지우는 기준은 **첫 커밋과 blob 이 같고
작업 트리에서 안 바뀐 파일** 이다. 첫 커밋이 곧 실어 보낸 상태라 상태 파일이 더 필요 없다. 바뀐 파일과 새 파일은 남기고
이름을 알린다. 첫 커밋을 하나로 특정할 수 없으면(원류 이력을 통째로 받은 clone) 아무것도 지우지 않는다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

TRACE = "harness_trace.jsonl"
MAINTENANCE = "harness_maintenance.json"
# 하네스 레포에서만 의미가 있는 파일. 원류 CI 가 이 파일들로 하네스를 검증한다. `harness_gates/edit_surface.py` 는 남는다 —
# 새 프로젝트도 첫날부터 편집 표면 래칫을 켠다(profiles/_template.py LOCAL_GATES).
HARNESS_REPO_ONLY = ("tests/", "examples/", "harness_gates/archive_not_shipped.py",
                     "harness_gates/stack_words.py", "harness_gates/english_output.py")


def _git(root: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.decode("utf-8", "replace") if done.returncode == 0 else None


def _blobs(root: Path, rev: str) -> dict[str, str]:
    """`rev` 에서 하네스 레포 전용 경로 아래 (경로 → blob). `-z` 라 한글·공백 경로도 그대로다."""
    out = _git(root, "ls-tree", "-r", "-z", rev, "--", *HARNESS_REPO_ONLY) or ""
    found: dict[str, str] = {}
    for record in out.split("\0"):
        meta, _tab, rel = record.partition("\t")
        if rel and len(meta.split()) == 3:
            found[rel] = meta.split()[2]
    return found


def _prune(root: Path, rel: str) -> None:
    """지운 파일 위의 빈 디렉터리를 레포 루트까지 정리한다."""
    parent = (root / rel).parent
    while parent != root and parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent


def repo_only_files(root: Path) -> tuple[list[str], list[str]]:
    """(지울 파일, 남길 파일). 첫 커밋 이후 그대로인 하네스 레포 전용 파일만 지울 대상이다."""
    roots = (_git(root, "rev-list", "--max-parents=0", "HEAD") or "").split()
    head = _blobs(root, "HEAD")
    if len(roots) != 1:
        return [], sorted(head)                   # 첫 커밋을 하나로 특정할 수 없으면 아무것도 지우지 않는다
    first = _blobs(root, roots[0])
    changed = set((_git(root, "diff", "--name-only", "-z", "HEAD", "--", *HARNESS_REPO_ONLY) or "").split("\0"))
    remove = sorted(rel for rel, blob in head.items() if first.get(rel) == blob and rel not in changed)
    return remove, sorted(set(head) - set(remove))


def reset(root: Path) -> None:
    """하네스 레포 상태를 비운다. 그 뒤에 쌓이는 것은 이 프로젝트의 기록이다."""
    trace = root / TRACE
    if trace.exists():
        trace.write_text("", encoding="utf-8")
        print(f"[SHIPPED STATE] {TRACE} emptied — it was the harness repo's own trace")
    (root / MAINTENANCE).write_text("{}\n", encoding="utf-8")
    print(f"[SHIPPED STATE] {MAINTENANCE} reset — maintenance reminders count from this project")
    remove, keep = repo_only_files(root)
    for rel in remove:
        (root / rel).unlink()
        _prune(root, rel)
    print(f"[SHIPPED STATE] {len(remove)} harness self-test and reference files removed "
          f"({' '.join(HARNESS_REPO_ONLY)}) — they verify the harness itself, and its own CI runs them")
    for rel in keep:
        print(f"   kept {rel} — changed after the first commit, so it may be yours")
