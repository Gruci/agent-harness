"""kernel/pack_check.py — 팩이 1급인지, 즉 그 팩의 선언으로 게이트가 실제로 동작하는지 판정한다.

  python -X utf8 -m kernel.pack_check [<이름> ...]   기본은 프로파일의 LANG 과 FRAMEWORK 전부. 미검증이 하나라도 있으면 exit 1

팩은 선언일 뿐이라 선언만으로는 1급이 되지 않는다. 팩의 FIXTURES 를 실제 판정 헬퍼에 넣어 위반 예제는
잡히고 통과 예제는 안 잡혀야 [1급] 이다. 초기 설정에서 스택을 맞추는 작업은 이 출력에 [미검증] 이 하나도 없어야 끝난다.

  [1급]    위반 예제 검출·통과 예제 통과 (사실 종류는 기대한 값 산출)
  [미검증] 예제 없음 · 분석기나 도구 없음 · 예제 결과가 어긋남
  [N/A]    팩이 NOT_APPLICABLE 로 선언한 게이트 — 손실이 아니다

언어팩은 예제를 그 팩의 분석기로 사실로 바꿔 사실 기반 게이트(`kernel/gates/core.py`)에 넣는다.
프레임워크팩은 서버팩이면 라우트 인식(`kernel/gates/orphan_api.py`)을, 화면팩이면 화면 게이트 6종을
ESLint 실측(`kernel/linters.py`)으로 판정한다. ESLint 가 없는 환경에서는 화면 예제가 [미검증] 이다.

FIXTURES 서식 — 값은 소스 문자열이다.

  언어팩
    "files"        {"go.mod": "…"}                        분석기가 읽을 보조 파일. 모듈 키 규칙이 쓴다
    게이트 slug    {"violating": "…", "passing": "…"}     closures · func_limit · type_hints
    사실 종류      {"source": "…", "expect": [...]}       imports(모듈 키) · top_symbols(이름). expect 가 부분집합이면 통과
  서버팩
    "orphan_api"   {"route": "…", "consumer": "…", "stranger": "…"}
                   route 에서 라우트가 정확히 하나 인식되고, consumer 는 그 라우트를 쓰며, stranger 는 안 써야 한다
  화면팩
    화면 slug      {"violating": "…", "passing": "…"}     ts_any · raw_fetch · hex_literal · responsive · browser_api · hash_nav
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path

from kernel import facts, framework, lang, linters, profile
from kernel.gates import core, orphan_api

GATE_SLUGS = ("closures", "func_limit", "type_hints")
FACT_KINDS = ("imports", "top_symbols")
SERVER_SLUGS = ("orphan_api",)
UI_SLUGS = linters.UI_SLUGS
_NEEDS = {"closures": "nesting", "func_limit": "functions", "type_hints": "types"}
_JUDGE: dict[str, Callable[[facts.FileFacts], list]] = {
    "closures": core.nested_pairs, "func_limit": core.long_functions, "type_hints": core.untyped_functions,
}

Verdict = tuple[str, str, str]     # (등급, slug, 사유)


def _judge_gate(slug: str, example: Mapping[str, object], analyzer: facts.Analyzer, ext: str) -> Verdict:
    if not all(isinstance(example.get(case), str) for case in ("violating", "passing")):
        return ("미검증", slug, "예제 서식 오류 — violating·passing 소스 문자열이 필요")
    for case, expected in (("violating", True), ("passing", False)):
        found = analyzer.analyze(str(example[case]), f"{slug}_{case}{ext}")
        if found.error:
            return ("미검증", slug, f"{case} 예제 파싱 실패: {found.error}")
        if bool(_JUDGE[slug](found)) != expected:
            return ("미검증", slug, "위반 예제가 안 잡힘" if expected else "통과 예제가 잡힘")
    return ("1급", slug, "위반 예제 검출·통과 예제 통과")


def _judge_kind(kind: str, example: Mapping[str, object], analyzer: facts.Analyzer, ext: str) -> Verdict:
    source, expect = example.get("source"), example.get("expect")
    if not isinstance(source, str) or not isinstance(expect, (list, tuple)) or not expect:
        return ("미검증", kind, "예제 서식 오류 — source 문자열과 expect 목록이 필요")
    found = analyzer.analyze(source, str(example.get("path") or f"{kind}{ext}"))
    if found.error:
        return ("미검증", kind, f"예제 파싱 실패: {found.error}")
    have = ({item.module for item in found.imports if item.module} if kind == "imports"
            else set(found.top_symbols))
    missing = [str(name) for name in expect if name not in have]
    if missing:
        return ("미검증", kind, f"기대한 값이 안 나옴: {', '.join(missing)}")
    return ("1급", kind, f"{', '.join(str(name) for name in expect)} 산출")


def assess(pack: Mapping[str, object]) -> list[Verdict]:
    """언어팩 하나의 slug 별 판정. 보조 파일은 임시 루트에 쓰고 예제는 메모리에서 분석한다."""
    fixtures = dict(pack.get("FIXTURES") or {})   # type: ignore[call-overload]  # lang.load 가 매핑임을 검증했다
    support = fixtures.pop("files", None) or {}
    not_applicable = dict(pack.get("NOT_APPLICABLE") or {})   # type: ignore[call-overload]
    ext_patterns = tuple(pack.get("EXT") or ())   # type: ignore[call-overload]
    ext = str(ext_patterns[0]).lstrip("*") if ext_patterns else ""
    verdicts: list[Verdict] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rel, body in support.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(body), encoding="utf-8")
        analyzer, reason = facts.analyzer_for_pack(pack, root)
        for slug in GATE_SLUGS + FACT_KINDS:
            if slug in not_applicable:
                verdicts.append(("N/A", slug, str(not_applicable[slug])))
                continue
            example = fixtures.get(slug)
            if not isinstance(example, Mapping):
                verdicts.append(("미검증", slug, "예제 없음"))
            elif analyzer is None:
                verdicts.append(("미검증", slug, reason))
            elif _NEEDS.get(slug, slug) not in analyzer.kinds:
                verdicts.append(("미검증", slug, f"분석기가 {_NEEDS.get(slug, slug)} 사실을 내지 않음"))
            elif slug in GATE_SLUGS:
                verdicts.append(_judge_gate(slug, example, analyzer, ext))
            else:
                verdicts.append(_judge_kind(slug, example, analyzer, ext))
    return verdicts


# ── 프레임워크팩 ─────────────────────────────────────────────────────────────

def _judge_route(example: Mapping[str, object], pattern: str) -> Verdict:
    """서버팩의 라우트 예제. 게이트와 같은 헬퍼(`orphan_api`)로 인식·소비를 판정한다."""
    slug = "orphan_api"
    if not all(isinstance(example.get(case), str) for case in ("route", "consumer", "stranger")):
        return ("미검증", slug, "예제 서식 오류 — route·consumer·stranger 소스 문자열이 필요")
    routes = orphan_api.routes_in(str(example["route"]), pattern)
    if len(routes) != 1:
        return ("미검증", slug, f"route 예제에서 라우트 {len(routes)}개 인식 — 정확히 하나여야 함")
    route = routes[0][1]
    if len(orphan_api.literal_prefix(route)) < orphan_api.MIN_PREFIX_LEN:
        return ("미검증", slug, f"라우트 `{route}` 의 고정 접두가 너무 짧아 비교 불가")
    if not orphan_api.consumed(route, str(example["consumer"])):
        return ("미검증", slug, "consumer 예제가 소비로 안 잡힘")
    if orphan_api.consumed(route, str(example["stranger"])):
        return ("미검증", slug, "stranger 예제가 소비로 잡힘")
    return ("1급", slug, f"라우트 `{route}` 인식·consumer 통과·stranger 검출")


def _assess_server(pack: Mapping[str, object]) -> list[Verdict]:
    fixtures = pack.get("FIXTURES") or {}
    verdicts: list[Verdict] = []
    for slug in SERVER_SLUGS:
        example = fixtures.get(slug)   # type: ignore[union-attr]  # framework.load_one 이 매핑임을 검증했다
        if not isinstance(example, Mapping):
            verdicts.append(("미검증", slug, "예제 없음"))
        else:
            verdicts.append(_judge_route(example, str(pack["ROUTE_PATTERN"])))
    return verdicts


def _lint_examples(pack: Mapping[str, object], npm_dir: Path,
                   examples: dict[str, Mapping[str, object]]) -> dict[str, list[str]]:
    """예제를 npm 프로젝트 안의 임시 폴더에 쓰고 ESLint 를 한 번 돌린다. ESLint 는 cwd 밖 파일을 무시하므로 밖에 둘 수 없다."""
    ext = str(tuple(pack["UI_EXT"])[0]).lstrip("*")   # type: ignore[arg-type]  # framework.load_one 이 목록임을 검증했다
    scratch = Path(tempfile.mkdtemp(prefix="harness_pack_check_", dir=npm_dir))
    try:
        targets: list[Path] = []
        for slug, example in examples.items():
            for case in ("violating", "passing"):
                target = scratch / f"{slug}_{case}{ext}"
                target.write_text(str(example[case]), encoding="utf-8")
                targets.append(target)
        return linters.eslint_report(npm_dir, targets, {}, "토큰", pack)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _assess_ui(pack: Mapping[str, object]) -> list[Verdict]:
    """화면팩. 규칙 본문은 ESLint 설정 한 벌이라 실측이 판정이다 — 실행 파일이 없으면 전부 [미검증] 이다."""
    fixtures = pack.get("FIXTURES") or {}
    examples: dict[str, Mapping[str, object]] = {}
    verdicts: list[Verdict] = []
    for slug in UI_SLUGS:
        example = fixtures.get(slug)   # type: ignore[union-attr]  # framework.load_one 이 매핑임을 검증했다
        if not isinstance(example, Mapping):
            verdicts.append(("미검증", slug, "예제 없음"))
        elif not all(isinstance(example.get(case), str) for case in ("violating", "passing")):
            verdicts.append(("미검증", slug, "예제 서식 오류 — violating·passing 소스 문자열이 필요"))
        else:
            examples[slug] = example
    if not examples:
        return verdicts
    npm_dir = linters.ui_npm_dir()
    if npm_dir is None or not linters.ui_eslint_bin(npm_dir):
        return verdicts + [("미검증", slug, f"eslint 미설치 — {pack['ESLINT_INSTALL']}") for slug in examples]
    found = _lint_examples(pack, npm_dir, examples)
    for slug in examples:
        hits = found.get(slug, [])
        if not any(f"{slug}_violating" in hit for hit in hits):
            verdicts.append(("미검증", slug, "위반 예제가 안 잡힘"))
        elif any(f"{slug}_passing" in hit for hit in hits):
            verdicts.append(("미검증", slug, "통과 예제가 잡힘"))
        else:
            verdicts.append(("1급", slug, "위반 예제 검출·통과 예제 통과"))
    return verdicts


def assess_framework(pack: Mapping[str, object]) -> list[Verdict]:
    """프레임워크팩 하나의 slug 별 판정. 역할이 어느 게이트를 재는지 정한다."""
    return _assess_server(pack) if pack["ROLE"] == "server" else _assess_ui(pack)


# ── 보고 ─────────────────────────────────────────────────────────────────────

def _summary(verdicts: list[Verdict]) -> str:
    counts = {grade: sum(1 for item in verdicts if item[0] == grade) for grade in ("1급", "미검증", "N/A")}
    summary = " · ".join(f"{grade} {count}" for grade, count in counts.items())
    verdict = "1급 팩" if not counts["미검증"] else "미검증이 남아 있으면 1급 팩이 아니다"
    return f"{summary} — {verdict}"


def report(name: str, pack: Mapping[str, object], verdicts: list[Verdict]) -> str:
    engine = {"python": "표준 ast", "treesitter": "tree-sitter", "command": "외부 명령"}.get(
        lang.analyzer_kind(dict(pack)) or "", "없음")
    lines = [f"언어팩 {name} (SYNTAX {pack.get('SYNTAX')}) — 분석기: {engine}"]
    lines += [f"[{grade}] {slug} — {reason}" for grade, slug, reason in verdicts]
    lines.append(_summary(verdicts))
    return "\n".join(lines)


def report_framework(name: str, pack: Mapping[str, object], verdicts: list[Verdict]) -> str:
    judge = "라우트 인식(kernel/gates/orphan_api.py)" if pack["ROLE"] == "server" else "ESLint 실측(kernel/linters.py)"
    lines = [f"프레임워크팩 {name} (역할 {pack['ROLE']}) — 판정: {judge}"]
    lines += [f"[{grade}] {slug} — {reason}" for grade, slug, reason in verdicts]
    lines.append(_summary(verdicts))
    return "\n".join(lines)


def _assess_named(name: str) -> tuple[str, list[Verdict]] | None:
    """이름 하나를 언어팩, 프레임워크팩 순으로 찾아 (보고문, 판정). 어느 쪽에도 없으면 None."""
    if lang.find_pack("언어팩", lang.SHIPPED_DIR, lang.ROOT / lang.PROJECT_DIR, name) is not None:
        pack = lang.load(name)
        verdicts = assess(pack)
        return report(name, pack, verdicts), verdicts
    if framework.exists(name):
        framework_pack = framework.load_one(name)
        verdicts = assess_framework(framework_pack)
        return report_framework(name, framework_pack, verdicts), verdicts
    return None


def main(argv: list[str]) -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(errors="replace")
    names = argv or [name for name in (profile.LANG, *profile.FRAMEWORK) if name]
    if not names:
        print("팩 이름이 없다 — 인자로 주거나 프로파일에 LANG·FRAMEWORK 를 적는다")
        return 2
    unverified = False
    for index, name in enumerate(names):
        try:
            assessed = _assess_named(name)
        except ValueError as exc:
            print(exc)
            return 2
        if assessed is None:
            print(f"팩을 찾을 수 없음: {name}")
            return 2
        text, verdicts = assessed
        print(("\n" if index else "") + text)
        unverified = unverified or any(grade == "미검증" for grade, _slug, _reason in verdicts)
    return 1 if unverified else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
