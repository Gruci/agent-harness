"""kernel/gates/core.py — 언어·파일 단위 코어 게이트.

레이어 구조를 모르는 검사만 모았다. 프로젝트에서 받는 것은 어휘(금칙어·축약어)와 면제 목록뿐이고
판정 로직은 어느 프로젝트에서든 같다.

  파일 길이 상한   단일 책임을 잃은 파일. 상한이지 목표가 아니다
  중첩 def         테스트할 수 없는 숨은 로직
  축약 이름·접두   내부 코드가 이름으로 새는 것
  UI 라벨 금칙어   사용자에게 노출되는 조어
  Any              Any 로 타입 검사를 피해 가는 것 (TS any 는 화면 린터 담당 — kernel/eslint.harness.mjs)
  타입힌트 누락    공개 함수의 경계면이 문서화되지 않는 것
  시크릿 토큰      실제 키 하드코딩 — 커밋되면 키를 교체(회전)해야 수습된다
  헤더 경로 주석   파일 이사 후 남은 잘못된 경로 주석
  미정의 모듈 상수 import 는 통과하고 호출할 때 NameError 가 나는 이름

중첩 def·함수 길이·타입힌트는 `ast` 가 아니라 구문 사실(`kernel/facts.py`)을 읽는다. 언어별 차이는
사실을 만드는 분석기가 처리한다. 판정 헬퍼(`nested_pairs`·`long_functions`·`untyped_functions`)는
사실만 받고, `kernel/pack_check.py` 가 같은 헬퍼로 언어팩의 1급 여부를 판정한다. 미정의 모듈 상수는
Python 에만 있는 함정이라 아직 `ast` 로 검사한다.
"""

from __future__ import annotations

import ast
import builtins
import re
from pathlib import Path

from kernel import facts, profile
from kernel.context import READ_ENC, _rel

MAX_LINES = 400
MAX_FUNC_LINES = 80   # 파일 400줄 상한으로는 못 잡는 경우("한 파일에 400줄 함수 하나")를 막는다

# 공급자별 실제 키 형식. 문자열이 이 형식이면 예시가 아니라 진짜 키다.
SECRET_TOKEN = re.compile(
    r"\b(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"
    r"|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9\-]{10,}|AIza[0-9A-Za-z_\-]{30,})"
)

# 줄 끝 주석(`code;  // 설명`) — 화면 밖이라 UI 금칙어 검사에서 제외한다. `://`(URL)는 주석이 아니다.
TRAILING_COMMENT = re.compile(r"(?<!:)//.*$")

_HEADER_PATH = re.compile(r"^#\s+([\w./-]+\.py)\b")


def _alt(words: tuple[str, ...]) -> str:
    return "|".join(re.escape(w) for w in words)


def _abbrev_name_re() -> re.Pattern[str] | None:
    names = profile.VOCAB["abbrev_names"]
    return re.compile(rf"^\s*({_alt(names)})\s*=") if names else None


def _abbrev_prefix_re() -> re.Pattern[str] | None:
    prefixes = profile.VOCAB["abbrev_prefixes"]
    return re.compile(rf"\b({_alt(prefixes)})\w") if prefixes else None


def _is_scratch(rel: str) -> bool:
    scratch = profile.scratch()
    return bool(scratch) and rel.startswith(scratch)


def check_line_limit(files: list[Path]) -> list[str]:
    bad: list[str] = []
    for f in files:
        n = len(f.read_text(encoding=READ_ENC).splitlines())
        if n > MAX_LINES:
            # as_posix() — 형제 검사 전부가 POSIX 표기다. Windows 역슬래시가 섞이면
            # 위반 경로를 키로 쓰는 소비처(allowlist·baseline 대조)가 조용히 빗나간다.
            bad.append(f"{_rel(f)}: {n} lines (>{MAX_LINES})")
    return bad


def check_header_path_comment(files: list[Path]) -> list[str]:
    """1행 `# <경로>.py` 헤더 주석이 실제 경로와 다르면 위반 (디렉토리를 옮긴 뒤 남은 옛 경로 주석을 잡는다)."""
    bad: list[str] = []
    for f in files:
        rel = _rel(f)
        if _is_scratch(rel):
            continue
        first = f.read_text(encoding=READ_ENC).split("\n", 1)[0]
        m = _HEADER_PATH.match(first)
        if m and "/" in m.group(1) and m.group(1) != rel:
            bad.append(f"{rel}: header comment '{m.group(1)}' ≠ actual path — update the comment to the actual path")
    return bad


def nested_pairs(found: facts.FileFacts) -> list[tuple[int, str]]:
    """중첩 def — (줄, "바깥 > 안쪽"). 감싸는 함수가 있는 함수 전부다."""
    return [(fn.line, f"{fn.parent} > {fn.name}") for fn in found.functions if fn.parent]


def long_functions(found: facts.FileFacts) -> list[tuple[facts.Function, int]]:
    """상한을 넘는 함수와 그 줄 수."""
    over: list[tuple[facts.Function, int]] = []
    for fn in found.functions:
        span = fn.end_line - fn.line + 1
        if span > MAX_FUNC_LINES:
            over.append((fn, span))
    return over


def untyped_functions(found: facts.FileFacts) -> list[tuple[facts.Function, list[str]]]:
    """타입이 빠진 공개 함수와 빠진 자리. 언어가 타입을 강제하면(`missing_types` None) 비어 있다."""
    gaps: list[tuple[facts.Function, list[str]]] = []
    for fn in found.functions:
        if not fn.public or fn.missing_types is None:
            continue
        missing = list(fn.missing_types) + (["return"] if fn.missing_return else [])
        if missing:
            gaps.append((fn, missing))
    return gaps


def check_closures(files: list[Path]) -> list[str]:
    """중첩 def(클로저) 금지. 일회성 스크립트와, 해당 줄에 예외 주석(탈출 주석)을 단 경우만 제외.

    예외 주석을 허용하는 이유: 전면 금지하면 데코레이터처럼 클로저로만 쓸 수 있는 경우에 고칠
    방법이 없다. 실제로 테스트의 가짜 git 클로저가 막혀 모듈 레벨로 밀려난 적이 있다. 핵심은
    사유를 적게 하는 것이다. `# any-ok: 사유` 와 같은 방식이고, 예외 주석은 통과 허가가 아니라
    사유를 남기는 기록이다.
    """
    escape = profile.pattern("closure_escape") or "closure-ok"
    comment = profile.pattern("comment") or "#"
    bad: list[str] = []
    for f in files:
        rel = _rel(f)
        if _is_scratch(rel):
            continue
        found = facts.facts_for(f)
        if found is None:
            continue
        if found.error:
            bad.append(f"{rel}: parse failed {found.error}")
            continue
        lines = f.read_text(encoding=READ_ENC).splitlines()
        for lineno, pair in nested_pairs(found):
            if escape in lines[lineno - 1]:
                continue
            bad.append(f"{rel}:{lineno}: nested def {pair} (if unavoidable, `{comment} {escape}: reason`)")
    return bad


def check_func_length(files: list[Path]) -> list[str]:
    """함수·메서드 길이 상한. 일회성 스크립트와 테스트만 제외한다."""
    tests = profile.layer("tests")
    exempt = profile.scratch() + ((tests,) if tests else ())
    bad: list[str] = []
    for f in files:
        rel = _rel(f)
        if exempt and rel.startswith(exempt):
            continue
        found = facts.facts_for(f)
        if found is None or found.error:
            continue                     # 파싱 실패는 중첩 def 게이트가 이미 보고한다
        for fn, span in long_functions(found):
            bad.append(f"{rel}:{fn.line}: {fn.name} {span} lines (>{MAX_FUNC_LINES})")
    return bad


def check_type_checking_future(files: list[Path]) -> list[str]:
    """`if TYPE_CHECKING:` 은 `from __future__ import annotations` 와 함께여야 한다.

    3.11 은 어노테이션을 즉시 평가해 NameError 를 내는데 3.12+ 로컬에서는 통과한다 —
    로컬에서는 초록불이고 CI 에서만 깨지는 함정이라 검사로만 발견할 수 있다.
    """
    bad: list[str] = []
    for f in files:
        text = f.read_text(encoding=READ_ENC)
        if "if TYPE_CHECKING:" in text and "from __future__ import annotations" not in text:
            bad.append(f"{_rel(f)}: TYPE_CHECKING block without `from __future__ import "
                       f"annotations` — 3.11 evaluates annotations eagerly and raises NameError")
    return bad


def check_abbrev_names(files: list[Path]) -> list[str]:
    """금지 축약 이름의 단독 대입."""
    pattern = _abbrev_name_re()
    if pattern is None:
        return []
    bad: list[str] = []
    for f in files:
        rel = _rel(f)
        for i, line in enumerate(f.read_text(encoding=READ_ENC).splitlines(), 1):
            m = pattern.match(line)
            if m:
                bad.append(f"{rel}:{i}: abbreviated variable {m.group(1)} — {line.strip()[:60]}")
    return bad


def check_abbrev_prefixes(files: list[Path]) -> list[str]:
    """금지 축약 접두를 쓴 식별자·키. 단어 경계라 `prev_` 같은 우연 일치는 걸리지 않는다."""
    pattern = _abbrev_prefix_re()
    if pattern is None:
        return []
    bad: list[str] = []
    for f in files:
        rel = _rel(f)
        if _is_scratch(rel):
            continue
        for i, line in enumerate(f.read_text(encoding=READ_ENC).splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            m = pattern.search(line)
            if m:
                bad.append(f"{rel}:{i}: abbreviated prefix {m.group(1)} — {stripped[:60]}")
    return bad


def check_ui_jargon(files: list[Path]) -> list[str]:
    """프론트에서 사용자에게 보이는 텍스트에 금칙어가 나오면 위반. 주석 줄은 제외한다(금칙어를 언급하는 설명은 허용)."""
    denylist = profile.VOCAB["ui_denylist"]
    if not denylist:
        return []
    bad: list[str] = []
    for f in files:
        rel = _rel(f)
        for i, line in enumerate(f.read_text(encoding=READ_ENC).splitlines(), 1):
            stripped = line.strip()
            # 주석(금칙어 메타 언급) 제외 — `{/* … */}` JSX 주석도 화면에 안 나온다.
            if stripped.startswith(("//", "*", "/*", "{/*")):
                continue
            # 줄 끝 주석도 화면 밖이다. `://`(URL)는 주석이 아니므로 남긴다.
            code = TRAILING_COMMENT.sub("", line)
            for term in denylist:
                if term in code:
                    bad.append(f"{rel}:{i}: banned UI term '{term}' — {stripped[:50]}")
    return bad


def check_py_any(files: list[Path]) -> list[str]:
    """임의 타입으로 타입 검사를 피해 가는 것을 금지한다.

    무엇이 '임의 타입'인지는 언어마다 다르다(파이썬 `Any`·Go `interface{}`·TS `any`).
    판정 형태만 여기 있고 패턴은 언어팩이 준다.
    """
    allow = tuple(profile.ALLOWLIST["py_any"])
    tests = profile.layer("tests")
    # 커널 자신은 러너의 대상 수집(`is_harness_own`)에서 이미 빠진다.
    exempt = profile.scratch() + ((tests,) if tests else ())
    pattern = profile.pattern("any_type")
    if not pattern:
        return []
    any_re = re.compile(pattern)
    escape = profile.pattern("any_escape") or "any-ok"
    comment = profile.pattern("comment") or "#"
    bad: list[str] = []
    for f in files:
        rel = _rel(f)
        if rel.startswith(exempt) or rel in allow:
            continue
        for i, line in enumerate(f.read_text(encoding=READ_ENC).splitlines(), 1):
            if escape in line or line.lstrip().startswith(comment):
                continue
            if any_re.search(line):
                bad.append(f"{rel}:{i}: arbitrary type → concrete type (if unavoidable, `{comment} {escape}: reason`)")
    return bad


def check_type_hints(files: list[Path]) -> list[str]:
    """공개 함수의 파라미터·반환 타입힌트. 경계면을 읽는 사람이 본문을 안 읽어도 되게 한다.

    `_` 로 시작하는 내부 함수는 제외한다 — 규칙의 목적이 모듈 경계면이기 때문이다.
    테스트도 제외한다. 커널 자신은 러너의 대상 수집에서 이미 빠진다.
    """
    tests = profile.layer("tests")
    exempt = profile.scratch() + ((tests,) if tests else ())
    bad: list[str] = []
    for f in files:
        rel = _rel(f)
        if rel.startswith(exempt):
            continue
        found = facts.facts_for(f)
        if found is None or found.error:
            continue                     # 파싱 실패는 중첩 def 게이트가 이미 보고한다
        for fn, missing in untyped_functions(found):
            bad.append(f"{rel}:{fn.line}: {fn.name}() missing type hints — {', '.join(missing)}")
    return bad


def check_secrets(files: list[Path]) -> list[str]:
    """실제 키 하드코딩. 커밋되면 지우는 것으로 끝나지 않고 키를 교체(회전)해야 수습된다."""
    bad: list[str] = []
    for f in files:
        rel = _rel(f)
        for i, line in enumerate(f.read_text(encoding=READ_ENC).splitlines(), 1):
            if SECRET_TOKEN.search(line):
                bad.append(f"{rel}:{i}: hardcoded secret token — move it behind the settings module; "
                           f"if already committed, rotate the key")
    return bad


def _bound_names(tree: ast.AST) -> set[str]:
    """그 모듈에서 이름이 될 수 있는 것 — import·정의·대입·인자·global·except as."""
    names = set(dir(builtins))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.Global):
            names.update(node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
    return names


def check_undefined_module_constants(files: list[Path]) -> list[str]:
    """모듈 상수 꼴(`UPPER`·`_UPPER`)인데 어디서도 바인딩되지 않는 참조.

    함수 본문 안의 이름은 **import 를 통과하고 호출 시점에** NameError 로 터진다. 라우트에서는
    그게 곧 500 이다. 서버는 정상 기동하고 그 함수를 안 부르는 테스트도 통과하므로, 개명·삭제에서
    소비처 하나를 놓친 것이 사용자가 그 화면을 누를 때까지 안 보인다.

    대문자로 좁히는 이유는 지역 변수 오탐 없이 모듈 상수만 겨냥하기 위해서다. 소문자까지 보면
    동적 바인딩·전역 주입 같은 정당한 형태가 대량으로 걸린다.
    """
    bad: list[str] = []
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding=READ_ENC))
        except (SyntaxError, ValueError):
            continue
        bound = _bound_names(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)):
                continue
            if node.id in bound or not node.id.lstrip("_").isupper():
                continue
            bad.append(f"{_rel(f)}:{node.lineno}: undefined module constant {node.id} — "
                       f"a rename or delete missed a consumer. It raises NameError when called")
    return bad
