"""kernel/pack_check.py — 언어팩이 1급인지, 즉 사실 기반 게이트가 그 언어에서 실제로 동작하는지 판정한다.

  python -X utf8 -m kernel.pack_check [<LANG>]     기본은 프로파일의 LANG. 미검증이 하나라도 있으면 exit 1

팩은 선언일 뿐이라 선언만으로는 1급이 되지 않는다. 팩의 FIXTURES 를 그 팩의 분석기로 사실로 바꾼 뒤
사실 기반 게이트의 판정 헬퍼(`kernel/gates/core.py`)에 넣는다. 위반 예제는 잡히고 통과 예제는
안 잡혀야 [1급] 이다. 초기 설정에서 스택을 맞추는 작업은 이 출력에 [미검증] 이 하나도 없어야 끝난다.

  [1급]    위반 예제 검출·통과 예제 통과 (사실 종류는 기대한 값 산출)
  [미검증] 예제 없음 · 분석기 없음 · 예제 결과가 어긋남
  [N/A]    팩이 NOT_APPLICABLE 로 선언한 게이트 — 손실이 아니다

FIXTURES 서식 — 값은 소스 문자열이다.

  "files"        {"go.mod": "…"}                        분석기가 읽을 보조 파일. 모듈 키 규칙이 쓴다
  게이트 slug    {"violating": "…", "passing": "…"}     closures · func_limit · type_hints
  사실 종류      {"source": "…", "expect": [...]}       imports(모듈 키) · top_symbols(이름). expect 가 부분집합이면 통과
"""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path

from kernel import facts, lang, profile
from kernel.gates import core

GATE_SLUGS = ("closures", "func_limit", "type_hints")
FACT_KINDS = ("imports", "top_symbols")
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
    """팩 하나의 slug 별 판정. 보조 파일은 임시 루트에 쓰고 예제는 메모리에서 분석한다."""
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


def report(name: str, pack: Mapping[str, object], verdicts: list[Verdict]) -> str:
    engine = "표준 ast" if pack.get("SYNTAX") == "python" else "tree-sitter"
    lines = [f"언어팩 {name} (SYNTAX {pack.get('SYNTAX')}) — 분석기: {engine}"]
    lines += [f"[{grade}] {slug} — {reason}" for grade, slug, reason in verdicts]
    counts = {grade: sum(1 for item in verdicts if item[0] == grade) for grade in ("1급", "미검증", "N/A")}
    summary = " · ".join(f"{grade} {count}" for grade, count in counts.items())
    verdict = "1급 팩" if not counts["미검증"] else "미검증이 남아 있으면 1급 팩이 아니다"
    lines.append(f"{summary} — {verdict}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(errors="replace")
    name = argv[0] if argv else profile.LANG
    if not name:
        print("언어팩 이름이 없다 — 인자로 주거나 프로파일에 LANG 을 적는다")
        return 2
    try:
        pack = lang.load(name)
    except ValueError as exc:
        print(exc)
        return 2
    verdicts = assess(pack)
    print(report(name, pack, verdicts))
    return 1 if any(grade == "미검증" for grade, _slug, _reason in verdicts) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
