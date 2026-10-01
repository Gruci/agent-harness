"""PreToolUse(Edit|Write) hook — 남이 잡은 곳을 건드리면 알린다.

`check_editing_lock.py` 는 이름과 달리 **Stop 훅**이고, "머지가 끝난 내 과업 파일이 남아 있는가"를 본다.
그래서 **편집을 시작할 때** 다른 과업이 맡은 곳을 건드리는지 알려주는 장치가 하나도 없었다. 겹침은 사람이
보드를 직접 읽어야만 발견됐다.

worktree 는 **파일 충돌**만 막는다. 두 세션이 서로 다른 파일로 같은 기능을 각자 만들면 git 은
조용히 둘 다 머지하고, 결과는 앞뒤가 안 맞는 화면이다(원본 프로젝트 MIS 에서 2026-09-16 에 확인: 한쪽이
클래스명을 바꾸자 다른 쪽 CSS 가 전부 적용되지 않았다). 이 훅은 그런 겹침을 편집을 시작하는 시점에
드러낸다. 판정 정본은 `kernel/workboard.py` 한 곳이고, Codex 진입점(`kernel/hook.py`)도
같은 판정을 저장 직후에 실행한다. Codex 에는 편집 전 이벤트가 없기 때문이다.

## 경고지 차단이 아니다

판정 근거인 `손대는 곳` 글로브는 사람이 적은 것이라 너무 넓거나 오래된 채로 남기 쉽다. 차단으로 하면 오탐 한 번에
세션이 멈춘다. `dev/HARNESS.md` 「단계」에서 추론에 기대는 규칙을 경고로 두는 것과 같은 이유다.

## 내 과업 판정은 파일명이 아니라 `#sid:` 태그다

파일명(= 범위 이름)으로 구분하면 범위 이름을 바꾸는 순간 자기 과업을 남의 과업으로 보고 경고한다.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hookio import read_hook_payload, record  # noqa: E402

# ⚠️ ROOT 는 **자기 worktree 루트**다(보드 위치와 다르다). 편집 대상 파일을 상대경로로 바꿔
#    글로브와 비교하는 데 쓰므로, 공유 체크아웃으로 잡으면 worktree 안 파일이 전부 `relative_to`
#    범위를 벗어나 경고가 전혀 나오지 않는다.
ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(ROOT))

# 판정 정본은 kernel/workboard.py — 커널을 못 읽으면 fail-open: 경고 훅이 편집을 막지 않는다.
try:
    from kernel.workboard import board_dir, overlaps as _overlaps  # noqa: E402
except Exception:
    sys.exit(0)

# 보드는 **공유 체크아웃 한 곳**에만 있다 — 훅 파일이 worktree 마다 복사되므로 자기 트리 기준으로
# 잡으면 보드가 세션 수만큼 따로 생긴다(`kernel.workboard.board_dir` 헤더).
BOARD_DIR = board_dir()

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def overlaps(target: Path, sid8: str) -> list[str]:
    """내 것이 아닌 과업의 글로브에 걸리는지 본다. 판정은 커널이 하고, 이 훅은 보드와 루트 위치만 넘긴다."""
    return _overlaps(target, sid8, BOARD_DIR, ROOT)


def _target(payload: dict) -> Path | None:
    """Edit·Write 가 건드리는 파일. 다른 도구면 None."""
    if payload.get("tool_name") not in EDIT_TOOLS:
        return None
    raw = (payload.get("tool_input") or {}).get("file_path")
    return Path(raw) if raw else None


def main() -> None:
    if not BOARD_DIR.is_dir():
        sys.exit(0)
    try:
        payload = read_hook_payload()
    except Exception:
        sys.exit(0)                       # 판정할 수 없으면 조용히 통과 — 경고 훅이 편집을 막지 않는다

    target = _target(payload)
    if target is None:
        sys.exit(0)
    sid8 = str(payload.get("session_id") or "")[:8]
    hits = overlaps(target, sid8)
    if not hits:
        sys.exit(0)

    record("check_workboard_overlap", "workboard_overlap", sid=sid8, msg=f"{len(hits)} found {target.name}")
    message = "\n".join([f"[WORKBOARD] Another task owns this file — {target.name}",
                         *(f"  {hit}" for hit in hits),
                         "If it is the same screen, add an item to that task file so that session handles it, or build on that branch.",
                         "If the lines do not overlap, go ahead — this is a warning, not a block."])
    # exit 1 의 stderr 는 모델에 닿지 않는다(훅 문서). exit 0 JSON 으로 모델(additionalContext)과
    # 사용자(systemMessage) 양쪽에 싣는다 — 편집은 그대로 진행된다.
    print(json.dumps({"systemMessage": message,
                      "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": message}},
                     ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
