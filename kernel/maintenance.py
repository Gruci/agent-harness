"""kernel/maintenance.py — 정비가 필요한 시점을 하네스가 스스로 판단한다.

  python -X utf8 -m kernel.maintenance              지금 밀린 정비를 출력
  python -X utf8 -m kernel.maintenance --stamp <이름>  방금 돌린 정비를 기록

월간 감사류(문서 드리프트·과설계·부채 수확·사용자 관점 검수)는 "한 달에 한 번"이라고 문서에 적어두면
아무도 안 한다. 사용자가 명령어를 외우고 때를 판단해야 하기 때문이다. 그건 하네스가 할 일이다.

이 모듈은 **정비할 때가 됐는지 재는 일**만 한다. 무엇을 볼지는 각 스킬이 알고, 임계치는
프로파일이 조정할 수 있다. 판정 근거는 모두 레포의 실제 상태다. 커밋 수, 바뀐 파일, 남은 `debt:` 표시를 센다.

기록은 `harness_maintenance.json` 이고 커밋한다. 세션과 머신이 바뀌어도 "언제 마지막으로
돌았는지"가 공유돼야 주기가 성립한다.
"""

from __future__ import annotations

import functools
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from kernel import profile, retro, runner
from kernel.context import READ_ENC, ROOT

LEDGER = ROOT / "harness_maintenance.json"

# 기본 임계치. 프로파일의 MAINTENANCE 가 항목별로 덮어쓴다.
DEFAULTS: dict[str, dict[str, int]] = {
    "md-audit":            {"commits": 80, "days": 30},
    "code-audit":          {"commits": 150, "days": 60},
    "code-debt":           {"markers": 12},
    "review-loop":         {"ui_changes": 12},
    # 임계 25 의 근거: 초반엔 하루에도 여러 번 걸리므로 10 이면 상시 알림이 되고, 100 이면
    # 관례가 굳은 뒤에야 읽는다. "몇 세션 분량이 모이면 본다"가 25 다.
    "harness-retro":       {"traces": 25},
}

WHY: dict[str, str] = {
    "md-audit":            "find where docs and code disagree",
    "code-audit":          "find code that grew more complex than needed",
    "code-debt":           "list deferred work (`debt:` markers)",
    "review-loop":         "review metrics and copy from a real user's view",
    "harness-retro":       "read the hook block trace and decide whether to adjust rules and gates",
}

DEBT_MARKER = "debt:"


def _git(*args: str) -> str:
    done = subprocess.run(("git", *args), cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    return done.stdout.strip() if done.returncode == 0 else ""


def _threshold(name: str, key: str) -> int:
    given = (profile.MAINTENANCE.get(name) or {}) if profile.MAINTENANCE else {}
    return int(given.get(key, DEFAULTS.get(name, {}).get(key, 0)))


def load_ledger() -> dict[str, dict[str, str]]:
    if not LEDGER.exists():
        return {}
    try:
        return json.loads(LEDGER.read_text(encoding=READ_ENC))
    except (ValueError, OSError):
        return {}                       # 손상된 기록은 "한 번도 안 돌았다"로 취급한다


def stamp(name: str) -> None:
    """방금 돌린 정비를 기록한다. 현재 HEAD 와 오늘 날짜를 남긴다."""
    ledger = load_ledger()
    ledger[name] = {"commit": _git("rev-parse", "HEAD"), "date": date.today().isoformat()}
    LEDGER.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")


def _commits_since(sha: str) -> int:
    if not sha:
        return 0
    out = _git("rev-list", "--count", f"{sha}..HEAD")
    return int(out) if out.isdigit() else 0


def _days_since(stamped: str) -> int:
    if not stamped:
        return 0
    try:
        return (date.today() - datetime.fromisoformat(stamped).date()).days
    except ValueError:
        return 0


def _ui_changes_since(sha: str) -> int:
    ui = profile.layer("ui")
    if not ui or not sha:
        return 0
    changed = _git("diff", "--name-only", f"{sha}..HEAD", "--", ui)
    return len([line for line in changed.splitlines() if line.strip()])


@functools.cache
def _source_lists() -> tuple[list[Path], list[Path]]:
    """정비가 볼 (서버, 화면) 소스 — 게이트와 **같은 목록**이다. 한 번의 판정에서 항목마다 다시 모으지 않는다.

    러너를 거치는 이유: 하네스 자체 파일 제외와 프로파일의 스코프 제외를 게이트와 똑같이 적용해야 한다.
    직접 세면 clone 으로 딸려온 픽스처 30개가 프로젝트 코드로 잡혀, 갓 만든 빈 프로젝트가
    첫날부터 "감사할 때가 됐다"는 알림을 받는다.
    """
    return runner.source_files()


def _sources() -> list[Path]:
    py_files, ui_files = _source_lists()
    return py_files + ui_files


def count_debt_markers() -> int:
    """소스에 남은 `debt:` 표시 수 — 미뤄둔 작업이 얼마나 쌓였는지 나타낸다."""
    total = 0
    for f in _sources():
        try:
            total += f.read_text(encoding=READ_ENC).count(DEBT_MARKER)
        except OSError:
            continue
    return total


def _never_ran_reason(name: str) -> str:
    """한 번도 안 돌았을 때. 갓 만든 레포까지 채근하지 않도록 레포 규모를 본다."""
    count = len(_sources())
    if count < 20:
        return ""
    return f"never run, and sources have grown to {count} files"


def _due_for(name: str, entry: dict[str, str]) -> str:
    """이 항목이 밀렸는지와 그 사유. 안 밀렸으면 빈 문자열."""
    if name == "code-debt":
        markers = count_debt_markers()
        limit = _threshold(name, "markers")
        return f"{markers} deferred markers piled up (threshold {limit})" if markers >= limit else ""

    # 커밋 수나 경과일이 아니라 쌓인 기록 건수를 재는 항목이라, 아래의 마지막 실행 시점 기준 판정을 거치지 않는다.
    # 한 번도 안 돌았으면 기록 전체를 센다. 그 기록이 첫 회고에서 읽을 자료다.
    if name == "harness-retro":
        seen = retro.count_since(entry.get("date", ""))
        limit = _threshold(name, "traces")
        return f"hooks blocked {seen} times since the last retro (threshold {limit})" if seen >= limit else ""

    if not entry:
        return _never_ran_reason(name)

    commits = _commits_since(entry.get("commit", ""))
    limit_commits = _threshold(name, "commits")
    if limit_commits and commits >= limit_commits:
        return f"{commits} commits since the last run (threshold {limit_commits})"

    days = _days_since(entry.get("date", ""))
    limit_days = _threshold(name, "days")
    if limit_days and days >= limit_days:
        return f"{days} days since the last run (threshold {limit_days})"

    changes = _ui_changes_since(entry.get("commit", ""))
    limit_ui = _threshold(name, "ui_changes")
    if limit_ui and changes >= limit_ui:
        return f"{changes} UI files changed (threshold {limit_ui})"
    return ""


def due() -> list[tuple[str, str]]:
    """지금 밀린 정비 목록 — (이름, 사유)."""
    ledger = load_ledger()
    found: list[tuple[str, str]] = []
    # 선언이 아니라 실물을 본다. 프리셋이 ui 레이어를 미리 적어두므로, 선언만 보면 화면
    # 파일이 한 개도 없는 프로젝트가 첫날부터 "화면 사용성 점검할 때"라는 알림을 받는다.
    has_ui = bool(_source_lists()[1])
    needs_ui = ("review-loop",)
    for name in DEFAULTS:
        if name in needs_ui and not has_ui:
            continue                    # 화면이 없으면 지표·문구 검수는 대상이 아니다
        reason = _due_for(name, ledger.get(name, {}))
        if reason:
            found.append((name, reason))
    return found


def main(argv: list[str]) -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(errors="replace")
    if len(argv) >= 2 and argv[0] == "--stamp":
        stamp(argv[1])
        print(f"Maintenance recorded: {argv[1]} — commit {LEDGER.name}")
        return 0
    pending = due()
    if not pending:
        print("No overdue maintenance.")
        return 0
    for name, reason in pending:
        print(f"[MAINTENANCE] {name} — {WHY.get(name, '')}. {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
