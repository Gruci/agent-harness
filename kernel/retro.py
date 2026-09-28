"""kernel/retro.py — 관찰 기록에서 반복되는 패턴을 뽑아낸다. 판정은 하지 않는다.

  python -X utf8 -m kernel.retro                전 기간
  python -X utf8 -m kernel.retro --since 2026-08-10

"게이트 X 가 파일 Y 에서 6번 걸렸다"까지가 여기 몫이다. 그게 규칙 위반인지 게이트 오탐인지
규칙 자체가 이 프로젝트에 안 맞는 건지는 사람이 정한다.

**왜 판정을 자동화하지 않나.** 이 하네스에는 "더 좋아졌다"를 재는 기준(적합도 함수)이 없다. 골든
대조는 회귀만 잡을 뿐 개선은 재지 못한다. 그런 기준 없이 수정 제안과 채택을 자동화하면 결국 가장 쉬운
통과 방법인 면제 목록 늘리기로 흘러간다. 그 길은 `harness_gates/edit_surface.py` 가 막아 둔다.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from kernel import trace

HOT_SPOT_HITS = 3          # 같은 게이트가 같은 파일에서 이만큼 반복되면 지목한다


def since(stamped: str) -> list[dict[str, str]]:
    """마지막 회고 다음 날부터의 기록. 회고 당일 것은 이미 읽은 것으로 본다."""
    items = trace.records()
    if not stamped:
        return items
    return [r for r in items if r.get("ts", "")[:10] > stamped]


def count_since(stamped: str) -> int:
    """정비 알림 판정에 쓰는 값. 마지막 회고 뒤에 훅이 막은 횟수다."""
    return len(since(stamped))


def by_gate(items: list[dict[str, str]]) -> list[tuple[str, int, int, str, str]]:
    """(게이트, 건수, 파일 수, 최초, 최근) — 건수 내림차순."""
    groups: dict[str, list[dict[str, str]]] = {}
    for item in items:
        if item.get("kind") == "gate":
            groups.setdefault(item.get("gate") or "?", []).append(item)
    rows = [(gate,
             len(hits),
             len({hit.get("file", "") for hit in hits if hit.get("file")}),
             min(hit.get("ts", "") for hit in hits)[:10],
             max(hit.get("ts", "") for hit in hits)[:10])
            for gate, hits in groups.items()]
    return sorted(rows, key=lambda row: (-row[1], row[0]))


def hot_spots(items: list[dict[str, str]]) -> list[tuple[str, str, int]]:
    """같은 게이트가 같은 파일에서 반복해서 걸린 지점. 그 파일의 관례가 아직 없거나 게이트가 오탐을 내는 경우다."""
    counts = Counter((item.get("gate") or "?", item["file"]) for item in items
                     if item.get("kind") == "gate" and item.get("file"))
    return sorted(((gate, path, n) for (gate, path), n in counts.items() if n >= HOT_SPOT_HITS),
                  key=lambda row: (-row[2], row[0], row[1]))


def by_kind(items: list[dict[str, str]]) -> list[tuple[str, int]]:
    """게이트 판정이 아닌 차단(게이트 밖 마찰)의 종류별 건수. 파일 통째 읽기, 너무 긴 에이전트 반환, 남은 과업 파일, 원격 미설정, 검사 실행 실패 등이다."""
    counts = Counter(item.get("kind") or "?" for item in items if item.get("kind") != "gate")
    return sorted(counts.items(), key=lambda row: (-row[1], row[0]))


def _print_report(items: list[dict[str, str]]) -> None:
    sessions = len({item.get("sid", "") for item in items})
    first = min(item.get("ts", "") for item in items)[:10]
    last = max(item.get("ts", "") for item in items)[:10]
    print(f"[회고] 관찰 {len(items)}건 · 세션 {sessions}개 · {first} ~ {last}\n")

    gates = by_gate(items)
    if gates:
        print("게이트별")
        for gate, hits, files, gate_first, gate_last in gates:
            print(f"  {hits:>4}  {gate:<20} 파일 {files}개   {gate_first} ~ {gate_last}")
        print()

    spots = hot_spots(items)
    if spots:
        print(f"반복 지점 (같은 게이트·같은 파일 {HOT_SPOT_HITS}회 이상)")
        for gate, path, hits in spots:
            print(f"  {hits:>4}  {gate:<20} {path}")
        print()

    kinds = by_kind(items)
    if kinds:
        print("게이트 밖 마찰")
        for kind, hits in kinds:
            print(f"  {hits:>4}  {kind}")
        print()


def main(argv: list[str]) -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(prog="kernel.retro", allow_abbrev=False)
    parser.add_argument("--since", default="", help="이 날짜 이후 관찰만 (예: 2026-08-10)")
    try:
        items = since(parser.parse_args(argv).since)
    except SystemExit as exc:
        return int(exc.code or 0)
    if not items:
        print("관찰 없음 — 훅이 아직 아무것도 막지 않았거나 기록이 비어 있다.")
        return 0

    _print_report(items)
    print("판정은 여기서 하지 않는다. 각 패턴이 규칙 위반인지, 게이트 오탐인지, "
          "규칙 자체가 이 프로젝트에 안 맞는지는 사람이 정한다.")
    print("면제 목록을 늘리는 것은 해결책이 아니다 — 면제 목록이 줄어들기만 하게 막는 게이트(편집 표면 래칫)가 그 길을 닫아 두었다.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
