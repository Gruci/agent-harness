"""tests/test_workspace.py — worktree·작업공간 판정(`kernel/worktree.py`·`kernel/workspace.py`)의 행동 테스트.

이 판정은 Claude 훅과 Codex 진입점이 같이 쓴다. 오판은 게이트 오탐보다 비싸다. 세션을
잠그거나, 작업 중인 worktree 를 지우라고 요구하기 때문이다. 실제로 그 두 사고가 연달아 났다
(`dev/LESSONS.md` §19, 고칠 수단이 없는 조건으로 차단한 사고). 그래서 커널 모듈의 판정 함수를 직접 테스트한다.

  worktree 잔해   방금 만든 worktree 를 잔해로 잘못 판정하지 않는가
  이름·자리       이름 접미사·범위·위치 규약, heredoc 안 산문을 명령으로 잘못 읽지 않는가
  보드 과업       진행 중인 내 과업은 통과, 브랜치명 없는 과업은 경고
  과업 산출물     방금 만든 산출물은 유예하고, 보드 조회가 실패해도 검사가 도는가
  Codex Stop      경고만 있으면 exit 0 + systemMessage, 차단이 섞이면 stderr + 2 인가
  Claude 래퍼     커널로 옮긴 뒤에도 기존 exit 와 stderr 머리말을 내는가

실행: `python -X utf8 tests/test_workspace.py`
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from harness_test_support import fake_board

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / ".claude" / "hooks"
sys.path.insert(0, str(ROOT))

# 중첩 def 금지 검사(검사 2) 때문에 가짜 git 을 모듈 레벨에 둔다. 케이스는 `_UPSTREAM` 값으로 가른다.
_UPSTREAM = ""


def _fake_git(*args: str) -> str | None:
    """worktree 잔해 판정이 묻는 세 질문에만 답한다. config 를 뺀 나머지 두 질문의 답은 항상 '잔해' 쪽이다."""
    if args[0] == "config":
        return _UPSTREAM                          # branch.<X>.merge 값
    if args[0] == "show-ref":
        return None                               # origin 에 없다
    if args[0] == "merge-base":
        return ""                                 # 기본 브랜치의 조상이다
    return None


def test_fresh_worktree_not_dead() -> None:
    """`git worktree add -b X origin/main` 이 남기는 upstream 은 push 이력이 아니다.

    시작점을 upstream 으로 자동 등록하므로 `branch.X.remote` 는 방금 만든 브랜치에도 있다.
    그것을 push 이력으로 읽으면 나머지 두 조건(원격 ref 없음·기본 브랜치의 조상)이 자동으로
    참이라, worktree 를 만든 그 순간부터 "머지 완료, 지워라"가 된다.
    """
    global _UPSTREAM
    from kernel import worktree
    real_git = worktree._git
    worktree._git = _fake_git
    try:
        _UPSTREAM = "refs/heads/main\n"           # 방금 만든 브랜치 — upstream 이 기본 브랜치다
        assert worktree.is_dead("feat/x", "main") is False, "방금 만든 worktree 를 잔해로 판정했다"

        _UPSTREAM = "refs/heads/feat/x\n"         # push -u 이력 — upstream 이 자기 이름이다
        assert worktree.is_dead("feat/x", "main") is True, "진짜 잔해를 놓쳤다"

        _UPSTREAM = ""                            # upstream 없음 = 로컬 전용 브랜치
        assert worktree.is_dead("feat/x", "main") is False
    finally:
        worktree._git = real_git


def test_alive_no_nameerror() -> None:
    """`_alive` 가 실제로 실행되는가. import 가 빠지면 NameError 를 `except` 가 삼켜서
    lock 걸린 worktree 가 정리 대상에서 영구히 빠진다(2026-09-07 실제 발생: `import subprocess` 누락)."""
    from kernel import worktree
    assert worktree._alive(os.getpid()) is True, "살아있는 자기 PID 를 죽었다고 판정했다"


def test_worktree_rel_strip() -> None:
    """worktree 안 파일의 상대경로에서는 `worktrees/<이름>/` 접두를 떼야 한다. 떼지 않으면 경로 기반 게이트가 전부 오탐한다."""
    from kernel.context import ROOT as KROOT, _rel
    inside = KROOT / "worktrees" / "feat-x--12345678" / "orders" / "a.py"
    assert _rel(inside) == "orders/a.py", "루트 worktrees/ 접두를 못 벗겼다"
    assert _rel(KROOT / "orders" / "a.py") == "orders/a.py"
    assert _rel(KROOT / "workboard" / "x.md") == "workboard/x.md", "보드 파일을 worktree 로 오인"


def test_worktree_location() -> None:
    """위치 규약: 공유 루트 기준 상대경로 `worktrees/<이름>` 만 통과한다. 나머지는 기대 경로를 알려준다."""
    from kernel import worktree as naming
    expected = "worktrees/feat-x--12345678"
    assert naming.wrong_location(expected) is None
    assert naming.wrong_location("./worktrees/feat-x--12345678") is None
    for token, label in (
        ("D:/repo/worktrees/feat-x--12345678", "드라이브 절대경로"),
        ("D:\\repo\\worktrees\\feat-x--12345678", "역슬래시 절대경로"),
        ("/srv/worktrees/feat-x--12345678", "POSIX 절대경로"),
        ("~/worktrees/feat-x--12345678", "홈 경로"),
        ("../worktrees/feat-x--12345678", "상위 탈출"),
        ("worktrees/sub/feat-x--12345678", "중첩 자리"),
        (".claude/worktrees/feat-x--12345678", ".claude/ 밑"),
        (".codex/worktrees/feat-x--12345678", ".codex/ 밑"),
        ("feat-x--12345678", "루트에 바로 생성"),
    ):
        assert naming.wrong_location(token) == expected, f"{label}을 통과시켰다: {token}"
    with tempfile.TemporaryDirectory() as tmp:
        shared = Path(tmp)
        (shared / "worktrees" / "other").mkdir(parents=True)
        assert naming.wrong_location(expected, shared, shared) is None
        assert naming.wrong_location(expected, shared / "worktrees" / "other", shared) == expected, \
            "다른 worktree 안에서의 상대 생성을 통과시켰다"
        board = shared / "workboard"
        board.mkdir()
        found = naming.name_violation(expected, "12345678", board, shared / "worktrees" / "other")
        assert found is not None and found.block, "공유 루트 밖 cwd 를 통과시켰다"
        assert naming.name_violation(expected, "12345678", board, shared) is None
    assert naming.worktree_add_path(
        "git worktree add worktrees/feat-x--12345678 -b feat/x origin/main"
    ) == "worktrees/feat-x--12345678", "경로 토큰을 못 읽었다"
    found = naming.name_violation(".claude/worktrees/x--12345678", "12345678", None)
    assert found is not None and found.block and "worktrees/x--12345678" in found.message, found


def test_worktree_name_matches_scope() -> None:
    """worktree 이름 앞부분은 내 workboard 범위와 같아야 한다. 어긋나면 기대 이름을 알려주고, 보드 파일이 없으면 검사를 건너뛴다.

    보드 등록이 worktree 보다 먼저지만, 순서를 바꾼 예외 상황에서 막으면 손쓸 방법이 없다.
    """
    from kernel import worktree as naming
    with tempfile.TemporaryDirectory() as tmp:
        board = fake_board(Path(tmp))
        assert naming.scope_mismatch("admin-report-viewers--abcd1234", "abcd1234", board) is None
        assert naming.scope_mismatch("report-viewers--abcd1234", "abcd1234", board) \
            == "admin-report-viewers--abcd1234", "범위 불일치를 통과시켰다"
        assert naming.scope_mismatch("anything--00000000", "00000000", board) is None, \
            "보드 파일 없는 세션의 생성을 막았다"
        found = naming.name_violation("worktrees/report-viewers--abcd1234", "abcd1234", board)
        assert found is not None and found.block and "admin-report-viewers--abcd1234" in found.message
        assert naming.name_violation("worktrees/admin-report-viewers--abcd1234", "abcd1234", board) is None


def test_worktree_add_only_at_command_head() -> None:
    """인용문 안의 `git worktree add` 는 명령이 아니다.

    문자열 전체를 훑던 판정이 커밋 메시지 heredoc 안의 산문을 명령으로 읽어 자기 커밋을 막았다.
    `outbound_link` 가 앞 3토큰만 보도록 제한해 막은 문제와 같은 종류다. 명령인지 인자인지는 토큰의 위치가 정한다.
    """
    from kernel import worktree as naming
    # 이 훅이 실제로 잘못 막은 명령이다. heredoc 본문은 따옴표로 묶이지 않아 shlex 가 그대로 낱말로
    # 쪼갠다. 그래서 `git`·`worktree`·`add` 가 나란히 놓여, 낱말이 붙어 있는지로는 구분되지 않고 위치로만 구분된다.
    heredoc_prose = (
        "git commit -q -F - <<'EOF'\n"
        "feat(harness): 역이식\n\n"
        "잔해 훅이 갓 판 worktree 를 뒤집었다. `git worktree add -b X origin/main`\n"
        "이 시작점을 upstream 으로 자동 등록해서 remote 가 갓 판 브랜치에도 있다.\n"
        "EOF"
    )
    real = [
        ("git worktree add worktrees/feat-x--16aa3fa6 -b feat/x origin/main",
         "feat-x--16aa3fa6"),
        ("git worktree add -b feat/x worktrees/topic--abcd1234 origin/main",
         "topic--abcd1234"),
        ("cd /repo && git worktree add worktrees/z--abcd1234", "z--abcd1234"),
    ]
    prose = [
        (heredoc_prose, "커밋 메시지 heredoc 안 산문 — 실제 사고 케이스"),
        ('git commit -m "git worktree add -b X origin/main 설명"', "인용문 안"),
        ("echo git worktree add foo > notes.txt", "echo 인자"),
        ("git worktree list", "생성이 아닌 하위명령"),
        ("git worktree remove worktrees/a", "제거"),
    ]
    for command, expected in real:
        assert Path(naming.worktree_add_path(command) or "").name == expected, f"정상 생성을 못 읽었다: {command}"
    for command, label in prose:
        assert naming.worktree_add_path(command) is None, f"명령으로 오독: {label}"


def test_board_residue_keeps_running_task() -> None:
    """진행 중인 내 과업은 통과, 브랜치명 없는 내 과업은 서식 위반이라 경고 — 둘 다 차단이 아니다."""
    from kernel import workspace
    real_git = workspace._git
    workspace._git = _fake_git                    # log 조회가 None → 머지 안 됨
    try:
        with tempfile.TemporaryDirectory() as tmp:
            board = fake_board(Path(tmp))
            assert workspace.board_residue("abcd1234", board) is None, "진행 중인 내 과업을 남은 잔해로 잡았다"
            (board / "no-branch.md").write_text("- 과업: 메인 체크아웃 #sid:abcd1234\n", encoding="utf-8")
            found = workspace.board_residue("abcd1234", board)
            assert found is not None and found.block is False, "브랜치명 없는 과업은 경고여야 한다"
            assert found.message.startswith("[WORKBOARD]") and len(found.trace) == 1, found
            assert workspace.board_residue("ffffffff", board) is None, "남의 진행 중 과업을 건드렸다"
    finally:
        workspace._git = real_git


def test_task_residue_fresh() -> None:
    """방금 만든 산출물은 검출하지 않는다. 보드에 아직 등록하지 않은 계획 단계 세션은 이 유예 시간이 보호한다."""
    from kernel import workspace as residue
    fake = ROOT / "docs" / "BACKLOG.md"            # 실존 파일이면 무엇이든 mtime 조작 없이 fresh
    assert residue._is_fresh(fake, time.time()) in (True, False)   # 판정 중에 예외가 나지 않는다
    assert residue._is_fresh(fake, fake.stat().st_mtime + 60) is True, "1분 전 파일을 잔해로 판정"
    assert residue._is_fresh(fake, fake.stat().st_mtime + residue.FRESH_SEC + 1) is False, \
        "하루 지난 파일을 fresh 로 판정"
    assert residue._is_fresh(ROOT / "no-such-file.md", time.time()) is True, \
        "stat 실패는 fresh(막지 않는다) 여야 한다"


def _broken_board(board: Path) -> list[str]:
    raise OSError("board unreadable")


def test_task_residue_survives_board_failure() -> None:
    """보드 조회가 실패해도 남은 산출물 검사는 돈다. 예전에는 다른 훅의 최상위 `sys.exit(0)` 때문에 검사 전체가 그냥 끝났다."""
    from kernel import workspace as residue
    saved_rows, saved_dir = residue.active_rows, residue.TASK_DIR
    residue.active_rows = _broken_board
    try:
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan_old.md"
            plan.write_text("x", encoding="utf-8")
            os.utime(plan, (0, 0))                 # 유예(24시간)를 넘긴 산출물
            residue.TASK_DIR = Path(tmp)
            assert residue.board_is_busy() is False, "보드 실패를 '보드 비었음'으로 보지 않았다"
            assert residue.task_leftovers() == [plan], "보드 조회 실패로 남은 산출물 검사가 꺼졌다"
            found = residue.task_residue()
            assert found is not None and found.block and found.message.startswith("[TASK RESIDUE]"), found
    finally:
        residue.active_rows, residue.TASK_DIR = saved_rows, saved_dir


def test_codex_stop_verdict() -> None:
    """경고만 있으면 exit 0 + systemMessage 본문, 차단이 하나라도 있으면 stderr 로 전부 내고 2 다."""
    from kernel.hook import workspace_verdict
    from kernel.workspace import Finding
    warn = Finding("check_editing_lock", "editing_lock", False, "[WORKBOARD] 경고 본문", ("row",))
    block = Finding("check_task_residue", "task_residue", True, "[TASK RESIDUE] 차단 본문", ("1건",))
    assert workspace_verdict([]) == (0, ""), "finding 없음은 조용한 통과여야 한다"
    assert workspace_verdict([warn]) == (0, "[WORKBOARD] 경고 본문"), "경고만이면 systemMessage 경로다"
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert workspace_verdict([warn, block]) == (2, ""), "차단은 exit 2 + stderr 다"
    assert "[TASK RESIDUE]" in err.getvalue() and "[WORKBOARD]" in err.getvalue(), \
        "차단하는 턴에는 경고도 stderr 에 함께 내야 모델이 읽는다"


def _wrapper_root(base: Path) -> Path:
    """커널과 래퍼 셋을 임시 루트로 복사한다 — 래퍼는 자기 위치에서 ROOT 를 잡는다."""
    root = base / "proj"
    shutil.copytree(ROOT / "kernel", root / "kernel", ignore=shutil.ignore_patterns("__pycache__", "engine"))
    (root / ".claude" / "hooks").mkdir(parents=True)
    for name in ("_hookio", "check_task_residue", "check_mockup_residue"):
        shutil.copy2(HOOKS / f"{name}.py", root / ".claude" / "hooks" / f"{name}.py")
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    return root


def _run_wrapper(root: Path, name: str) -> tuple[int, str]:
    done = subprocess.run([sys.executable, "-X", "utf8", str(root / ".claude" / "hooks" / f"{name}.py")],
                          cwd=str(root), input='{"session_id": "wrap1234"}', capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=60)
    return done.returncode, done.stderr


def test_claude_wrappers_keep_exit_and_header() -> None:
    """커널로 옮긴 뒤에도 Claude 래퍼는 같은 조건에서 기존 exit 2 와 stderr 머리말을 낸다."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _wrapper_root(Path(tmp))
        tasks = root / "docs" / "tasks"
        tasks.mkdir(parents=True)
        code, err = _run_wrapper(root, "check_task_residue")
        assert code == 0, err
        plan = tasks / "plan_old.md"
        plan.write_text("x", encoding="utf-8")
        os.utime(plan, (0, 0))
        code, err = _run_wrapper(root, "check_task_residue")
        assert code == 2 and err.startswith("[TASK RESIDUE]") and "plan_old.md" in err, (code, err)

        mockup = tasks / "mockup"
        mockup.mkdir()
        (mockup / "wip_a.html").write_text("<p>a</p>", encoding="utf-8")
        code, err = _run_wrapper(root, "check_mockup_residue")
        assert code == 0, err
        (mockup / "b.html").write_text("<p>b</p>", encoding="utf-8")
        code, err = _run_wrapper(root, "check_mockup_residue")
        assert code == 2 and err.startswith("[MOCKUP RESIDUE]") and "b.html" in err, (code, err)


def demo() -> None:
    for check in (test_fresh_worktree_not_dead, test_alive_no_nameerror, test_worktree_rel_strip,
                  test_worktree_location, test_worktree_name_matches_scope,
                  test_worktree_add_only_at_command_head, test_board_residue_keeps_running_task,
                  test_task_residue_fresh, test_task_residue_survives_board_failure,
                  test_codex_stop_verdict, test_claude_wrappers_keep_exit_and_header):
        check()
        print(f"  [OK] {check.__name__}")
    print("작업공간 판정 테스트 전건 통과")


if __name__ == "__main__":
    demo()
