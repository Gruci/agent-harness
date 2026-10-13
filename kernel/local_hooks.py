"""kernel/local_hooks.py — 프로젝트가 자기 레포에 둔 PreToolUse 훅 규칙의 실행과 자가 시험.

게이트(`harness_gates/`)는 저장·종료 시점에 코드 상태를 판정한다. 명령이나 편집이 실행되기 **전에** 막아야 하는
규칙에는 그 자리가 없었다 — 훅 판정은 `kernel/pretool.py` 와 `.claude/hooks/` 에 고정돼 있고, 프로젝트가 고치면
업그레이드가 그 파일에서 멈춘다. 프로젝트 훅은 `harness_hooks/<이름>.py` 에 두고 프로파일 `LOCAL_HOOKS` 로 켠다.
실행은 `kernel/pretool.py` 가 핵심 가드가 통과한 뒤 부르고(Claude·Codex 공통), 자가 시험은 러너 전체 실행이
`local_hook:<이름>` 섹션으로 찍는다.

harness_hooks/<이름>.py 계약
  TOOLS = ("Bash", "PowerShell")      볼 도구 이름. 비우면 전부
  MODE  = "block"                      "warn" 이면 알리기만 한다. 추론 판정은 warn 으로 시작해 관찰 뒤 올린다
  CASES = [("Bash", {"command": "rm -rf data"}, True), ("Bash", {"command": "ls"}, False)]
  def check(tool: str, tool_input: dict, cwd: Path) -> str | None   막을 이유 한 줄, 통과면 None

자가 시험은 CASES 를 실제 판정(`run` 과 같은 경로)으로 돌린다. 모듈을 못 읽거나, 막는 예와 통과 예가 하나씩 없거나,
예 하나라도 기대와 다르면 `[FAIL]` 이다. 오탐을 고친 훅이 예전 판정으로 돌아가면 그 자리에서 잡힌다 — 회고가
"재현 예를 먼저 더한다"고 정한 이유다(`.claude/skills/harness-retro/SKILL.md`).

훅 예외는 막지 않는다. 훅 버그로 세션이 잠기면 그 버그를 고칠 도구까지 막히기 때문이다(`dev/HARNESS.md` 「실패 시 방향」).
경고로 알리고 `gate_error` 관찰로 남긴다. 첫 차단이 이기고, 경고는 모아서 한 번에 낸다.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from kernel import profile
from kernel.context import ROOT
from kernel.sections import Section
from kernel.workspace import Finding

HOOK_NAME = "check_pretool"
HOOKS_DIR = ROOT / "harness_hooks"
MODES = ("block", "warn")


@dataclass(frozen=True)
class Hook:
    """읽어 들인 프로젝트 훅 하나. `check` 는 모듈의 함수 그대로다."""
    name: str
    tools: tuple[str, ...]
    mode: str
    cases: tuple[tuple[str, dict, bool], ...]
    check: Callable[[str, dict, Path], object]


def _load(name: str) -> Hook:
    """`harness_hooks/<이름>.py` 를 읽는다. 계약 위반은 ValueError 로 — 사유가 그대로 [FAIL] 줄이 된다."""
    path = HOOKS_DIR / f"{name}.py"
    where = f"{HOOKS_DIR.name}/{name}.py"
    if not path.is_file():
        raise ValueError(f"{where} does not exist — it is declared in the profile LOCAL_HOOKS")
    spec = importlib.util.spec_from_file_location(f"harness_hooks.{name}", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"{where}: cannot create a loader")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ValueError(f"{where}: load failed {exc.__class__.__name__}: {exc}") from exc
    check = getattr(module, "check", None)
    if not callable(check):
        raise ValueError(f"{where}: no check(tool, tool_input, cwd) function")
    mode = getattr(module, "MODE", "block")
    if mode not in MODES:
        raise ValueError(f"{where}: MODE must be one of {' '.join(MODES)} — got {mode!r}")
    return Hook(name, tuple(getattr(module, "TOOLS", ()) or ()), mode,
                tuple(getattr(module, "CASES", ()) or ()), check)


def _judge(hook: Hook, tool: str, tool_input: object, cwd: Path) -> str | None:
    """훅 하나의 판정. TOOLS 밖의 도구는 보지 않는다. 사유가 있으면 한 줄 문자열이다."""
    if hook.tools and tool not in hook.tools:
        return None
    reason = hook.check(tool, tool_input if isinstance(tool_input, dict) else {}, cwd)
    text = str(reason).strip() if reason else ""
    return text or None


def run(tool: str, tool_input: object, cwd: Path) -> Finding | None:
    """등재된 훅을 순서대로 돌린다. 첫 차단이 이기고, 경고와 훅 오류는 모아서 경고 finding 하나로 낸다."""
    warnings: list[tuple[str, str]] = []
    errors: list[tuple[str, str]] = []
    for name in profile.LOCAL_HOOKS:
        try:
            hook = _load(name)
            reason = _judge(hook, tool, tool_input, cwd)
        except Exception as exc:                  # 훅 버그는 규칙 위반이 아니다 — 막지 않고 알린다
            errors.append((name, f"{exc.__class__.__name__}: {exc}"))
            continue
        if reason is None:
            continue
        if hook.mode == "block":
            return Finding(HOOK_NAME, f"local:{name}", True,
                           f"[LOCAL HOOK] {name}: {reason}\n(Source of truth: {HOOKS_DIR.name}/{name}.py — MODE block)",
                           (reason,))
        warnings.append((name, reason))
    if not warnings and not errors:
        return None
    lines = [f"[LOCAL HOOK] {name}: {reason} (warning — MODE warn)" for name, reason in warnings]
    lines += [f"[LOCAL HOOK] {name} could not run ({detail}) — the rule did not apply; fix {HOOKS_DIR.name}/{name}.py"
              for name, detail in errors]
    kind = f"local:{warnings[0][0]}" if warnings else "gate_error"
    return Finding(HOOK_NAME, kind, False, "\n".join(lines), tuple(reason for _name, reason in warnings + errors))


def _self_test(hook: Hook) -> list[str]:
    """CASES 를 실제 판정으로 돌려 기대와 다른 예를 돌려준다. 막는 예와 통과 예가 하나씩은 있어야 한다."""
    where = f"{HOOKS_DIR.name}/{hook.name}.py"
    found: list[str] = []
    expected = [bool(case[2]) for case in hook.cases if len(case) == 3]
    if len(expected) != len(hook.cases):
        found.append(f"{where}: every CASES entry is (tool, tool_input, expect_block)")
    if True not in expected or False not in expected:
        found.append(f"{where}: CASES needs at least one blocking example and one passing example")
    for index, case in enumerate(hook.cases):
        if len(case) != 3:
            continue
        tool, tool_input, expect = case
        try:
            reason = _judge(hook, str(tool), tool_input, ROOT)
        except Exception as exc:
            found.append(f"{where}: CASES[{index}] raised {exc.__class__.__name__}: {exc}")
            continue
        if bool(reason) != bool(expect):
            found.append(f"{where}: CASES[{index}] {tool} {tool_input!r} expected "
                         f"{'a block' if expect else 'a pass'} but got {reason!r}")
    return found


def sections() -> list[Section]:
    """등재된 훅마다 자가 시험 섹션 하나. 러너 전체 실행이 부른다."""
    found: list[Section] = []
    for name in profile.LOCAL_HOOKS:
        title = f"Project hook {name}"
        try:
            violations = _self_test(_load(name))
        except ValueError as exc:
            violations = [str(exc)]
        found.append((f"local_hook:{name}", title, violations, None))
    return found
