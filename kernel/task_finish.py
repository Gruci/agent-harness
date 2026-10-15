"""kernel/task_finish.py — 과업 끝내기 상태 기계. `python -X utf8 -m kernel.task finish --sid <sid8>` 가 부른다.

지금 상태를 보고 남은 단계만 한다. 몇 번을 다시 실행해도 된다.

| 과업 상태 | 하는 일 |
|---|---|
| 어느 상태든 | worktree 에 커밋 안 한 변경이 있으면 아무것도 바꾸지 않고 멈춘다 — 정리 단계의 날것 git 오류 대신 할 일을 말한다 |
| 합치기 전 | 원격 확인(없으면 로컬에만 합치고 백업 없음을 알린다. `MERGE_FLOW = "pr"` 은 거절) → 소규모 과업이면 실제 diff 상한 확인 → 산출물·시안 폴더 복사·관찰 기록 이동·여기서 다시 만든 지도를 그 브랜치에 커밋 → 따라잡기 merge → 래칫 증가가 있으면 `[RATCHET]` 알림과 관찰(막지 않는다) → 그 worktree 에서 `--verify` → 본체 `merge --ff-only` → push |
| 커밋이 하나도 없던 브랜치 | 합칠 것이 없다고 말하고 정리한다 — HEAD 의 조상이라 "합침"과 그래프로는 구분되지 않아 reflog 로 가른다 |
| `상태: 계획` | 거절 — start 로 구현 단계에 올린 뒤에만 끝낼 수 있다 |
| `MERGE_FLOW = "pr"` | 합치기 대신 `push -u` 와 `gh pr create --fill`, 보드 상태 `PR#n` |
| `PR#n` | 머지됐으면 본체를 `origin/<기본>` 으로 ff 한 뒤 정리, 아니면 CI 확인 명령 안내 |
| 합침 | 원본 산출물 삭제 → `git worktree remove` → `git branch -d` → 보드 파일 삭제(맨 끝, `dev/LESSONS.md` §24) |
| 합침, 실행 위치가 그 worktree 안 | 정리 전에 멈추고 worktree 를 나와 다시 실행하라고 안내 |

| exit | 뜻 |
|---|---|
| 0 | 끝남. 또는 PR 머지 대기나 worktree 밖 재실행 안내를 출력함 |
| 1 | 사람이 할 일 — 커밋 안 한 변경, 충돌, `[FAIL]`, 소규모 상한 초과, 실행 중 origin 이 두 번 움직임 |
| 2 | 지금 끝낼 수 없음 — PR 흐름인데 원격 없음, `[TOOL]`, 러너 실행 실패, git 실패 |
| 3 | `--verify` 결정 대기 — 사용자에게 분류 제안을 알린다 |

결함 E·F·G 는 "검사할 트리, 커밋할 파일, 정리 순서"를 모델이 매번 손으로 고르게 둔 데서 나왔다. 셋 다 기계적으로
정해지므로 코드가 고른다. 이 명령은 나올 때 검사(⑧-7)가 지키는 셸 명령이 아니다 — 같은 `verify_checkout` 을 직접 부른다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

from kernel import profile, trace, workspace
from kernel.baseline import growth
from kernel.context import default_branch
from kernel.exit_gate import verify_checkout
from kernel.hook import refresh_projection
from kernel.isolation import GENERATED, GENERATED_MAPS
from kernel.task import PLANNING, SIZE_KEY, SMALL, TASK_DOCS, fail, git
from kernel.workboard import board_dir, branch_of, field, list_field, sid_of, task_files
from kernel.worktree import worktree_of

ARCHIVE = "docs/tasks/archive"
MOCKUPS = "docs/mockup"
_PR_NUMBER = re.compile(r"/pull/(\d+)")
# 소규모 과업의 사후 실측 상한 — 기존 파일만, 바뀐 줄 합계. 사전 추정이 아니라 실제 diff 라서 낙관 추정이 끼지 않는다.
SMALL_FILES, SMALL_LINES = 3, 40
SMALL_GUARDED = ("harness_profile.py", "profiles/", "docs/architecture/")   # 그래프·프로파일 변경은 소규모가 아니다
NO_REMOTE = ("[TASK] No remote — merged locally only. Nothing is backed up until a remote is connected: "
             "`gh repo create <name> --private --source . --push`, or `git remote add origin <url>` and "
             "`git push -u origin HEAD`.")


def finish(sid8: str, scope: str | None) -> int:
    board = board_dir()
    shared = board.parent
    found = my_task(board, sid8, scope)       # 내 #sid 과업이 둘 이상이면 --scope 를 요구한다
    if found is None:
        return 1
    task_file, text = found
    branch = branch_of(" | ".join(text.split())) or ""
    tree = worktree_of(branch)
    state = field(text, "상태")  # ko-ok: task-board key
    if state == PLANNING:
        return fail(f"{task_file.stem} is still in planning — start it with `python -X utf8 -m kernel.task start "
                    f"{task_file.stem} --sid {sid8} --branch <branch> --touch <glob> --plan <plan>` first. "
                    f"If the plan was abandoned, delete workboard/{task_file.stem}.md by hand.", 1)
    if state.startswith("PR#"):
        return _after_pr(shared, task_file, text, branch, tree, state.removeprefix("PR#"))
    dirty = uncommitted(tree) if tree is not None else []
    if dirty:
        return fail("commit or revert these in the worktree first:\n" + "\n".join(f"  {line}" for line in dirty), 1)
    if not _merged(shared, branch):
        code = _land(shared, task_file, text, branch, tree)
        if code or profile.MERGE_FLOW == "pr":
            return code
    elif not _had_commits(shared, branch):
        return _cleanup(shared, task_file, text, branch, tree, outcome="had no commits — nothing to merge")
    return _cleanup(shared, task_file, text, branch, tree)


def my_task(board: Path, sid8: str, scope: str | None) -> tuple[Path, str] | None:
    """내 `#sid` 과업 파일 하나. 없거나 둘 이상인데 `--scope` 가 없으면 열린 과업 목록과 함께 None."""
    mine = [(path, text) for path, text in task_files(board) if f"#sid:{sid8}" in text]
    if scope:
        mine = [(path, text) for path, text in mine if path.stem == scope]
    if len(mine) == 1:
        return mine[0]
    if not mine:
        opened = ", ".join(path.stem for path, _text in task_files(board)) or "none"
        fail(f"no task file tagged #sid:{sid8}{f' with scope {scope}' if scope else ''} — open tasks: {opened}. "
             f"Take one over with `python -X utf8 -m kernel.task resume <scope> --sid {sid8}`.", 1)
    else:
        fail(f"{len(mine)} tasks are tagged #sid:{sid8} — pass --scope: {', '.join(p.stem for p, _t in mine)}", 1)
    return None


def _merged(shared: Path, branch: str) -> bool:
    """브랜치 끝이 본체 기본 브랜치(HEAD)의 조상인가."""
    return bool(branch) and git(shared, "merge-base", "--is-ancestor", branch, "HEAD").returncode == 0


def _had_commits(shared: Path, branch: str) -> bool:
    """브랜치에 자기 커밋이 있었는가. 커밋 없이 끝난 브랜치도 HEAD 의 조상이라 reflog 항목 수로 가른다. 못 읽으면 있었다고 본다."""
    log = git(shared, "reflog", "show", "--format=%H", f"refs/heads/{branch}")
    return log.returncode != 0 or len(log.stdout.split()) > 1


def _land(shared: Path, task_file: Path, text: str, branch: str, tree: Path | None) -> int:
    """보관 커밋 → 따라잡기 → 그 worktree 검사 → 합치기·push. 어느 단계에서 멈춰도 다시 실행하면 이어서 한다."""
    missing = workspace.git_remote()          # 원격이 없으면 로컬에만 합친다 — PR 흐름은 원격이 있어야 성립한다
    if missing is not None and profile.MERGE_FLOW == "pr":
        return fail(missing.message, 2)
    if tree is None:
        return fail(f"no worktree has {branch} checked out — nothing to verify. Resume it first.", 2)
    # 작업 사본이 갈라진 본체 브랜치 기준으로 잰다 — origin 기준이면 아직 push 안 한 본체 커밋(설정 커밋)까지 크기에 섞였다
    overrun = _small_overrun(tree, text, _local_base(shared), task_file.stem)
    if overrun:
        return fail(overrun, 1)
    _archive(shared, tree, task_file.stem, list_field(text, "산출물"))  # ko-ok: task-board key
    for attempt in range(2):                  # push 사이에 origin 이 움직이면 한 번 더 따라잡는다
        target = _sync_target(shared)
        if not _catch_up(tree, (target, _local_base(shared))):
            return fail(f"merging {target} into {branch} conflicts — resolve it in the worktree, commit, run again.", 1)
        if attempt == 0:
            _report_growth(tree, target, sid_of(text) or "")
        code, lines = verify_checkout(tree) or (0, [])
        if code:
            return fail(f"--verify exited {code} in {tree.name} — fix there, commit, run again.\n" + "\n".join(lines), code)
        if profile.MERGE_FLOW == "pr":
            return _open_pr(task_file, branch, tree, target)
        if _fast_forward(shared, branch) and (missing is not None or _push(shared)):
            if missing is not None:
                print(NO_REMOTE)
            return 0
    return fail("origin moved twice during finish — run it again.", 1)


def _small_overrun(tree: Path, text: str, base: str, scope: str) -> str:
    """소규모 과업(`--small`)의 실제 diff 가 상한을 넘었으면 할 일 한 문단, 아니면 빈 문자열.
    작업 문서·생성 지도·관찰 기록은 세지 않는다 — 과업 결과물이 아니다."""
    if field(text, SIZE_KEY) != SMALL:
        return ""
    stat = git(tree, "diff", "--numstat", f"{base}...HEAD").stdout.splitlines()
    rows = [line.split("\t", 2) for line in stat if line.count("\t") >= 2]
    counted = [(rel, max(int(a) if a.isdigit() else 1, int(d) if d.isdigit() else 1)) for a, d, rel in rows
               if rel not in GENERATED and not rel.startswith(TASK_DOCS)]
    added = git(tree, "diff", "--name-only", "--diff-filter=A", f"{base}...HEAD").stdout.split()
    guarded = [rel for rel, _n in counted if rel.startswith(SMALL_GUARDED)]
    lines = sum(n for _rel, n in counted)
    if len(counted) <= SMALL_FILES and lines <= SMALL_LINES and not added and not guarded:
        return ""
    extra = "".join(f"; {label}: {', '.join(items)}" for label, items in (("new files", added), ("graph or profile", guarded))
                    if items)
    return (f"{scope} grew past a small change ({len(counted)} files, {lines} lines{extra}; limit {SMALL_FILES} existing "
            f"files and {SMALL_LINES} lines). Write the research and plan in {TASK_DOCS}, get the plan approved, then in "
            f"workboard/{scope}.md delete the `- {SIZE_KEY}: {SMALL}` line, list the plan under its artifacts, and run finish again.")


def uncommitted(tree: Path) -> list[str]:
    """worktree 의 `status --porcelain` 줄. 생성 파일(`GENERATED`)은 빼고 본다 — `_archive` 가 커밋에 싣는다."""
    status = git(tree, "status", "--porcelain")
    return [line for line in status.stdout.splitlines()
            if line.strip() and line[3:].strip().strip('"') not in GENERATED]


def _modified(tree: Path, rel: str) -> bool:
    """그 경로가 worktree 에서 바뀌었는가."""
    return bool(git(tree, "status", "--porcelain", "--", rel).stdout.strip())


def _report_growth(tree: Path, base: str, sid8: str) -> None:
    """래칫 파일·제외 목록이 늘었으면 알리고 관찰로 남긴다. 막지 않는다 — 차단으로 올릴지는 회고가 이 관찰을 보고 정한다."""
    for row in growth(tree, base):
        print(f"[RATCHET] {row} — an exemption grew in this task; the retro reads these rows (dev/REJECTED.md keeps the hold)")
        trace.record("task_finish", "ratchet_growth", sid=sid8, msg=row, level="warn")


def _archive(shared: Path, tree: Path, scope: str, artifacts: list[str]) -> None:
    """설계 문서·채택 시안·관찰 기록·다시 만든 지도를 그 과업 브랜치에 커밋한다. 원본은 합친 뒤에 지운다.

    `git mv` 를 쓰지 않는 이유: 산출물은 본체에서 쓰고 한 번도 커밋되지 않아 git 이 모른다(결함 G).
    배포본처럼 archive 를 싣지 않는 레포(`archive_not_shipped` 로컬 게이트)는 본체의 로컬 archive 로만 옮긴다.
    생성 지도는 훅이 갱신했다고 가정하지 않고 여기서 다시 만든다 — 훅을 거치지 않은 편집(사용자 직접 편집·셸)도 받는다.
    """
    folder = f"{ARCHIVE}/{date.today().isoformat()}-{scope}"
    local_only = "archive_not_shipped" in profile.LOCAL_GATES
    dest = (shared if local_only else tree) / folder
    for rel in artifacts:
        source = shared / rel
        if source.is_file():
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest / source.name.removeprefix("wip_"))
    mockups = shared / MOCKUPS / scope
    if mockups.is_dir():
        shutil.copytree(mockups, dest / "mockup", dirs_exist_ok=True)
    refresh_projection(tree)
    staged = [] if local_only else [folder]
    staged += [rel for rel in GENERATED_MAPS if _modified(tree, rel)]   # 모델이 지도 없이 커밋한 경우를 받는다
    if trace.flush(tree / trace.TRACE.name) or _modified(tree, trace.TRACE.name):
        staged.append(trace.TRACE.name)
    present = [rel for rel in staged if (tree / rel).exists()]
    if present and git(tree, "add", "--", *present).returncode == 0:
        git(tree, "commit", "-q", "-m", f"chore(task): archive {scope} design docs and harness trace")


def _local_base(shared: Path) -> str:
    """본체가 서 있는 브랜치 — 기본 브랜치다."""
    return git(shared, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "HEAD"


def _sync_target(shared: Path) -> str:
    """origin 이 있으면 fetch 후 `origin/<기본>`, 없으면 본체 기본 브랜치."""
    base = default_branch()
    if base:
        git(shared, "fetch", "--quiet", "origin", base)
        return f"origin/{base}"
    return _local_base(shared)


def _catch_up(tree: Path, refs: tuple[str, ...]) -> bool:
    """브랜치가 ref 를 품지 않으면 worktree 에서 `merge --no-edit`. 충돌이면 `merge --abort` 하고 False."""
    for ref in dict.fromkeys(refs):
        if git(tree, "merge-base", "--is-ancestor", ref, "HEAD").returncode == 0:
            continue
        merged = git(tree, "merge", "--no-edit", ref)
        if merged.returncode:
            git(tree, "merge", "--abort")
            return False
    return True


def _fast_forward(shared: Path, branch: str) -> bool:
    """본체의 더러운 추적 기록을 대기 파일로 옮기고(L5) 생성 지도를 되돌린 뒤(L6) `merge --ff-only <브랜치>`."""
    trace.reclaim(shared)
    maps = [rel for rel in GENERATED_MAPS if (shared / rel).exists()]
    if maps:
        git(shared, "checkout", "--", *maps)
    merged = git(shared, "merge", "--ff-only", branch)
    if merged.returncode:
        print(f"[TASK] fast-forward refused — {(merged.stderr or merged.stdout).strip()[:300]}", file=sys.stderr)
        return False
    return True


def _push(shared: Path) -> bool:
    """`git push origin <기본>`. 거부되면 False — 루프가 한 번 더 따라잡는다."""
    pushed = git(shared, "push", "origin", _local_base(shared))
    if pushed.returncode:
        print(f"[TASK] push refused — {pushed.stderr.strip()[:300]}", file=sys.stderr)
    return pushed.returncode == 0


def _gh(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)


def _gh_state(shared: Path, number: str) -> str:
    """`gh pr view <n>` 의 state(OPEN·MERGED·CLOSED). gh 가 실패하면 빈 문자열."""
    done = _gh(shared, "pr", "view", number, "--json", "state", "-q", ".state")
    return done.stdout.strip() if done.returncode == 0 else ""


def _set_state(task_file: Path, value: str) -> None:
    lines = task_file.read_text(encoding="utf-8").splitlines()
    kept = [f"- 상태: {value}" if line.strip().startswith("- 상태:") else line for line in lines]  # ko-ok: task-board key
    task_file.write_text("\n".join(kept) + "\n", encoding="utf-8")


def _open_pr(task_file: Path, branch: str, tree: Path, target: str) -> int:
    """`push -u`, `gh pr create --fill`, 보드 상태 `PR#n`. CI 는 `gh pr checks <n>` 을 단독으로 확인하라고 안내한다."""
    pushed = git(tree, "push", "-u", "origin", branch)
    if pushed.returncode:
        return fail(f"push failed — {pushed.stderr.strip()[:300]}", 2)
    created = _gh(tree, "pr", "create", "--fill", "--base", target.removeprefix("origin/"), "--head", branch)
    number = _PR_NUMBER.search(created.stdout + created.stderr)
    if created.returncode or number is None:
        return fail(f"gh pr create failed — {(created.stderr or created.stdout).strip()[:300]}", 2)
    _set_state(task_file, f"PR#{number.group(1)}")
    print(f"[TASK] PR#{number.group(1)} opened for {branch}. Run `gh pr checks {number.group(1)}` alone, "
          "merge when green, then run task finish again to clean up.")
    return 0


def _after_pr(shared: Path, task_file: Path, text: str, branch: str, tree: Path | None, number: str) -> int:
    """`gh pr view` 가 MERGED 면 본체를 ff 한 뒤 정리. squash 머지는 조상이 아니므로 브랜치를 강제로 지운다."""
    state = _gh_state(shared, number)
    if state != "MERGED":
        print(f"[TASK] PR#{number} is {state or 'unknown'} — check `gh pr checks {number}` alone; "
              "run task finish again after the merge.")
        return 0
    base = default_branch()
    if base:
        git(shared, "fetch", "--quiet", "origin", base)
        trace.reclaim(shared)
        forwarded = git(shared, "merge", "--ff-only", f"origin/{base}")
        if forwarded.returncode:
            return fail(f"fast-forward to origin/{base} refused — {forwarded.stderr.strip()[:300]}", 1)
    return _cleanup(shared, task_file, text, branch, tree, force=not _merged(shared, branch))


def _cleanup(shared: Path, task_file: Path, text: str, branch: str, tree: Path | None, force: bool = False,
             outcome: str = "merged") -> int:
    """§24 순서다. 원본 → worktree → 브랜치 → 보드 파일(맨 끝). 중간에 죽어도 보드가 남아 다음 실행이 이어 간다."""
    _drop_originals(shared, task_file.stem, list_field(text, "산출물"))  # ko-ok: task-board key
    if tree is not None:
        if Path.cwd().resolve().is_relative_to(tree.resolve()):
            print(f'[TASK] {outcome.capitalize()}. Leave the worktree first — Claude: ExitWorktree(action="keep") · '
                  "Codex: cd to the main checkout — then run task finish again to clean up.")
            return 0
        removed = git(shared, "worktree", "remove", str(tree))
        if removed.returncode:
            return fail(f"git worktree remove refused — {removed.stderr.strip()[:300]}", 1)
    if branch:
        git(shared, "branch", "-D" if force else "-d", branch)
    task_file.unlink()
    print(f"[TASK] Finished {task_file.stem}: {outcome}, worktree and branch removed, board file deleted last.")
    return 0


def _drop_originals(shared: Path, scope: str, artifacts: list[str]) -> None:
    """보관 사본이 본체 archive 에 있는 원본과 시안 폴더만 지운다."""
    for rel in artifacts:
        source = shared / rel
        name = source.name.removeprefix("wip_")
        if source.is_file() and any((shared / ARCHIVE).glob(f"*-{scope}/{name}")):
            source.unlink()
    mockups = shared / MOCKUPS / scope
    if mockups.is_dir() and any((shared / ARCHIVE).glob(f"*-{scope}/mockup")):
        shutil.rmtree(mockups)
