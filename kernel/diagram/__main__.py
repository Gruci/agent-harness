"""python -X utf8 -m kernel.diagram <명령> — 다이어그램 엔진 CLI.

  validate <타입> <정본.json>                 진단만 한다. 고칠 때마다 다시 돌린다
  deliver  <타입> <정본.json> [출력.html]     최종 렌더 + 영수증
  compare  <base.json> <head.json> <출력.html>  architecture 델타
  rules                                        훅 배선과 게이트 목록으로 규칙 지도를 만들고 deliver 한다
  svg      <정본.json>                          렌더된 HTML 에서 독립 SVG 만 다시 뽑기
  doctor                                       node·엔진 상태

exit 코드는 엔진 결과를 따른다. 0 은 통과, 1 은 진단 있음, 2 는 인자 오류나 도구 없음이다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from kernel import diagram

USAGE = __doc__ or ""


def _report(receipt: dict[str, object]) -> int:
    if receipt.get("tool_missing"):
        print(f"[TOOL] {receipt['tool_missing']} 없음 — 렌더도 진단도 할 수 없다. node 를 설치하고 다시 돌려라.")
        return 2
    validation = receipt.get("validation")
    if isinstance(validation, dict):
        print(f"검증 {validation.get('checksPassed')}/{validation.get('checkCount')} "
              f"{validation.get('compositionProfile')} · 오류 {validation.get('errors')} · "
              f"경고 {validation.get('warnings')}")
    for line in diagram.diagnostics_lines(receipt):
        print(f"   - {line}")
    if receipt.get("ok"):
        print("[OK] 엔진 통과")
        return 0
    print("[FAIL] 엔진 진단 — 각 진단의 subject · evidence · supportedFixes 만 보고 고친 뒤 다시 돌려라")
    return 1


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    command, rest = argv[0], argv[1:]
    if command == "doctor":
        status = diagram.doctor()
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0 if status["ok"] else 2
    if command == "validate" and len(rest) == 2 and rest[0] in diagram.TYPES:
        return _report(diagram.validate(rest[0], Path(rest[1]).resolve()))
    if command == "deliver" and len(rest) in (2, 3) and rest[0] in diagram.TYPES:
        output = Path(rest[2]).resolve() if len(rest) == 3 else None
        receipt = diagram.deliver(rest[0], Path(rest[1]).resolve(), output)
        code = _report(receipt.get("engine", receipt) if receipt.get("ok") else receipt)
        if code == 0:
            print(f"영수증: {diagram.receipt_path(Path(rest[1]).resolve()).name} · revision {receipt.get('revision')}")
            undefined = receipt.get("svg_undefined_vars") or []
            print(f"SVG: {diagram.output_path(Path(rest[1]).resolve()).with_suffix('.svg').name}"
                  + (f" — 정의 안 된 CSS 변수: {' '.join(str(v) for v in undefined)}" if undefined else ""))
        return code
    if command == "rules" and not rest:
        from kernel.diagram import rules
        source = rules.write()
        print(f"생성: {source.relative_to(diagram.ROOT).as_posix()}")
        return main(["deliver", "workflow", str(source)])
    if command == "svg" and len(rest) == 1:
        from kernel.diagram import svg
        source = Path(rest[0]).resolve()
        undefined = svg.export(diagram.output_path(source), diagram.output_path(source).with_suffix(".svg"))
        print(f"SVG: {diagram.output_path(source).with_suffix('.svg').name}"
              + (f" — 정의 안 된 CSS 변수 {len(undefined)}개: {' '.join(sorted(undefined))}" if undefined else ""))
        return 1 if undefined else 0
    if command == "compare" and len(rest) == 3:
        return _report(diagram.compare(Path(rest[0]).resolve(), Path(rest[1]).resolve(),
                                       Path(rest[2]).resolve()))
    print(f"인자 오류: {' '.join(argv)}\n{USAGE}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
