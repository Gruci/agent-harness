"""PreToolUse(Workflow) 훅 — 워크플로우 스크립트의 `agent()` 에 model 미지정을 차단.

`agent()` 에 model 을 안 주면 **메인 루프 모델을 상속한다.** 툴 문서는 그게 기본이라고 하는데,
그 기본값이 문제없는 것은 메인이 Opus 일 때뿐이다. 메인이 Fable 이면 워커 전원이 Fable 단가에 더해
**Fable 전용 거부 정책까지 함께 상속한다.**

원본 프로젝트 사고(2026-08-21): 15트랙 감사에서 1차 실행 28개가 전부 Fable 로 실행됐고, 재실행한 20개 중
11개가 safeguards 거부로 중단됐다. 같은 재실행에서 Opus 로 돈 3개는 거부가 0건이었다. 거부된 실행은 result 행을 남기지 않아
`pipeline()` 이 끝없이 기다렸고, 그 사이 cache_read 248M 이 과금됐다.

## 왜 산문이 아니라 게이트인가

이 규칙은 이미 `CLAUDE.md` 모델 라우팅에 문장으로 적혀 있었는데도 사고가 났다. 검사할 수 있는
규칙을 문서 문장으로만 단속하면 실패한다는 CLAUDE.md 「일관성 게이트」 1번이 실제로 확인된 사례다.
게다가 그 문장은 적용 범위를 「팬아웃 스테이지」로 좁게 잡았고, 사고는 그 밖(구현·검수)에서 났다. 이 훅은
**모든 `agent()` 호출**을 본다.

## 판정 — 코드 안의 위치로 구분한다

`agent(` 를 찾을 때 **주석과 문자열 안은 세지 않는다.** 워크플로우 스크립트는 프롬프트를
문자열로 담고 있고, 거기에 "agent(" 가 들어가는 것은 정상이다. 그걸 호출로 세면 정상 스크립트가
막힌다. 이 하네스가 `outbound_link` 와 `worktree_add_path` 에서 이미 두 번 겪은 문제라 처음부터
코드 안의 위치로 구분한다.

호출 범위는 괄호 깊이로 잡는다. 정규식으로 같은 줄만 보면 여러 줄로 쓴 호출을 통째로 놓친다.

## 단계

위반은 **차단**(exit 2)한다. 스크립트 본문에 `model:` 이 실제로 없다는 것을 직접 확인한 결과이기 때문이다.
판정할 수 없는 경우(본문 없음, 파일을 못 읽음, 괄호가 안 닫힘)는 **차단하지 않는 경고**(exit 1)다. 스크립트를 못 읽는
것은 규칙 위반이 아니라 훅 오작동이고, 그것으로 Workflow 를 막으면 고칠 수단이 사라진다.
정본은 `dev/HARNESS.md` 「단계」다.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hookio import read_hook_payload, record  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

# `foo.agent(` 는 다른 객체의 메서드다 — 앞이 단어·점이면 호출로 세지 않는다.
CALL = re.compile(r"(?<![\w.])agent\s*\(")
# `agentType:` 은 model 과 동치다 — 에이전트 정의 frontmatter 가 모델의 정본이라서다.
MODEL_KEY = re.compile(r"\b(?:model|agentType)\s*:")
# `...opts` 나 `{...spec}` 처럼 통째로 넘기는 형태는 여기서 판정할 수 없다 — 전개 대상이
# 런타임 값이라 본문에 model 이 안 보인다. 정적 검사의 한계라 판정 불능(경고)으로 넘긴다.
SPREAD = re.compile(r"\.\.\.\s*\w+")
IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")


def strip_noncode(source: str) -> str:
    """주석과 문자열 리터럴을 같은 길이의 공백으로 지운다.

    길이를 보존하는 이유는 줄번호와 괄호 위치가 원본과 같아야 하기 때문이다. 지우지 않고
    검사하면 프롬프트 문자열 안의 `agent(` 를 호출로 세어 정상 스크립트를 막는다.
    """
    out = list(source)
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        nxt = source[index + 1] if index + 1 < length else ""
        if char == "/" and nxt == "/":                       # 줄 주석
            while index < length and source[index] != "\n":
                out[index] = " "
                index += 1
        elif char == "/" and nxt == "*":                     # 블록 주석
            out[index] = out[index + 1] = " "
            index += 2
            while index < length and not (source[index] == "*" and
                                          index + 1 < length and source[index + 1] == "/"):
                if source[index] != "\n":
                    out[index] = " "
                index += 1
            index = min(index + 2, length)
        elif char in "\"'`":                                 # 문자열·템플릿 리터럴
            quote = char
            out[index] = " "
            index += 1
            while index < length and source[index] != quote:
                if source[index] == "\\":
                    out[index] = " "
                    index += 1
                if index < length:
                    if source[index] != "\n":
                        out[index] = " "
                    index += 1
            if index < length:
                out[index] = " "
                index += 1
        else:
            index += 1
    return "".join(out)


def agent_calls(source: str) -> list[tuple[int, str]]:
    """(줄번호, 호출 인자 본문) — `agent(` 부터 짝이 맞는 닫는 괄호까지.

    괄호 깊이로 범위를 잡아 여러 줄 호출을 통째로 담는다. 짝이 안 맞으면 그 호출은 건너뛴다 —
    판정 불능이지 위반이 아니다.
    """
    code = strip_noncode(source)
    found: list[tuple[int, str]] = []
    for match in CALL.finditer(code):
        start = match.end()
        depth = 1
        index = start
        while index < len(code) and depth:
            if code[index] == "(":
                depth += 1
            elif code[index] == ")":
                depth -= 1
            index += 1
        if depth:
            continue                                  # 안 닫힘 — 판정 불능
        found.append((code.count("\n", 0, match.start()) + 1, code[start:index - 1]))
    return found


def _last_top_level_arg(body: str) -> str:
    """호출 인자 본문의 마지막 최상위 인자 — 중첩 괄호 안 쉼표는 무시한다.

    stripped 소스 위라 문자열 안 쉼표는 이미 공백이다.
    """
    depth = 0
    start = 0
    parts: list[str] = []
    for index, char in enumerate(body):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(body[start:index])
            start = index + 1
    parts.append(body[start:])
    return parts[-1].strip()


def _identifier_defines_model(code: str, ident: str) -> bool | None:
    """`ident = {...}` 정의부에 model/agentType 키가 있나. 정의를 못 찾으면 None(판정 불능)."""
    found = re.search(rf"\b{re.escape(ident)}\s*=\s*\{{", code)
    if found is None:
        return None
    depth = 1
    index = found.end()
    while index < len(code) and depth:
        if code[index] == "{":
            depth += 1
        elif code[index] == "}":
            depth -= 1
        index += 1
    if depth:
        return None
    return bool(MODEL_KEY.search(code[found.end():index - 1]))


def classify_calls(source: str) -> tuple[list[int], list[int]]:
    """(model 없는 호출의 줄번호, 판정 불능 호출의 줄번호).

    opts 가 객체 리터럴이면 그 본문에서, 식별자면 그 정의부에서 같은 키를 찾는다. 전개 문법, 정의를 찾지 못한
    식별자, 그 밖의 형태의 opts 는 판정 불능으로 분류한다. 틀릴 수 있는 판정에는 차단 권한을 주지 않는다.
    """
    code = strip_noncode(source)
    missing: list[int] = []
    unknown: list[int] = []
    for line, body in agent_calls(source):
        if MODEL_KEY.search(body):
            continue
        if SPREAD.search(body):
            unknown.append(line)
            continue
        opts = _last_top_level_arg(body)
        if IDENTIFIER.fullmatch(opts):
            verdict = _identifier_defines_model(code, opts)
            if verdict is None:
                unknown.append(line)
            elif not verdict:
                missing.append(line)
            continue
        missing.append(line)
    return missing, unknown


def script_source(tool_input: dict) -> str | None:
    """검사할 스크립트 본문. 인라인 우선, 없으면 `scriptPath` 파일. 둘 다 없으면 None.

    None 은 등재된 워크플로우를 이름으로 부르는 경우다 — 본문이 이 호출에 없으니 검사할 것도 없다.
    """
    inline = tool_input.get("script")
    if isinstance(inline, str) and inline.strip():
        return inline
    raw_path = tool_input.get("scriptPath")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = ROOT / raw_path
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def main() -> None:
    try:
        payload = read_hook_payload()
    except Exception as exc:
        print(f"[WORKFLOW GATE] 훅 페이로드 파싱 실패({exc.__class__.__name__}) — "
              f"model 검사가 동작하지 않는다. 훅을 점검하라.", file=sys.stderr)
        sys.exit(1)

    source = script_source(payload.get("tool_input") or {})
    if source is None:
        sys.exit(0)

    lines, unknown = classify_calls(source)
    sid = str(payload.get("session_id") or "")
    if lines:
        record("check_workflow_script", "workflow_model", sid=sid,
               msg=f"model 미지정 agent() {len(lines)}건 — 줄 {lines}")
        print(
            f"[WORKFLOW GATE] model 을 안 준 `agent()` 호출 {len(lines)}건 — "
            f"줄 {', '.join(str(n) for n in lines)}.\n"
            "model 을 지정하지 않으면 메인 루프 모델을 상속한다. 메인이 Fable 이면 모든 워커가 Fable 단가와\n"
            "Fable 전용 거부 정책까지 상속하고, 거부된 워커는 result 행을 남기지 않아 pipeline 이 끝없이 기다린다.\n"
            "구현·검수는 `model: 'opus'`, 기계적 팬아웃은 `model: 'sonnet'` 을 명시하라.\n"
            "`agentType:` 지정도 통과다 — 에이전트 정의 frontmatter 가 모델의 정본이다.\n"
            "(정본: .claude/agents/orchestrator.md §4-1 Workflow 스폰 계약)",
            file=sys.stderr,
        )
        sys.exit(2)
    if unknown:
        # 판정 불능은 경고다 — 전개·런타임 opts 를 차단하면 정상 스크립트가 막힌다.
        print(f"[WORKFLOW GATE] `agent()` 호출 {len(unknown)}건은 opts 를 판정하지 못했다 — "
              f"줄 {', '.join(str(n) for n in unknown)}. model(또는 agentType)이 실제로 "
              f"명시되는지 직접 확인하라.", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
