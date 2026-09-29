"""kernel/trace.py — 훅이 막을 때마다 한 줄씩 남기는 관찰 기록.

프로젝트 초반이 신호가 제일 센 구간이다. 게이트가 제일 많이 걸리고, 관례가 그때 정해지고,
오탐도 그때 드러난다. 그 시기에 기록 장치가 없으면 데이터는 사람 기억에만 남고 기억은
세션이 끝나면 사라진다. 코드가 쌓인 뒤에 기록을 붙이면 이미 늦다. 그래서 제품 코드보다 이 기록 장치를 먼저 둔다.

기록은 `harness_trace.jsonl` 이고 **커밋한다.** 정비 기록과 같은 근거다. 머신과 세션이
바뀌어도 남아야 회고의 기준점이 성립하고, gitignore 하면 clone 한 번에 통째로 사라진다.

여기는 **적기만 한다.** 무엇이 패턴인지는 `kernel/retro.py` 가 보고, 그게 규칙 위반인지
게이트 오탐인지는 사람이 판정한다. 이 하네스에는 "더 좋아졌다"를 재는 기준이 없어서, 그 판정까지
기계에 맡기면 결국 가장 쉬운 통과 방법인 면제 목록 늘리기로 흘러간다.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from kernel.context import READ_ENC, ROOT
from kernel.runner import violation_path

TRACE = ROOT / "harness_trace.jsonl"

MAX_MSG_CHARS = 400

# 같은 세션의 같은 차단은 새 신호가 아니다. Stop 훅은 턴마다 실행되므로 위반 하나가 다섯
# 턴을 끌면 같은 줄이 다섯 개 쌓이고, "이 게이트가 자주 걸린다"는 집계가 통째로 거짓이 된다.
# 세션이 다르면 따로 센다 — 다른 세션의 같은 차단은 실제로 다른 사건이다.
DEDUP_KEYS = ("sid", "kind", "gate", "file", "msg")

# 형식 계약의 정본은 `kernel/runner.py` 의 `_print_sections` 다.
_FAIL_HEAD = re.compile(r"^\[FAIL\]\s+.+?\s+\(([\w:.\-]+)\)\s+—")
_VIOLATION = re.compile(r"^\s+-\s+(.+?)\s*$")


def records() -> list[dict[str, str]]:
    """기록 전체를 읽는다. 깨진 줄은 건너뛰어, 줄 하나 때문에 회고 전체가 막히지 않게 한다."""
    if not TRACE.exists():
        return []
    found: list[dict[str, str]] = []
    for line in TRACE.read_text(encoding=READ_ENC).splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            found.append({key: str(value) for key, value in item.items()})
    return found


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
           file: str = "", msg: str = "") -> None:
    """관찰 한 줄을 남긴다. 무슨 일이 있어도 예외를 밖으로 던지지 않는다.

    기록 실패가 훅을 죽이면 차단 자체가 무력화된다. 관찰은 차단보다 항상 덜 중요하다.
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
        }
        # debt:append 할 때마다 파일 전체를 읽어 중복을 확인한다. 관찰은 드물고 파일은 작아서 지금은
        # 이게 제일 싸다. 수천 줄이 되면 마지막 N줄만 읽는 것으로 바꾼다.
        if _key(item) in {_key(old) for old in records()}:
            return
        with TRACE.open("a", encoding="utf-8") as out:
            out.write(json.dumps(item, ensure_ascii=False) + "\n")
    except Exception:
        return


def record_runner_output(hook: str, sid: str, stdout: str) -> None:
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
            record(hook, "gate", sid=sid, gate=slug, file=violation_path(msg) or "", msg=msg)
