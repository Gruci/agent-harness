"""kernel/finish_checks.py — finish 가 합치기 전에 보는 판정과 소규모 과업의 조기 알림.

`kernel/task_finish.py` 는 순서를 정하고 이 모듈은 판정만 한다. 의존 방향은 `task_finish → finish_checks` 하나뿐이다 —
이 모듈은 `task_finish` 를 import 하지 않는다.

| 판정 | 언제 | 결과 |
|---|---|---|
| 범위 대조(`check_touch`) | 보관 커밋과 따라잡기 전 | 이 과업이 바꾼 경로 중 `--touch` 가 덮지 못한 것을 알린다. 공유 체크아웃 프로파일의 `TOUCH_ENFORCE` 가 참일 때만 막는다 |
| 제품 테스트(`product_tests`) | `--verify` 가 통과한 직후, 같은 트리 | 그 트리 프로파일의 `TESTS` 를 `kernel/tests_run.py` 로 돌리고, 검증한 커밋과 테스트한 커밋이 같고 트리가 그대로인지 본다 |
| 소규모 실측(`small_counts`) | 같은 자리 | `task_finish._small_overrun` 과 저장 시점 조기 알림이 같은 계산을 쓴다 |
| 소규모 조기 알림(`small_warning`) | 소규모 과업의 worktree 저장 | 상한의 80% 에 이르면 한 줄 경고. 막지 않고 관찰 기록도 남기지 않는다 |

git 출력은 전부 `-z` 로 읽는다. 공백·탭·개행·한글이 든 경로를 이스케이프나 공백 분할 없이 그대로 받기 위해서다.
"""

from __future__ import annotations

import ast
from pathlib import Path

from kernel import tests_run, trace
from kernel.context import PROFILE_FILE
from kernel.isolation import GENERATED
from kernel.task import SIZE_KEY, SMALL, TASK_DOCS, git
from kernel.workboard import board_dir, field, sid_of, task_files, touch_globs, touches

SMALL_FILES, SMALL_LINES = 3, 40
SMALL_GUARDED = ("harness_profile.py", "profiles/", "docs/architecture/")   # 그래프·프로파일 변경은 소규모가 아니다
SMALL_WARN_RATIO = 0.8


def _nul_fields(out: str) -> list[str]:
    return [part for part in out.split("\0") if part]


def uncommitted(tree: Path) -> list[str]:
    """worktree 의 커밋 안 된 변경 `XY 경로`. 생성 파일(`GENERATED`)은 빼고 본다 — finish 의 보관 커밋이 싣는다."""
    entries = git(tree, "status", "--porcelain", "-z").stdout.split("\0")
    found: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        if entry[0] in "RC":
            index += 1                     # rename·copy 는 다음 칸이 원래 경로다
        if entry[3:] not in GENERATED:
            found.append(entry)
    return found


def _counted(rel: str) -> bool:
    return rel not in GENERATED and not rel.startswith(TASK_DOCS)


def small_counts(numstat_z: str, added_z: str) -> tuple[list[tuple[str, int]], list[str], list[str]]:
    """`--numstat -z --no-renames` 와 `--name-only -z` 출력에서 (센 파일과 줄 수, 새 파일, 보호 경로)를 뽑는다.
    파일마다 max(추가, 삭제) 줄이고 바이너리(`-`)는 1이다."""
    counted: list[tuple[str, int]] = []
    for record in _nul_fields(numstat_z):
        parts = record.split("\t", 2)
        if len(parts) == 3 and _counted(parts[2]):
            added, deleted, rel = parts
            counted.append((rel, max(int(added) if added.isdigit() else 1, int(deleted) if deleted.isdigit() else 1)))
    new_files = [rel for rel in _nul_fields(added_z) if _counted(rel)]
    guarded = [rel for rel, _n in counted if rel.startswith(SMALL_GUARDED)]
    return counted, new_files, guarded


def _changed_paths(tree: Path, base: str) -> list[str]:
    """`base...HEAD` 가 바꾼 경로 — rename 은 양쪽, 삭제도 포함한다."""
    fields = _nul_fields(git(tree, "diff", "--name-status", "--no-renames", "-z", f"{base}...HEAD").stdout)
    return fields[1::2]                    # -z 출력은 상태, 경로, 상태, 경로 … 순서다


def touch_drift(tree: Path, base: str, globs: list[str]) -> list[str]:
    """이 과업이 바꾼 경로 중 `--touch` 가 덮지 못한 것. finish 의 보관 문서와 생성 파일은 뺀다.

    보관·따라잡기 전에 재므로 대개 이 과업의 변경만 남지만, 사용자가 이미 origin 을 worktree 에 merge 했거나
    중단 뒤 재시도한 이력은 섞일 수 있다. 그래서 기본은 알림이다.
    """
    if not globs:
        return []
    return [rel for rel in _changed_paths(tree, base)
            if _counted(rel) and not any(touches(rel, glob) for glob in globs)]


def shared_setting(shared: Path, name: str, default: object) -> object:
    """공유 체크아웃 프로파일의 최상위 상수 하나를 AST 로 읽는다. 파일이나 이름이 없으면 default 다.

    전역 `kernel.profile` 은 finish 를 실행한 커널의 ROOT 프로파일이라 worktree 안에서 실행하면 worktree 것이다.
    정책 값은 worktree 가 자기 프로파일을 고쳐 끌 수 없게 공유 체크아웃 것을 읽는다. 읽을 수 없으면 ValueError 다 —
    기본값으로 조용히 넘어가지 않는다.
    """
    path = shared / PROFILE_FILE
    if not path.is_file():
        return default
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError) as error:
        raise ValueError(f"{path.name} could not be read: {error}") from error
    values: list[ast.expr] = []
    for node in tree.body:
        simple = (node.targets if isinstance(node, ast.Assign) else
                  [node.target] if isinstance(node, ast.AnnAssign) and node.value is not None else [])
        if len(simple) == 1 and isinstance(simple[0], ast.Name) and simple[0].id == name:
            values.append(node.value)
        elif any(isinstance(sub, ast.Name) and sub.id == name and isinstance(sub.ctx, ast.Store) for sub in ast.walk(node)):
            raise ValueError(f"{name} in {path.name} is bound in a way finish cannot read — use one plain assignment")
    if len(values) > 1:
        raise ValueError(f"{name} is assigned {len(values)} times in {path.name} — keep one assignment")
    if not values:
        return default
    try:
        return ast.literal_eval(values[0])
    except ValueError as error:
        raise ValueError(f"{name} in {path.name} is not a literal") from error


def check_touch(shared: Path, tree: Path, base: str, text: str) -> tuple[int, str]:
    """범위 대조. 덮이지 않은 경로가 없으면 (0, ""). 있으면 출력·관찰하고, 강제 설정이면 (1, 안내)다."""
    drift = touch_drift(tree, base, touch_globs(text))
    if not drift:
        return 0, ""
    try:
        enforce = shared_setting(shared, "TOUCH_ENFORCE", False)
    except ValueError as error:
        return 2, f"TOUCH_ENFORCE could not be read from the shared checkout profile — {error}"
    if not isinstance(enforce, bool):
        return 2, f"TOUCH_ENFORCE in the shared checkout profile must be True or False, not {enforce!r}"
    for rel in drift:
        print(f"[TOUCH] {rel} is outside this task's --touch globs")
    trace.record("task_finish", "touch_drift", sid=sid_of(text) or "", msg=", ".join(drift), level="warn")
    if enforce:
        return 1, (f"{len(drift)} changed paths are outside --touch and TOUCH_ENFORCE is on — widen the task's "
                   f"touch globs on the board if they belong to it, or move the changes to their own task.")
    return 0, ""


def product_tests(tree: Path, verified_head: str) -> tuple[int, str]:
    """검증한 그 커밋에서 테스트가 돌았고 그 뒤 트리가 그대로인지. (0, "") 이면 통과다.

    종료 코드는 tests_run 의 것을 보존한다 — 미검증(2)을 일반 실패(1)로 바꾸지 않는다.
    `TESTS` 를 선언하지 않은 트리는 `[SKIP]` 줄을 보이고 통과한다. 그 상태를 제품 테스트 통과라고 부르지 않는다.
    """
    result = tests_run.run_tests(tree)
    if result.lines:
        print("\n".join(result.lines))
    if result.code:
        return result.code, f"product tests exited {result.code} in {tree.name} — fix there, commit, run finish again."
    if result.declared and result.head != verified_head:
        return 1, "HEAD moved between --verify and the product tests — run finish again."
    if git(tree, "rev-parse", "HEAD").stdout.strip() != verified_head or uncommitted(tree):
        return 1, "the worktree changed during the product tests — commit or revert, then run finish again."
    return 0, ""


def _my_task_text(sid8: str) -> str:
    for _path, text in task_files(board_dir()):
        if sid_of(text) == sid8:
            return text
    return ""


def small_warning(tree: Path, sid8: str) -> str:
    """소규모 과업이 상한의 80% 에 이르면 한 줄 경고. 소규모가 아니면 git 을 부르지 않고 빈 문자열이다."""
    text = _my_task_text(sid8[:8]) if sid8 else ""
    if field(text, SIZE_KEY) != SMALL:
        return ""
    shared = board_dir().parent
    base = git(shared, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "HEAD"
    fork = git(tree, "merge-base", base, "HEAD").stdout.strip()
    if not fork:
        return ""
    numstat = git(tree, "diff", "--numstat", "--no-renames", "-z", fork).stdout
    added = (git(tree, "diff", "--name-only", "--diff-filter=A", "-z", fork).stdout + "\0"
             + git(tree, "ls-files", "--others", "--exclude-standard", "-z").stdout)
    counted, new_files, guarded = small_counts(numstat, added)
    lines = sum(n for _rel, n in counted)
    if new_files or guarded or len(counted) >= SMALL_FILES or lines >= SMALL_LINES * SMALL_WARN_RATIO:
        return (f"[SMALL] This small task is at {len(counted)} files and {lines} lines"
                f"{', with new files' if new_files else ''}{', touching graph or profile' if guarded else ''} "
                f"(finish refuses past {SMALL_FILES} existing files, {SMALL_LINES} lines, or any new file). "
                f"If it keeps growing, write the research and plan now.")
    return ""
