"""kernel/retro.py — 관찰 기록에서 반복되는 패턴을 뽑아낸다. 판정은 하지 않는다.

  python -X utf8 -m kernel.retro                전 기간
  python -X utf8 -m kernel.retro --since 2026-08-10
  python -X utf8 -m kernel.retro --verdict <게이트> <violation|false_positive|wrong_rule|hold> --evidence <경로> [--file <경로>]

`--verdict` 는 사람이 내린 판정과 그 증거 위치를 `harness_retro_verdicts.jsonl` 에 한 줄 남긴다. 보고서의 「By gate」 가
게이트별 판정 수를 함께 보여 준다. 판정이 있다고 강등 후보를 만들지 않는다 — 적중 수나 판정 수로 게이트를 낮추는 일은
거절된 안이다(`dev/REJECTED.md` 「게이트 소거 기준」).

"게이트 X 가 파일 Y 에서 6번 걸렸다"까지가 여기 몫이다. 그게 규칙 위반인지 게이트 오탐인지
규칙 자체가 이 프로젝트에 안 맞는 건지는 증거로 판정한다 — 오탐은 고치기 전에 실패하는 재현 예, 규칙 위반은
사고 기록의 절, 틀린 규칙은 거절 기록의 행이 그 증거다(`.claude/skills/harness-retro/SKILL.md`).

**왜 판정을 자동화하지 않나.** 이 하네스에는 "더 좋아졌다"를 재는 기준(적합도 함수)이 없다. 골든
대조는 회귀만 잡을 뿐 개선은 재지 못한다. 그런 기준 없이 수정 제안과 채택을 자동화하면 결국 가장 쉬운
통과 방법인 면제 목록 늘리기로 흘러간다. 그 길은 `harness_gates/edit_surface.py` 가 막아 두고, 다른 래칫 파일이
늘어난 것은 `kernel.task finish` 가 `ratchet_growth` 관찰로 남겨 여기서 따로 센다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date

from kernel import trace
from kernel.context import READ_ENC, ROOT

HOT_SPOT_HITS = 3          # 같은 게이트가 같은 파일에서 이만큼 반복되면 지목한다
UNRECORDED = "unrecorded"  # level 필드가 생기기 전의 기록
RATCHET_KIND = "ratchet_growth"
VERDICTS_FILE = "harness_retro_verdicts.jsonl"
VERDICTS = ("violation", "false_positive", "wrong_rule", "hold")


def verdicts() -> list[dict[str, str]]:
    """기록된 회고 판정. 깨진 줄은 건너뛴다."""
    path = ROOT / VERDICTS_FILE
    if not path.exists():
        return []
    found: list[dict[str, str]] = []
    for line in path.read_text(encoding=READ_ENC).splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            found.append({key: str(value) for key, value in item.items()})
    return found


def verdict_note(gate: str, decisions: list[dict[str, str]] | None = None) -> str:
    """「By gate」 줄 끝에 붙는 판정 수. 판정이 없으면 빈 문자열이다."""
    counts = Counter(item.get("verdict", "?") for item in (verdicts() if decisions is None else decisions) if item.get("gate") == gate)
    return "   verdicts: " + ", ".join(f"{n} {name}" for name, n in sorted(counts.items())) if counts else ""


def record_verdict(gate: str, verdict: str, evidence: str, file: str = "", *, passing: str = "", failing: str = "",
                   retries: int | None = None, seconds: int | None = None) -> None:
    """판정 한 줄을 붙인다. 판정과 증거는 사람이 정한다 — 이 함수는 적기만 한다."""
    item = {"date": date.today().isoformat(), "gate": gate, "file": file, "verdict": verdict, "evidence": evidence}
    item.update({key: value for key, value in {"passing": passing, "failing": failing,
                                             "retries": retries, "seconds": seconds}.items() if value not in (None, "")})
    with (ROOT / VERDICTS_FILE).open("a", encoding="utf-8") as out:
        out.write(json.dumps(item, ensure_ascii=False) + "\n")


def since(stamped: str) -> list[dict[str, str]]:
    """마지막 회고 다음 날부터 관측된 사건. 회고 전에 처음 생겨 그 뒤에도 다시 관측된 사건은 포함한다(`last_ts`)."""
    items = trace.records()
    if not stamped:
        return items
    return [r for r in items if (r.get(trace.LAST) or r.get("ts", ""))[:10] > stamped]


def by_level(items: list[dict[str, str]]) -> Counter[str]:
    """막은 것(block)·worktree 알림(wip)·경고(warn)의 건수. level 이 없는 옛 기록은 따로 센다."""
    return Counter(item.get("level") or UNRECORDED for item in items)


def by_gate(items: list[dict[str, str]]) -> list[tuple[str, int, int, int, int, str, str]]:
    """(게이트, 사건 수, 관측 수, 그중 차단, 파일 수, 최초, 최근) — 사건 수 내림차순."""
    groups: dict[str, list[dict[str, str]]] = {}
    for item in items:
        if item.get("kind") == "gate":
            groups.setdefault(item.get("gate") or "?", []).append(item)
    rows = [(gate,
             len(hits),
             sum(int(hit.get(trace.COUNT) or 1) for hit in hits),
             sum(1 for hit in hits if hit.get("level") == "block"),
             len({hit.get("file", "") for hit in hits if hit.get("file")}),
             min(hit.get("ts", "") for hit in hits)[:10],
             max(hit.get(trace.LAST) or hit.get("ts", "") for hit in hits)[:10])
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
    counts = Counter(item.get("kind") or "?" for item in items if item.get("kind") not in ("gate", RATCHET_KIND))
    return sorted(counts.items(), key=lambda row: (-row[1], row[0]))


def ratchet_growth(items: list[dict[str, str]]) -> list[str]:
    """끝내기가 관찰한 래칫 증가 행(`kernel/baseline.py` `growth`). 하나라도 있으면 건수와 무관하게 회고 대상이다."""
    return [item.get("msg", "") for item in items if item.get("kind") == RATCHET_KIND]


def _print_report(items: list[dict[str, str]]) -> None:
    decisions = verdicts()
    sessions = len({item.get("sid", "") for item in items})
    first = min(item.get("ts", "") for item in items)[:10]
    last = max(item.get("ts", "") for item in items)[:10]
    print(f"[RETRO] {len(items)} trace records · {sessions} sessions · {first} ~ {last}\n")
    levels = ", ".join(f"{count} {level}" for level, count in sorted(by_level(items).items()))
    print(f"By level: {levels}\n")

    gates = by_gate(items)
    if gates:
        print("By gate (events · times the same state was observed — not fix attempts)")
        for gate, hits, seen, blocked, files, gate_first, gate_last in gates:
            print(f"  {hits:>4}  {gate:<20} {seen} observed   {blocked} blocked   {files} files   "
                  f"{gate_first} ~ {gate_last}{verdict_note(gate, decisions)}")
        print()

    _print_evidence(items, decisions, [row[0] for row in gates[:5]])

    spots = hot_spots(items)
    if spots:
        print(f"Hot spots (same gate, same file, {HOT_SPOT_HITS}+ times)")
        for gate, path, hits in spots:
            print(f"  {hits:>4}  {gate:<20} {path}")
        print()

    kinds = by_kind(items)
    if kinds:
        print("Friction outside gates")
        for kind, hits in kinds:
            print(f"  {hits:>4}  {kind}")
        print()

    grown = ratchet_growth(items)
    if grown:
        print(f"Exemption growth ({RATCHET_KIND}) — {len(grown)} rows added to a ratchet file or exclude list")
        for row in grown:
            print(f"  {row}")
        print()


def _print_evidence(items: list[dict[str, str]], decisions: list[dict[str, str]], gates: list[str]) -> None:
    print("Evidence for review (top 5 gates; recorded judgments; observations are not retries or false-positive rates)")
    for gate in gates:
        matching = [item for item in decisions if item.get("gate") == gate]
        if not matching:
            sample = next((item.get("msg", "") for item in items if item.get("gate") == gate), "")
            print(f"  {gate}: unjudged; sample: {' '.join(sample.split())[:240]}")
        for item in matching[-3:]:
            print(f"  {gate}: {item.get('verdict', '?')}; evidence: {item.get('evidence', '?')}")
            print(f"    passing: {item.get('passing') or 'not linked'}; failing: {item.get('failing') or 'not linked'}")
            cost = [f"{item['retries']} retries"] if "retries" in item else []
            if "seconds" in item:
                cost.append(f"{item['seconds']}s")
            if cost:
                print(f"    manual measurement: {', '.join(cost)}")
    print()


def _case_errors(passing: str, failing: str, retries: int | None, seconds: int | None) -> list[str]:
    errors = []
    if bool(passing) != bool(failing):
        errors.append("link both --passing and --failing cases")
    for case in (passing, failing):
        if not case:
            continue
        path = (ROOT / case.split("::", 1)[0].split("#", 1)[0]).resolve()
        if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
            errors.append(f"case does not name an existing file inside this checkout: {case}")
    if any(value is not None and value < 0 for value in (retries, seconds)):
        errors.append("manual retries and seconds must be nonnegative")
    return errors


def main(argv: list[str]) -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(prog="kernel.retro", allow_abbrev=False)
    parser.add_argument("--since", default="", help="only trace records after this date (e.g. 2026-08-10)")
    parser.add_argument("--verdict", nargs=2, metavar=("GATE", "VERDICT"), help=f"record a verdict: {', '.join(VERDICTS)}")
    parser.add_argument("--evidence", default="", help="path of the evidence (test, CASES entry, LESSONS or REJECTED row)")
    parser.add_argument("--file", default="", help="the file the verdict is about, if any")
    parser.add_argument("--passing", default="", help="normal case that must pass (path, optionally ::test or #anchor)")
    parser.add_argument("--failing", default="", help="actual violation case that the gate must catch")
    parser.add_argument("--retries", type=int, help="manually measured retries; never inferred from trace repetitions")
    parser.add_argument("--seconds", type=int, help="manually measured time spent resolving this event")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    if args.verdict:
        gate, verdict = args.verdict
        if verdict not in VERDICTS or not args.evidence:
            print(f"[RETRO] a verdict is one of {', '.join(VERDICTS)} and needs --evidence <path>", file=sys.stderr)
            return 1
        errors = _case_errors(args.passing, args.failing, args.retries, args.seconds)
        if errors:
            print("[RETRO] " + "; ".join(errors), file=sys.stderr)
            return 1
        record_verdict(gate, verdict, args.evidence, args.file, passing=args.passing, failing=args.failing,
                       retries=args.retries, seconds=args.seconds)
        print(f"[RETRO] recorded {verdict} for {gate} in {VERDICTS_FILE} — commit it with the evidence.")
        return 0
    items = since(args.since)
    if not items:
        print("No trace records — hooks have not blocked anything yet, or the trace is empty.")
        return 0

    _print_report(items)
    print("No verdict here. Evidence is the verdict: a false positive needs a reproduction that fails before the fix "
          "(a hook CASES entry or a test), a rule violation cites its LESSONS section, a wrong rule leaves a REJECTED row.")
    print("Growing the exemption list is not a fix — the edit-surface ratchet only lets that list shrink, "
          f"and {RATCHET_KIND} rows above show where other ratchets grew.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
