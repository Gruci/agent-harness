"""kernel/trace.py — 훅이 막을 때마다 한 줄씩 남기는 관찰 기록.

프로젝트 초반이 신호가 제일 센 구간이다. 게이트가 제일 많이 걸리고, 관례가 그때 정해지고,
오탐도 그때 드러난다. 그 시기에 기록 장치가 없으면 데이터는 사람 기억에만 남고 기억은
세션이 끝나면 사라진다. 코드가 쌓인 뒤에 기록을 붙이면 이미 늦다. 그래서 제품 코드보다 이 기록 장치를 먼저 둔다.

기록은 `harness_trace.jsonl` 이고 **커밋한다.** 정비 기록과 같은 근거다. 머신과 세션이
바뀌어도 남아야 회고의 기준점이 성립하고, gitignore 하면 clone 한 번에 통째로 사라진다.

훅은 추적 파일에 바로 쓰지 않는다. 본체와 worktree 어디서나 도는 훅이 각자의 추적 파일에 붙이면 체크아웃마다
따로 더러워져 ff 합치기를 git 이 거부했다(결함 F). 그래서 공유 `.git` 안의 비추적 대기 파일에 먼저 쌓고,
`kernel.task finish` 가 그 과업 브랜치의 추적 파일로 옮겨 커밋한다. 병렬 과업의 줄은 `.gitattributes` 의
`merge=union` 이 둘 다 남긴다.

여기는 **적기만 한다.** 무엇이 패턴인지는 `kernel/retro.py` 가 보고, 그게 규칙 위반인지
게이트 오탐인지는 사람이 판정한다. 이 하네스에는 "더 좋아졌다"를 재는 기준이 없어서, 그 판정까지
기계에 맡기면 결국 가장 쉬운 통과 방법인 면제 목록 늘리기로 흘러간다.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

from kernel.context import READ_ENC, ROOT, git_common_dir
from kernel.runner import violation_path

TRACE = ROOT / "harness_trace.jsonl"
PENDING_NAME = "harness-trace.jsonl"

MAX_MSG_CHARS = 400

# 관찰 단계. block 은 막았다, wip 는 worktree 안 직접 관측을 알렸다, warn 은 추론이거나 검사 불능이다.
# 회고(`kernel/retro.py`)와 정비 알림이 단계별로 센다 — worktree 알림을 차단으로 세면 집계가 거짓이 된다.
LEVELS = ("block", "wip", "warn")

# 같은 세션의 같은 차단은 새 신호가 아니다. Stop 훅은 턴마다 실행되므로 위반 하나가 다섯
# 턴을 끌면 같은 줄이 다섯 개 쌓이고, "이 게이트가 자주 걸린다"는 집계가 통째로 거짓이 된다.
# 세션이 다르면 따로 센다 — 다른 세션의 같은 차단은 실제로 다른 사건이다.
# 단계(level)도 키다 — worktree 안 알림과 합칠 때의 차단은 같은 위반이어도 다른 사건이다.
DEDUP_KEYS = ("sid", "kind", "gate", "file", "msg", "level")

# 형식 계약의 정본은 `kernel/runner.py` 의 `_print_sections` 다.
_FAIL_HEAD = re.compile(r"^\[FAIL\]\s+.+?\s+\(([\w:.\-]+)\)\s+—")
_VIOLATION = re.compile(r"^\s+-\s+(.+?)\s*$")


def pending_path() -> Path:
    """기록이 먼저 쌓이는 곳 — 공유 `.git` 안의 비추적 파일 하나. git 을 못 쓰면 추적 파일에 바로 쓴다.

    보드처럼 한 곳에 모으고, 추적 파일에는 `task finish` 가 과업 커밋으로 옮긴다.
    """
    common = git_common_dir(TRACE.parent)
    return TRACE if common is None else common / PENDING_NAME


def _read(path: Path) -> list[dict[str, str]]:
    """한 파일의 기록. 깨진 줄은 건너뛰어, 줄 하나 때문에 회고 전체가 막히지 않게 한다."""
    if not path.exists():
        return []
    found: list[dict[str, str]] = []
    for line in path.read_text(encoding=READ_ENC).splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            found.append({key: str(value) for key, value in item.items()})
    return found


def records() -> list[dict[str, str]]:
    """기록 전체 — 추적 파일과 대기 파일을 합쳐 읽는다. 회고와 정비 알림의 건수가 그대로 맞는다."""
    pending = pending_path()
    return _read(TRACE) + (_read(pending) if pending != TRACE else [])


def flush(target: Path) -> int:
    """대기 기록을 그 체크아웃의 추적 파일 끝으로 옮기고 대기 파일을 비운다. 옮긴 줄 수를 돌려준다."""
    pending = pending_path()
    if pending == target or not pending.exists():
        return 0
    lines = [line for line in pending.read_text(encoding=READ_ENC).splitlines() if line.strip()]
    if lines:
        with target.open("a", encoding="utf-8") as out:
            out.write("\n".join(lines) + "\n")
    pending.write_text("", encoding="utf-8")
    return len(lines)


def reclaim(checkout: Path) -> int:
    """예전 훅이 추적 파일에 바로 붙인 커밋 안 된 줄을 대기 파일로 옮기고 추적 파일을 HEAD 로 되돌린다.

    업그레이드한 설치의 첫 finish 가 본체의 더러운 추적 파일 때문에 막히지 않게 하는 이행 경로다. 옮긴 줄 수를 돌려준다.
    """
    name = TRACE.name
    try:
        diff = subprocess.run(["git", "-C", str(checkout), "diff", "-U0", "HEAD", "--", name],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return 0
    added = [line[1:] for line in diff.stdout.splitlines() if line.startswith("+") and not line.startswith("+++")]
    if diff.returncode != 0 or not added:
        return 0
    pending = pending_path()
    if pending == TRACE:
        return 0
    known = {_key(old) for old in _read(pending)}
    kept = [line for line in added if line.strip() and _key(_load(line)) not in known]
    if kept:
        with pending.open("a", encoding="utf-8") as out:
            out.write("\n".join(kept) + "\n")
    subprocess.run(["git", "-C", str(checkout), "checkout", "--", name], capture_output=True, timeout=10)
    return len(kept)


def _load(line: str) -> dict[str, str]:
    try:
        item = json.loads(line)
    except ValueError:
        return {"msg": line}
    return {key: str(value) for key, value in item.items()} if isinstance(item, dict) else {"msg": line}


def portable(text: str) -> str:
    """커밋되는 기록에서 체크아웃 위치와 사용자 홈을 뺀다.

    레포 안 경로는 레포 상대, 홈 아래는 `~/…` 로 바꾼다. 절대경로가 남으면 clone 위치가
    바뀔 때 같은 사건이 다른 키가 되어 중복 제거와 집계가 갈리고, 다른 사람 홈 경로가 커밋된다.
    """
    from pathlib import Path

    fixed = text
    for base, label in ((ROOT.resolve(), ""), (Path.home().resolve(), "~/")):
        bare = label.rstrip("/") or "."
        for form in {str(base), base.as_posix()}:
            for sep in ("\\", "/"):
                fixed = fixed.replace(form + sep, label)
            # 뒤에 구분자 없이 나온 루트(`--root D:\repo`). 이름이 이어지는 형제 경로(`D:\repo-old`)는 레포 밖이라 둔다.
            fixed = re.sub(re.escape(form) + r"(?![A-Za-z0-9_.-])", lambda _match: bare, fixed)
    return fixed.replace("\\", "/") if fixed != text else fixed


def _key(item: dict[str, str]) -> tuple[str, ...]:
    return tuple(item.get(name, "") for name in DEDUP_KEYS)


def record(hook: str, kind: str, sid: str = "", gate: str = "",
           file: str = "", msg: str = "", level: str = "block") -> None:
    """관찰 한 줄을 남긴다. 무슨 일이 있어도 예외를 밖으로 던지지 않는다.

    기록 실패가 훅을 죽이면 차단 자체가 무력화된다. 관찰은 차단보다 항상 덜 중요하다.
    `level` 은 `LEVELS` 중 하나다.
    """
    try:
        item = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "sid": sid[:8],
            "hook": hook,
            "kind": kind,
            "gate": gate,
            "file": portable(file),
            "msg": portable(msg)[:MAX_MSG_CHARS],
            "level": level,
        }
        # debt:append 할 때마다 파일 전체를 읽어 중복을 확인한다. 관찰은 드물고 파일은 작아서 지금은
        # 이게 제일 싸다. 수천 줄이 되면 마지막 N줄만 읽는 것으로 바꾼다.
        if _key(item) in {_key(old) for old in records()}:
            return
        with pending_path().open("a", encoding="utf-8") as out:
            out.write(json.dumps(item, ensure_ascii=False) + "\n")
    except Exception:
        return


def record_runner_output(hook: str, sid: str, stdout: str, level: str = "block") -> None:
    """러너 출력에서 (게이트 slug, 위반 문구)를 뽑아 전부 기록한다."""
    slug = ""
    for line in stdout.splitlines():
        head = _FAIL_HEAD.match(line)
        if head:
            slug = head.group(1)
            continue
        found = _VIOLATION.match(line)
        if found and slug:
            msg = found.group(1)
            record(hook, "gate", sid=sid, gate=slug, file=violation_path(msg) or "", msg=msg, level=level)
