"""kernel/gates/duplication.py — 정본을 다시 짠 코드를 사고가 나기 전에 찾는다 (래칫: baseline 은 줄어들기만 한다).

다른 게이트는 전부 **사고가 난 뒤에** 생겼다. 누군가 문제를 알아채야 규칙이 하나 늘었다는 뜻이고,
그래서 하네스는 강제는 해도 문제 발견은 사람에게 맡겨 왔다. 이 게이트는 그보다 앞 단계를 맡는다.
어느 정본을 우회했는지는 모르는 채로 **"같은 것이 두 곳에 있다"만** 본다.

  선언 중복   함수·컴포넌트 선언의 **본문 지문**이 같다. 함수 이름은 보지 않는다
  블록 중복   선언 안쪽 덩어리가 연속 여러 줄 같다. 함수로 안 뽑힌 복붙이 대상이다

## 지문 — 지역 이름을 지운 토큰열

이름만 갈린 재구현(`signedWon`·`wonSigned`)을 잡으려고 본문 토큰에서 **그 함수 안에서 생긴 이름**(인자·지역 변수)만
등장 순서 번호로 바꾼다. 호출 대상·멤버(`.x`)·전역·리터럴은 그대로다 — 모양이 같아도 다른 API 를 부르면 다른 구현이다.
Python 은 독스트링을 뺀 본문의 `ast.unparse`, 다른 서버 언어는 구문 사실(`kernel/facts.py`)의 함수 범위, 화면은 선언
정규식의 본문이다. 크기 하한은 문장 수가 아니라 토큰 수다(`with` 한 블록짜리 함수도 비교한다). 같은 파일 안의 두 선언도
묶고, 블록은 같은 파일이면 `BLOCK_WINDOW` 이상 떨어져야 센다. 테스트는 같은 준비 코드를 되풀이하는 게 관례라 뺀다.

## baseline 키가 내용 해시가 아니라 파일 목록인 이유

내용 해시를 키로 쓰면 한 줄만 고쳐도 키가 달라져 **동결이 조용히 풀린다.** 동결해 둔 항목이
슬그머니 새 위반으로 바뀌거나, 반대로 고쳤는데도 동결 항목이 남는다. 파일 집합은 파일 내용을
고쳐도 바뀌지 않는다. 다른 baseline 들이 (slug, 파일) 쌍을 키로 쓰는 것도 같은 이유다.

## 전량 모드(레포 전체 검사) 전용

파일끼리 교차 비교하므로 레포 전체가 대상일 때만 의미가 있다. 작성 시점의 `--file` 은 파일 하나만
보므로 비교할 상대가 없다. 편집할 때마다 레포 전체를 다시 읽으면 훅이 느려져 사람이 훅을 꺼 버린다.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from kernel import facts, profile
from kernel.context import READ_ENC, ROOT, _rel, read_list
from kernel.gates.tests_pairing import is_test_path

DECL_BASELINE_FILE = "dup_decl_baseline.txt"
BLOCK_BASELINE_FILE = "dup_block_baseline.txt"

# 정규화 토큰 수 하한. 위임만 하는 짧은 함수(`return self.repo.get(x)` 9토큰)는 같아도 중복이 아니다. 이 레포 kernel/·tests/
# 약 1,000 선언에서 보정했다 — 10~20 사이 묶음은 전부 실제 복사본(`_is_str_seq` 27토큰, 테스트 도우미 셋)이고 8 이하에서
# 한 줄 위임이 묶이기 시작한다. 15 는 그 위임과 거리를 두면서 세 문장짜리 합계 루프(20토큰)를 잡는 값이다.
MIN_DECL_TOKENS = 15
BLOCK_WINDOW = 8          # 블록 중복의 연속 일치 줄 수
MIN_BLOCK_DISTINCT = 4    # 창(비교 구간) 안의 서로 다른 줄 수 하한. 같은 줄 반복(닫는 태그 나열)은 정보가 없다
MIN_BLOCK_CHARS = 96      # 토큰 몇 개짜리 짧은 줄만 모인 창 제외

_UI_COMMENT = ("//", "*", "/*", "{/*")
_WS = re.compile(r"\s+")
# `function X(...)` 와 `const X = (...) =>` 두 형태. 화살표는 인자 괄호가 있는 것만 본다 —
# `const x = v => ...` 는 본문이 식이라 선언 단위 비교 대상이 아니다.
_UI_DECL = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?"
    r"(?:function\s+(\w+)"
    r"|const\s+(\w+)\s*(?::[^=]+)?=\s*(?:async\s*)?\([^)]*\)\s*(?::[^=]*)?=>)")
# 문자열·템플릿 리터럴 안의 중괄호 때문에 짝이 어긋나도 끝없이 훑지 않도록 거는 상한.
_UI_SCAN_LIMIT = 400

_TOKEN = re.compile(r"[A-Za-z_$][\w$]*|\d[\w.]*|\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`|\S")
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
# 중괄호 언어의 지역 이름 선언 — const/let/var·구조분해·Go `:=`·화살표 인자·catch·`Type name =`(Java·C#)
_DECLARED = re.compile(
    r"\b(?:const|let|var|val)\s+(?:mut\s+)?([A-Za-z_$][\w$]*)"
    r"|\b(?:const|let|var)\s*[{\[]([^=;]*?)[}\]]\s*(?::[^=;]*)?="
    r"|\b([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*:="
    r"|\(([^()]*)\)\s*(?::[^=;{]*)?=>"
    r"|\b([A-Za-z_$][\w$]*)\s*=>"
    r"|\bcatch\s*\(\s*([A-Za-z_$][\w$]*)"
    r"|\b[A-Z]\w*(?:<[^<>;()]*>)?(?:\[\])*\s+([a-z]\w*)\s*[=;:]")
# 인자 목록에 섞여 나오는 키워드 — 지역 이름으로 바꾸지 않는다
_NOT_LOCAL = frozenset(("async await const let var val mut function func fn new return this self super "
                        "public private protected static final readonly override in of as is "
                        "true false null nil undefined void").split())


@dataclass(frozen=True)
class _Decl:
    """한 선언의 위치와 본문 지문. `digest` 가 같으면 같은 구현이다."""

    rel: str
    line: int
    end_line: int
    name: str
    digest: str


def fingerprint(code: str, local: set[str] | frozenset[str]) -> tuple[str, int]:
    """지역 이름(`local`)을 등장 순서 번호로 바꾼 토큰열과 토큰 수. 앞에 `.` 이 붙은 멤버는 같은 글자여도 그대로 둔다."""
    tokens = _TOKEN.findall(code)
    names: dict[str, str] = {}
    out: list[str] = []
    for index, token in enumerate(tokens):
        if token in local and not (index and tokens[index - 1] == "."):
            token = names.setdefault(token, f"v{len(names)}")
        out.append(token)
    return " ".join(out), len(out)


def _norm(line: str, marks: tuple[str, ...]) -> str | None:
    """공백을 한 칸으로 줄인 코드 줄. 빈 줄과 주석 줄은 None 이다 — 비교 창이 주석을 건너뛰어 이어지지 않도록 경계로 쓴다."""
    stripped = line.strip()
    if not stripped or stripped.startswith(marks):
        return None
    return _WS.sub(" ", stripped)


def _py_locals(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """함수 안에서 생긴 이름 — 인자·대입·for·with·컴프리헨션 대상·except 이름."""
    found: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.arg):
            found.add(sub.arg)
        elif isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
            found.add(sub.id)
        elif isinstance(sub, ast.ExceptHandler) and sub.name:
            found.add(sub.name)
    return found


def _py_tree(path: Path, text: str, rel: str) -> ast.AST | None:
    """구문 사실 캐시의 ast 를 쓴다 — 중첩 def·함수 길이 검사가 이미 같은 파일을 파싱했다."""
    found = facts.facts_for(path, rel) if profile.SYNTAX == "python" else None
    tree = found.extra.get("tree") if found is not None and not found.error else None
    try:
        return tree if isinstance(tree, ast.AST) else ast.parse(text)
    except (SyntaxError, ValueError):
        return None


def _py_decls(path: Path, text: str, rel: str) -> list[_Decl]:
    """Python 함수 선언. 독스트링을 뺀 본문을 `ast.unparse` 한 문자열의 지문이다."""
    tree = _py_tree(path, text, rel)
    if tree is None:
        return []
    found: list[_Decl] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = node.body[1:] if ast.get_docstring(node, clean=False) is not None else node.body
        if not body:
            continue
        digest, size = fingerprint(ast.unparse(ast.Module(body=body, type_ignores=[])), _py_locals(node))
        if size >= MIN_DECL_TOKENS:
            found.append(_Decl(rel, node.lineno, node.end_lineno or node.lineno, node.name, digest))
    return found


def _brace_locals(header: str, body: str) -> set[str]:
    """중괄호 언어의 지역 이름 — 머리 괄호 안의 이름 전부(인자·리시버, 타입 이름이 섞여도 일관되게 바뀌어 무해하다)와
    본문의 선언."""
    depth = 0
    inside: list[str] = []
    for char in header:
        depth += {"(": 1, ")": -1}.get(char, 0)
        inside.append(char if depth > 0 else " ")
    found = set(_IDENT.findall("".join(inside)))
    for match in _DECLARED.finditer(body):
        for group in match.groups():
            if group:
                found.update(_IDENT.findall(group))
    return found - _NOT_LOCAL


def _split_body(span: str) -> tuple[str, str] | None:
    """(머리, 본문). 본문은 인자 괄호가 닫힌 뒤 처음 여는 중괄호부터 마지막 닫는 중괄호까지다."""
    depth, seen = 0, False
    for index, char in enumerate(span):
        if char == "(":
            depth, seen = depth + 1, True
        elif char == ")":
            depth -= 1
        elif char == "{" and depth == 0 and seen:
            close = span.rfind("}")
            return (span[:index], span[index + 1:close]) if close > index else None
    return None


def _span_decls(path: Path, text: str, rel: str, marks: tuple[str, ...]) -> list[_Decl]:
    """Python 밖 서버 언어 — 구문 사실의 함수 범위. 분석기가 없으면 빈 목록이고 러너가 [TOOL] 로 먼저 끊는다."""
    found_facts = facts.facts_for(path, rel)
    if found_facts is None or found_facts.error:
        return []
    lines = text.split("\n")
    found: list[_Decl] = []
    for fn in found_facts.functions:
        kept = [line for line in lines[fn.line - 1:fn.end_line] if not line.strip().startswith(marks)]
        parts = _split_body(_BLOCK_COMMENT.sub(" ", "\n".join(kept)))
        if parts is None:
            continue
        digest, size = fingerprint(parts[1], _brace_locals(*parts))
        if size >= MIN_DECL_TOKENS:
            found.append(_Decl(rel, fn.line, fn.end_line, fn.name, digest))
    return found


def _brace_end(lines: list[str], start: int) -> int | None:
    """선언 여는 중괄호의 짝이 닫히는 줄 인덱스. 상한 안에 못 닫으면 None."""
    depth, opened = 0, False
    for index in range(start, min(len(lines), start + _UI_SCAN_LIMIT)):
        depth += lines[index].count("{") - lines[index].count("}")
        opened = opened or "{" in lines[index]
        if opened and depth <= 0:
            return index
    return None


def _ui_decls(text: str, rel: str) -> list[_Decl]:
    """화면 소스 선언. 중괄호 짝이 어긋나도 두 파일이 같은 본문을 내놓으면 원문이 같다는
    뜻이므로 중복 발견은 유효하다. 선언 경계가 틀릴 뿐 '중복이 있다'는 판정은 바뀌지 않는다."""
    lines = text.split("\n")
    found: list[_Decl] = []
    for index, line in enumerate(lines):
        matched = _UI_DECL.match(line)
        if not matched:
            continue
        end = _brace_end(lines, index)
        if end is None:
            continue
        body = "\n".join(n for n in (_norm(raw, _UI_COMMENT) for raw in lines[index + 1:end]) if n)
        digest, size = fingerprint(body, _brace_locals(line, body))
        if size < MIN_DECL_TOKENS:
            continue
        name = matched.group(1) or matched.group(2)
        found.append(_Decl(rel, index + 1, end + 1, name, digest))
    return found


def _cluster(decls: list[_Decl], gap: int) -> list[list[_Decl]]:
    """지문이 같은 묶음. 한 파일 안에서만 겹치면 시작 줄이 `gap` 이상 떨어져야 별개의 사본이다."""
    buckets: dict[str, list[_Decl]] = defaultdict(list)
    for decl in decls:
        buckets[decl.digest].append(decl)
    return [group for group in buckets.values()
            if len({d.rel for d in group}) >= 2
            or (len(group) >= 2 and max(d.line for d in group) - min(d.line for d in group) >= gap)]


def _key(rels: list[str]) -> str:
    return ",".join(sorted(set(rels)))


def _collapse(groups: list[list[_Decl]]) -> list[list[_Decl]]:
    """파일집합 키가 같은 묶음을 하나로 합친다.

    baseline 이 이 키 단위로 동결하므로, 묶음을 나눠 두면 한 항목이 여러 번 보고된다. 창이 한 줄씩
    밀리며 겹치면 같은 복붙이 조각마다 잡히고, 같은 두 파일이 공유하는 다른 선언도 같은 키를 갖는다.
    """
    merged: dict[str, list[_Decl]] = defaultdict(list)
    for group in groups:
        merged[_key([d.rel for d in group])] += group
    return sorted((sorted(g, key=lambda d: (d.rel, d.line)) for g in merged.values()),
                  key=lambda g: (-len({d.rel for d in g}), g[0].rel, g[0].line))


def _positions(group: list[_Decl], gap: int) -> str:
    """파일마다 서로 `gap` 이상 떨어진 시작 위치만 — 겹친 창을 전부 찍으면 한 줄이 수십 개가 된다."""
    kept: dict[str, list[int]] = defaultdict(list)
    for decl in sorted(group, key=lambda d: (d.rel, d.line)):
        lines = kept[decl.rel]
        if not lines or decl.line - lines[-1] >= gap:
            lines.append(decl.line)
    return ", ".join(f"{rel}:{line}" for rel, lines in sorted(kept.items()) for line in lines)


def _decl_violation(group: list[_Decl]) -> str:
    names = "/".join(sorted({d.name for d in group if d.name}))
    files = len({d.rel for d in group})
    where = (f"{files} files carry the same implementation. Move it to a shared module and keep one copy"
             if files > 1 else "declared twice in one file. Keep one and call it")
    return f"{group[0].rel}:{group[0].line}: identical declaration body ({names}) — {where}. At: {_positions(group, 1)}"


def _block_violation(group: list[_Decl]) -> str:
    files = len({d.rel for d in group})
    where = f"{files} files share the same chunk" if files > 1 else "repeated within one file"
    return (f"{group[0].rel}:{group[0].line}: identical {BLOCK_WINDOW}-line block — {where}. Extract a shared function. "
            f"At: {_positions(group, BLOCK_WINDOW)}")


def _block_decls(text: str, rel: str, marks: tuple[str, ...],
                 covered: list[tuple[int, int]]) -> list[_Decl]:
    """창 단위 지문. 선언 중복이 이미 잡은 범위 안에서 시작하는 창은 세지 않는다."""
    lines = text.split("\n")
    norm = [_norm(raw, marks) for raw in lines]
    found: list[_Decl] = []
    for index in range(len(norm) - BLOCK_WINDOW + 1):
        window = norm[index:index + BLOCK_WINDOW]
        if any(part is None for part in window):
            continue
        if len({*window}) < MIN_BLOCK_DISTINCT:
            continue
        if sum(len(part) for part in window) < MIN_BLOCK_CHARS:
            continue
        line_no = index + 1
        if any(start <= line_no <= end for start, end in covered):
            continue
        found.append(_Decl(rel, line_no, line_no + BLOCK_WINDOW - 1, "", "\n".join(window)))
    return found


def _sources(py_files: list[Path], ui_files: list[Path]) -> list[tuple[Path, str, str, bool]]:
    """(파일, 경로, 본문, 화면 여부) — 파일을 한 번만 읽어 두 검사가 함께 쓴다.

    일회성 스크립트(scratch)와 테스트는 뺀다. 재사용할 코드가 아니므로 중복이 있어도 정본을 다시 짠 신호가
    아니고, baseline 에 올려 봐야 없앨 수 없는 부채만 남는다.
    """
    scratch = profile.scratch()
    out: list[tuple[Path, str, str, bool]] = []
    for ui, files in ((False, py_files), (True, ui_files)):
        for path in files:
            rel = _rel(path)
            if (scratch and rel.startswith(scratch)) or is_test_path(rel):
                continue
            try:
                out.append((path, rel, path.read_text(encoding=READ_ENC), ui))
            except OSError:
                continue
    return out


def _analyze(py_files: list[Path],
             ui_files: list[Path]) -> tuple[list[list[_Decl]], list[list[_Decl]]]:
    """(선언 묶음, 블록 묶음). 검사와 baseline 재생성이 같은 계산을 공유한다.

    블록 검사가 선언 검사의 결과(covered)를 써야 해서 둘을 한 번에 돌린다. 같은 중복을 두 baseline 이
    함께 세면 "감소만 허용"이 모호해진다(한 번 고쳤는데 두 항목이 준다).
    """
    sources = _sources(py_files, ui_files)
    mark = profile.pattern("comment") or "#"       # 언어팩의 줄 주석. `#` 이 아니면 블록 주석의 줄머리도 주석이다
    marks = (mark,) if mark == "#" else (mark, "/*", "*")
    python = profile.SYNTAX == "python"

    decls: list[_Decl] = []
    for path, rel, text, ui in sources:
        if ui:
            decls += _ui_decls(text, rel)
        else:
            decls += _py_decls(path, text, rel) if python else _span_decls(path, text, rel, marks)
    decl_groups = _collapse(_cluster(decls, 1))

    covered: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for group in decl_groups:
        for decl in group:
            covered[decl.rel].append((decl.line, decl.end_line))

    blocks: list[_Decl] = []
    for _path, rel, text, ui in sources:
        blocks += _block_decls(text, rel, _UI_COMMENT if ui else marks, covered[rel])
    return decl_groups, _collapse(_cluster(blocks, BLOCK_WINDOW))


def check_duplication(py_files: list[Path],
                      ui_files: list[Path]) -> tuple[list[str], list[str]]:
    """(선언 중복 위반, 블록 중복 위반). 동결된 파일 집합은 건너뛴다."""
    decl_groups, block_groups = _analyze(py_files, ui_files)
    decl_frozen = read_list(ROOT / DECL_BASELINE_FILE)
    block_frozen = read_list(ROOT / BLOCK_BASELINE_FILE)
    decl_bad = [_decl_violation(g) for g in decl_groups
                if _key([d.rel for d in g]) not in decl_frozen]
    block_bad = [_block_violation(g) for g in block_groups
                 if _key([d.rel for d in g]) not in block_frozen]
    return decl_bad, block_bad


def emit_baselines(py_files: list[Path], ui_files: list[Path]) -> tuple[list[str], list[str]]:
    """현재 소스의 파일집합 키 전체. baseline 파일을 다시 만들 때 쓴다. 해결된 행을 지우는 갱신은 사람이 한다.

    키를 손으로 조립하다 틀리면 동결 항목이 실제 중복과 어긋나고, 어긋난 항목은 아무 경고 없이
    넘어간다. 그래서 정확한 키를 게이트가 직접 출력해 준다.
    """
    decl_groups, block_groups = _analyze(py_files, ui_files)
    decl_keys = [f"{_key([d.rel for d in g])}\t# {len({d.rel for d in g})} files "
                 f"{'/'.join(sorted({d.name for d in g if d.name}))}" for g in decl_groups]
    block_keys = [f"{_key([d.rel for d in g])}\t# {len({d.rel for d in g})} files"
                  for g in block_groups]
    return decl_keys, block_keys


if __name__ == "__main__":
    from kernel.context import app_code

    _py = [f for f in app_code(*profile.SOURCE_EXT)]
    _ui_dir = profile.layer("ui")
    _ui = [f for f in app_code(*profile.UI_EXT, under=_ui_dir)] if _ui_dir else []
    _decl, _block = emit_baselines(_py, _ui)
    print(f"--- {DECL_BASELINE_FILE} ({len(_decl)} found) ---")
    print("\n".join(_decl))
    print(f"--- {BLOCK_BASELINE_FILE} ({len(_block)} found) ---")
    print("\n".join(_block))
