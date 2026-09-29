"""tests/test_hooks.py — `.claude/hooks/` 훅 판정 함수의 행동 테스트.

훅은 러너 밖에서 돌기 때문에 골든 대조로는 검사되지 않는다. 그런데 훅의 오판은 게이트 오탐보다 비용이 크다.
세션을 잠그거나 작업 중인 worktree 를 지우라고 요구하기 때문이다. 실제로 이 두 사고가 연달아 났다
(`dev/LESSONS.md` §19). 그래서 판정 함수만 따로 떼어 테스트한다.

  격리 밖 링크    실제 사고가 난 경로를 잡고, 산문과 정상 링크는 통과시키는가
  보드 데이터     파일 하나가 보드 행 하나라는 계약, 브랜치 필드, 겹침 판정
  UI 카피·워크플로 UI 문구 추출기와 워크플로 스크립트의 `agent()` model 판정

worktree 와 작업공간 판정은 커널로 옮겼다. 그 모듈은 `tests/test_workspace.py` 가 직접 테스트한다.
이 파일은 아직 `.claude/hooks/` 가 정본인 훅만 파일로 읽어 테스트한다.

실행: `python -X utf8 tests/test_hooks.py`
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
from pathlib import Path

from harness_test_support import TASK_TEXT, fake_board

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / ".claude" / "hooks"
sys.path.insert(0, str(ROOT))


def _load(name: str):
    """훅을 모듈로 읽는다. 훅끼리 `_hookio` 를 import 하므로 경로를 먼저 얹는다."""
    sys.path.insert(0, str(HOOKS))
    spec = importlib.util.spec_from_file_location(f"_hook_{name}", HOOKS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_outbound_link() -> None:
    """worktree 격리 밖을 가리키는 링크만 잡고, 산문과 트리 안 링크는 통과시킨다."""
    gate = _load("check_bash_write")
    blocked = [
        ("cmd /c mklink /J worktrees/f--1234/frontend/node_modules "
         "D:/proj/frontend/node_modules", "의존성 링크(실제 사고 경로)"),
        ("ln -s /etc/hosts worktrees/f--1234/hosts", "트리 밖"),
        ("New-Item -ItemType Junction -Path worktrees/a/nm -Target ../../node_modules",
         "PowerShell junction"),
    ]
    allowed = [
        ("ln -s docs/tasks/plan.md docs/tasks/current.md", "트리 안에서 안으로"),
        ('git commit -m "ln -s 로 걸었던 링크 제거"', "커밋 메시지 안의 산문"),
        ('echo "use ln -s here" >> notes.txt', "인용문 안"),
    ]
    for command, label in blocked:
        assert gate.outbound_link(command) is not None, f"막아야 하는데 통과: {label}"
    for command, label in allowed:
        assert gate.outbound_link(command) is None, f"통과해야 하는데 막음: {label}"


def test_workboard_file_is_one_row() -> None:
    """보드에서 파일 하나가 행 하나다. README 는 서식 설명이라 과업이 아니고, 디렉토리가 없으면 빈 보드다.

    이 계약이 깨지면 잔여물 검사가 영영 돌지 않거나(항상 busy 상태) 훅이 예외로 죽는다(fail-open 위반).
    """
    from kernel.workboard import active_rows
    with tempfile.TemporaryDirectory() as tmp:
        board = fake_board(Path(tmp))
        (board / "issues-quarter.md").write_text(
            "- 과업: fix/quarter #sid:99999999\n- 상태: 진행\n", encoding="utf-8")
        rows = active_rows(board)
        assert len(rows) == 2, f"README 를 빼고 과업 파일 수만큼 나와야 한다: {rows}"
        assert all("example" not in row for row in rows), "README 를 과업으로 셌다"
        assert active_rows(Path(tmp) / "nope") == [], "없는 디렉토리는 빈 보드여야 한다"


def test_branch_comes_from_task_field() -> None:
    """브랜치는 `과업:` 필드에서 읽는다. `손대는 곳` 에 적힌 `docs/tasks/*` 도 브랜치 접두와 형태가 같아서 헷갈리기 쉽다."""
    from kernel.workboard import active_rows, branch_of
    with tempfile.TemporaryDirectory() as tmp:
        (row,) = active_rows(fake_board(Path(tmp)))
        assert branch_of(row) == "feat/report-viewers", \
            f"과업 필드가 아니라 다른 데서 집었다: {branch_of(row)}"


def test_workboard_overlap() -> None:
    """겹침 판정. 내 과업에는 경고하지 않고(경고가 소음이 되는 것을 막는다), 남의 과업에는 경고하며(방어가 사라지는 것을 막는다), 관련 없는 파일에는 경고하지 않는다."""
    overlap = _load("check_workboard_overlap")
    from kernel.workboard import touch_globs
    globs = touch_globs(TASK_TEXT)
    assert globs == ["frontend/src/components/admin/salesStatus/*", "docs/tasks/plan_x.md"], \
        f"다음 필드(- 상태:)까지 글로브로 읽었다: {globs}"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        overlap.BOARD_DIR = fake_board(root)
        overlap.ROOT = root
        target = root / "frontend/src/components/admin/salesStatus/X.tsx"
        assert overlap.overlaps(target, "abcd1234") == [], "자기 과업에 경고가 떴다"
        hits = overlap.overlaps(target, "ffffffff")
        assert hits and "admin-report-viewers" in hits[0], f"남의 글로브를 놓쳤다: {hits}"
        assert overlap.overlaps(root / "db/core.py", "ffffffff") == [], "무관 파일에 경고가 떴다"


def test_auto_merge() -> None:
    """`gh pr merge --auto` 만 잡는다 — 산문·일반 머지는 통과."""
    gate = _load("check_bash_write")
    assert gate.auto_merge("gh pr merge 12 --auto") is True
    assert gate.auto_merge("gh pr checks 12 ; gh pr merge 12 --auto --squash") is True
    assert gate.auto_merge("gh pr merge 12 --merge") is False, "일반 머지를 막았다"
    assert gate.auto_merge('git commit -m "gh pr merge --auto 설명"') is False, "산문을 명령으로 오독"


def test_shared_tree_mutation() -> None:
    """병렬 중 공유 체크아웃의 git 변경은 막고, 끝난 브랜치의 `git merge --ff-only` 는 통과시킨다.

    격리가 강제된 뒤로 이 절은 과업이 열려 있는 동안 늘 적용된다. fast-forward 까지 막으면 완료 절차
    (합치기 → 자기 worktree 제거)를 밟을 수 없다.
    """
    gate = _load("check_bash_write")
    gate._is_main_checkout = lambda: True
    gate._parallel_mode = lambda: True
    for command, expected in (("git merge feat/x", "git merge"), ("git commit -m x", "git commit"),
                              ("git switch feat/x", "git switch")):
        assert gate.shared_tree_mutation(command) == expected, f"막아야 하는데 통과: {command}"
    for command in ("git merge --ff-only feat/x", 'echo "git merge"', "git -C worktrees/a--1 commit -m x"):
        assert gate.shared_tree_mutation(command) is None, f"통과해야 하는데 막음: {command}"
    gate._parallel_mode = lambda: False
    assert gate.shared_tree_mutation("git merge feat/x") is None, "병렬이 아닌데 막았다"


def test_ui_copy_extract() -> None:
    """문구 추출기 단위 테스트. JSX 텍스트는 추출하고, JSDoc 이어짐 줄은 제외하고, `${}` 를 가린 뒤 남는 조각은 버린다. LLM 은 호출하지 않는다."""
    gate = _load("check_ui_copy")
    lines = [
        "  <span>수탁고 추이</span>",                      # JSX 텍스트 → 추출
        "  const label = '기간 선택';",                    # 리터럴 → 추출
        " * '주석 속 인용'은 화면에 안 나간다",             # JSDoc 이어짐 줄 → 제외
        "  const t = `${y}년 ${m}월`;",                    # 치환 후 남는 조각 → 제외
        "  const u = `${name} 님의 보유 현황`;",           # 치환 + 실제 문구 → 치환을 가리고 추출
    ]
    found = gate.extract_strings(lines)
    assert "수탁고 추이" in found and "기간 선택" in found
    assert all("주석" not in s for s in found), "주석 이어짐 줄을 추출했다"
    assert "{값}년 {값}월" not in found, "조사·단위 조각을 문구로 추출했다"
    assert "{값} 님의 보유 현황" in found, "치환을 가린 실제 문구를 놓쳤다"


def test_workflow_model_required() -> None:
    """`agent()` 에 model 을 지정하지 않은 호출만 잡고, 주석이나 문자열 안의 `agent(` 는 호출로 세지 않는다.

    워크플로우 스크립트는 프롬프트를 문자열로 들고 다닌다. 그 안에 "agent(" 가 들어가는 것은
    정상이라, 코드인지 문자열인지 가르지 않으면 정상 스크립트가 막힌다.
    """
    gate = _load("check_workflow_script")
    violating = [
        ("const r = await agent('find bugs')", [1], "한 줄 · model 없음"),
        ("await agent(\n  'p',\n  {label: 'x',\n   phase: 'Find'}\n)", [1], "여러 줄 · model 없음"),
        ("await agent('a', {model:'opus'})\nawait agent('b')", [2], "둘 중 하나만 누락"),
    ]
    passing = [
        ("const r = await agent('find bugs', {model: 'opus'})", "model 있음"),
        ("await agent(\n  'p',\n  {label: 'x',\n   model: 'sonnet'}\n)", "여러 줄 · model 있음"),
        ("// await agent('x')\nawait agent('y', {model:'opus'})", "주석 안 호출"),
        ("await agent(`설명: agent( 를 쓰는 법`, {model:'opus'})", "템플릿 문자열 안"),
        ("await agent('a', {...opts})", "전개 — 런타임 값이라 판정할 수 없음"),
        ("await agent('a', {agentType: 'code-reviewer'})", "agentType — frontmatter 가 모델 정본"),
        ("const O = {model:'opus'}\nawait agent('a', O)", "식별자 opts — 정의부에 model"),
        ("foo.agent('x')", "남의 객체 메서드 — 호출로 세지 않는다"),
    ]
    for source, expected, label in violating:
        assert gate.classify_calls(source)[0] == expected, f"잘못 잡았다: {label}"
    for source, label in passing:
        assert gate.classify_calls(source)[0] == [], f"통과해야 하는데 막음: {label}"

    # 판정할 수 없는 호출은 차단(missing)이 아니라 경고(unknown)로 분류한다.
    missing, unknown = gate.classify_calls("await agent('a', mysteryOpts)")
    assert missing == [] and unknown == [1], "정의를 찾을 수 없는 식별자 opts 는 판정할 수 없음(경고)으로 나와야 한다"
    missing, unknown = gate.classify_calls("const O = {label:'x'}\nawait agent('a', O)")
    assert missing == [2] and unknown == [], "정의부에 model 없는 식별자 opts 는 위반이어야 한다"


def test_record_never_raises() -> None:
    """관찰 기록은 커널이 없어도 예외를 안 낸다 — 기록 실패가 차단을 죽이면 안 된다."""
    hookio = _load("_hookio")
    saved = sys.modules.get("kernel.trace")
    sys.modules["kernel.trace"] = None
    try:
        hookio.record("test", "kind", sid="00000000", msg="x")
    finally:
        if saved is None:
            sys.modules.pop("kernel.trace", None)
        else:
            sys.modules["kernel.trace"] = saved


def test_trace_paths_are_portable() -> None:
    """커밋되는 관찰 기록에 체크아웃 위치와 사용자 홈 경로가 남지 않아야 한다. 남으면 clone 위치를 옮길 때 기록의 키가 달라진다."""
    sys.path.insert(0, str(ROOT))
    from kernel.context import ROOT as KROOT
    from kernel.trace import portable
    inside = KROOT.resolve() / "kernel" / "hook.py"
    assert portable(str(inside)) == "kernel/hook.py", portable(str(inside))
    assert portable(f"{inside}:12: 위반") == "kernel/hook.py:12: 위반"
    home_file = Path.home().resolve() / ".claude" / "x.txt"
    assert portable(str(home_file)) == "~/.claude/x.txt", portable(str(home_file))
    assert portable("orders/a.py:3: 위반") == "orders/a.py:3: 위반", "상대경로를 건드렸다"
    # 구분자 없이 단독으로 나온 루트·홈. 실제로 `--root <루트>` 안내문이 절대경로 그대로 커밋될 뻔했다
    root = KROOT.resolve()
    assert portable(f"run x --root {root}") == "run x --root .", portable(f"run x --root {root}")
    assert portable(f"{root}에서 exit 1") == ".에서 exit 1", "한글이 바로 붙은 루트를 놓쳤다"
    assert portable(f"home {Path.home().resolve()}") == "home ~", "단독 홈 경로를 놓쳤다"
    sibling = f"{root}-old/a.py"
    assert portable(sibling) == sibling, "레포 밖 형제 경로를 레포 경로로 바꿨다"


def test_agent_return_gate_error_keys() -> None:
    """반환 검사를 못 하면 값 형식과 받은 키를 기록하고 통과시킨다. 값 본문은 대화 내용일 수 있어 기록하지 않는다."""
    gate = _load("check_agent_return")
    recorded: list[str] = []
    gate.read_hook_payload = lambda: {"session_id": "abcd1234", "hook_event_name": "SubagentStop",
                                      "agent_transcript_path": "C:/secret/x.jsonl"}
    gate.record = lambda *args, **kwargs: recorded.append(kwargs.get("msg", ""))
    code = None
    with contextlib.redirect_stderr(io.StringIO()):
        try:
            gate.main()
        except SystemExit as done:
            code = done.code
    assert code == 0, f"검사 불능인데 막았다: exit {code}"
    (msg,) = recorded
    assert "NoneType" in msg and "hook_event_name" in msg and "session_id" in msg, msg
    assert "secret" not in msg, "값 본문을 기록했다"


def demo() -> None:
    for check in (test_outbound_link, test_workboard_file_is_one_row, test_branch_comes_from_task_field,
                  test_workboard_overlap, test_auto_merge, test_shared_tree_mutation, test_ui_copy_extract,
                  test_workflow_model_required, test_record_never_raises,
                  test_trace_paths_are_portable, test_agent_return_gate_error_keys):
        check()
        print(f"  [OK] {check.__name__}")
    print("훅 행동 테스트 모두 통과")


if __name__ == "__main__":
    demo()
