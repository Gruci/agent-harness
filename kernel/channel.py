"""kernel/channel.py — 판정을 런타임별 채널로 옮긴다.

`kernel/hook.py` 는 검사를 돌려 `Verdict` 하나를 만들고, 그것을 누가 어떻게 받는지는 여기서 정한다.
exit 코드와 JSON 필드가 누구에게 닿는지는 런타임이 정하므로(훅 문서), 채널 선택의 정본을 한 곳에 둔다.

| 결과 | Claude | Codex |
|---|---|---|
| 위반 — 공유 체크아웃 | exit 2 + stderr. 판정 줄만 | 같다 |
| 위반 — worktree 저장 | exit 0. `additionalContext` 는 모델에게, `systemMessage` 한 줄은 사용자에게 | exit 0 + `systemMessage` |
| 위반 — worktree 종료 | exit 0 + `systemMessage` 한 줄. 모델 몫은 git 디렉터리에 보관했다가 다음 저장에 붙인다 | exit 0 + `systemMessage` |
| 결정 알림만 | 저장은 `additionalContext`. 종료는 `systemMessage` 와 보관 | `systemMessage` |
| 검사 불능 — 시간 초과 포함 | exit 1 + stderr. 화면의 "hook error" 표시가 사실이다 | 같다 |

종료 시점의 모델 채널(`additionalContext`·`decision`)은 쓰지 않는다. 막지 않는 알림도 턴을 8번까지 잇고,
워커를 기다리는 세션이 매 턴 깨는 §25 가 돌아온다(`dev/LESSONS.md` §26). 모델 몫은 다음 저장이 받는다 —
그때가 모델이 코드를 고치는 순간이고, 저장 없이 끝내면 나올 때 검사가 같은 목록으로 막는다.

이 모듈은 커널의 다른 모듈을 최상위에서 import 하지 않는다. 플러그인 경로가 `HARNESS_ROOT` 를 정하기 전에
`kernel.context.ROOT` 가 굳으면 안 되기 때문이다. git 디렉터리는 표준 라이브러리만으로 찾는다.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from kernel.workspace import Finding

WIP_HEAD = ("[WIP] These will block at merge — not blocked inside a worktree. "
            "Before push or PR, `python -X utf8 -m kernel.runner --verify` must exit 0.")
HELD_HEAD = "[TURN END] The full check at the end of the last turn found these — they block at merge:"
HELD_USER_LINE = "[TURN END] The last turn's full-check findings were handed to the model with this save."
HELD_FILE = "harness-held-{sid8}.json"
FAILURE_HEADS = ("[FAIL]", "[TOOL]")


@dataclass(frozen=True)
class Verdict:
    """One save or stop run. code: 0 nothing blocks, 1 the check could not run, 2 a violation or a Stop crash."""
    code: int = 0
    lines: tuple[str, ...] = ()       # verdict lines only (kernel.exit_gate.verdict_lines), or why the check could not run
    notices: tuple[str, ...] = ()     # [DECISION] notices from kernel.graph_notifications — never a block


@dataclass(frozen=True)
class Delivery:
    """What the adapter prints. An empty payload prints nothing for Claude and `{}` for Codex."""
    code: int
    stderr: str = ""
    payload: dict[str, object] = field(default_factory=dict)


def model_text(verdict: Verdict, wip: bool) -> str:
    """판정 줄과 결정 알림. worktree 안이면 `WIP_HEAD` 를 앞에 붙인다. 아무것도 없으면 빈 문자열."""
    body = [*verdict.lines, *verdict.notices]
    if not body:
        return ""
    return "\n".join([WIP_HEAD, *body] if wip else body)


def user_line(verdict: Verdict, event: str, wip: bool) -> str:
    """사용자 화면 한 줄 — 실패 수와 결정 수, 그리고 모델이 지금 받는지 다음 저장 때 받는지."""
    failures = sum(1 for line in verdict.lines if line.startswith(FAILURE_HEADS))
    parts = []
    if failures:
        parts.append(f"{failures} gate {'failure' if failures == 1 else 'failures'}")
    if verdict.notices:
        count = len(verdict.notices)
        parts.append(f"{count} decision {'request' if count == 1 else 'requests'}")
    if not parts:
        return HELD_USER_LINE
    head = "[WIP]" if wip else "[DECISION]"
    where = "will block at merge" if wip else "wait for the user"
    when = "the model has them now" if event == "PostToolUse" else "the model gets them at its next save"
    return f"{head} {' and '.join(parts)} {where} — {when}."


def held_text(verdict: Verdict, wip: bool) -> str | None:
    """종료가 보관할 본문. 검사 불능이면 None(지난 본문 유지), 공유 체크아웃 차단과 깨끗한 실행이면 빈 문자열(지움)."""
    if verdict.code == 1:
        return None
    if verdict.code == 2 and not wip:
        return ""                             # the model already read the block on stderr
    return model_text(verdict, wip)


def for_claude(verdict: Verdict, event: str, wip: bool, held: str = "") -> Delivery:
    """Claude routing (table above). `held` is the text a Stop kept for this save."""
    if verdict.code == 1:
        return Delivery(1, "\n".join(verdict.lines))      # could not run — the "hook error" label is true
    text = "\n".join(part for part in (model_text(verdict, wip), f"{HELD_HEAD}\n{held}" if held else "") if part)
    if verdict.code == 2 and not wip:
        return Delivery(2, text)
    if not text:
        return Delivery(0)
    shown: dict[str, object] = {"systemMessage": user_line(verdict, event, wip)}
    if event == "Stop":
        return Delivery(0, "", shown)                   # a Stop channel to the model would keep the turn going
    return Delivery(0, "", {**shown, "hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                            "additionalContext": text}})


def for_codex(verdict: Verdict, wip: bool, findings: Sequence[Finding] = (), overlap: str = "") -> Delivery:
    """Codex routing: a blocked turn reads stderr only, so a block carries every notice there."""
    blocking = [finding.message for finding in findings if finding.block]
    notes = [finding.message for finding in findings if not finding.block]
    message = "\n".join(part for part in (model_text(verdict, wip), *notes, overlap) if part)
    code = max(0 if wip else verdict.code, 2 if blocking else 0)
    if code:
        return Delivery(code, "\n".join(part for part in (*blocking, message) if part))
    return Delivery(0, "", {"systemMessage": message} if message else {})


def _git_dirs(root: Path) -> tuple[Path, Path] | None:
    """(이 체크아웃의 git 디렉터리, 공유 git 디렉터리). git 실패면 None."""
    try:
        done = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-dir", "--git-common-dir"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = done.stdout.splitlines()
    if done.returncode != 0 or len(lines) < 2:
        return None
    own, common = Path(lines[0].strip()), Path(lines[1].strip())
    if not own.is_absolute():
        own = root / own                      # 메인 체크아웃에서는 `.git` 상대경로가 온다
    if not common.is_absolute():
        common = root / common
    return own.resolve(), common.resolve()


def linked_worktree(root: Path) -> bool:
    """링크드 worktree 인가 — 자기 git 디렉터리와 공유 git 디렉터리가 다르다."""
    found = _git_dirs(root)
    return found is not None and found[0] != found[1]


def held_path(root: Path, sid8: str) -> Path | None:
    """보관 파일 자리. git 디렉터리라 `git status` 를 더럽히지 않고 `git worktree remove` 가 함께 지운다."""
    found = _git_dirs(root)
    return found[0] / HELD_FILE.format(sid8=sid8) if found else None


def hold(root: Path, sid8: str, text: str | None) -> None:
    """종료가 보관한다. None 은 지난 본문 유지, 빈 문자열은 지움. 같은 해시면 다시 쓰지 않는다 — 전달 표시가 남아 같은 본문은 한 번만 간다.

    실패는 삼킨다. 잃은 알림이 게이트를 깨지 않는다.
    """
    if text is None or not sid8:
        return
    try:
        path = held_path(root, sid8)
        if path is None:
            return
        if not text:
            path.unlink(missing_ok=True)
            return
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if path.exists() and json.loads(path.read_text(encoding="utf-8")).get("hash") == digest:
            return
        path.write_text(json.dumps({"hash": digest, "text": text, "delivered": False}, ensure_ascii=False),
                        encoding="utf-8")
    except Exception:
        return


def take(root: Path, sid8: str) -> str:
    """저장이 한 번만 가져간다. 가져가면 `delivered` 표시를 남긴다. 없거나 실패면 빈 문자열."""
    if not sid8:
        return ""
    try:
        path = held_path(root, sid8)
        if path is None or not path.exists():
            return ""
        item = json.loads(path.read_text(encoding="utf-8"))
        if item.get("delivered"):
            return ""
        item["delivered"] = True
        path.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
        return str(item.get("text") or "")
    except Exception:
        return ""


def emit(delivery: Delivery, agent: str) -> int:
    """stderr 와 JSON 을 찍고 exit 코드를 돌려준다. Codex 는 exit 0 이면 늘 JSON 객체를 찍는다."""
    if delivery.stderr:
        print(delivery.stderr, file=sys.stderr)
    if delivery.payload:
        print(json.dumps(delivery.payload, ensure_ascii=False))
    elif agent == "codex" and delivery.code == 0:
        print("{}")
    return delivery.code
