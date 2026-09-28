"""kernel/workspace.py — 세션 종료 시점의 작업공간 판정: 보드·git 원격·목업·과업 산출물.

Claude Stop 훅 넷(`check_editing_lock`·`check_git_remote`·`check_mockup_residue`·
`check_task_residue`)과 Codex Stop(`kernel/hook.py`)이 같은 판정을 쓴다. 판정은 전부
`Finding` 한 모양으로 돌아오고, 페이로드·exit·출력 JSON 은 어댑터가 맡는다. 판정 불능의
방향은 판정마다 다르다 — 보드 잔존은 통과, git 원격은 fail-closed, 과업 산출물은 보드
조회 실패를 "보드 빔"으로 본다.

## 보드 잔존 (⑫ ⑫-1) — `workboard/` 에 '끝난' 과업 파일이 남아있으면 알린다

과업 보드는 파일 하나가 과업 하나다(`workboard/<수정범위>.md` — git 비추적).
표 한 개를 모든 세션이 같이 고치던 시절에는 PR 이 머지될 때마다 열린 나머지가 전부 같은
자리에서 깨졌다(원류 MIS 2026-09 실측: 보드 전용 PR 51건 = 전체의 25% · 충돌 해소 34건).
파일을 가르면 git 이 충돌을 만들 수 없고, 디렉토리가 `.gitignore` 라 보드를 보이려고 머지할
일도 없다.

멀티 세션 대응: 구버전은 잠금 행 전체를 차단해서, 다른 세션이 작업 중이면 이 세션이 영원히
종료 못 하는 데드락이 났다. 훅이 세션을 식별하지 못하는 게 원인이었다.

관례(정본: `workboard/README.md`) — 과업 파일에 `#sid:<세션ID 앞8자>` 태그를 붙인다. 판정:
  - 내 sid 태그 과업 중 **머지가 끝난 것** → 잔존이다. 완료 보고를 안 한 과업이다.
  - 내 sid 태그 과업이라도 **진행 중이면 통과** (아래).
  - 다른 sid 태그 과업 → 다른 세션의 활성 과업이라 건드리지 않는다.
  - 죽은 과업(아래) → sid 와 무관하게 잔존이다. 주인이 없어진 파일은 누가 지워도 된다.
  - session_id 를 못 읽으면 태그 없는 과업만 본다. 전부 막으면 남의 파일은 내가 지우면 안 되는
    것이라 종료할 방법이 사라진다 — 태그 없는 파일이 내 것일 수 있는 유일한 후보다.

구버전은 내 sid 행이 **있기만 하면** 막았다. 그러면 "과업이 머지될 때까지 세션은 못 끝난다"가
되는데, 이 하네스는 반대로 **여러 세션에 걸치는 작업을 전제**한다(`wip_` 접두·파일 핸드오프·
`/clear` 후 이어받기). 커밋만 하고 push 승인을 기다리던 세션이 그래서 종료 불능에 빠졌고,
모델이 할 수 있는 일이 없어 연속차단 상한이 훅을 무시하고 턴을 끝냈다.

차단은 **모델이 지금 고칠 수 있는 것**에만 건다. 머지가 끝났는데 남은 파일은 지우면 되지만,
머지 전 파일은 지우는 것이 곧 거짓 완료 보고라 고칠 수단이 없다. `stop_hook_active` 로 재차단만
빠져나가는 방법도 있지만 그건 조건은 그대로 둔 채 입만 막는 것이라 쓰지 않는다 — 훅이 도는 건
조건이 참이기 때문이고, 조건이 틀렸으면 조건을 고친다.

조건을 좁혀도 판정 근거는 여전히 **git 상태 추론**이다(머지 커밋 제목 매칭·ref 유무). squash
머지나 포크 워크플로처럼 흔적이 다른 경우가 있어 오탐 여지가 남는다. 검출은 계속하되 문은
안 잠근다(`block=False`) — 정본은 `dev/HARNESS.md` 「단계」다.

원격 조회는 remote-tracking ref 로 한다(`git ls-remote` 아님). Stop 은 매 턴 끝에 도므로
네트워크를 타면 안 된다. ref 신선도는 SessionStart 의 `git_staleness.py` 가 맡는다.

## git 원격 (⑭) — origin 미설정 시 종료 차단

초기 설정 ⓪은 git init 이 아니라 GitHub 원격 연결까지다. 원격 없이 "완료"를 선언하면
커밋이 이 머신에만 남는다 — origin 이 잡히기 전까지 종료를 막는다. git 실행 실패도
통과가 아니라 차단(fail-closed).

**gh 가 인증돼 있으면 사용자에게 묻지 않는다.** 예전엔 "레포 주소는 사용자만 아는 정보"라며
매번 물었는데, 인증된 계정이 있으면 그건 사실이 아니다. 폴더 이름이 곧 레포 이름이고 계정은
이미 정해져 있다. 사용자만 아는 게 실제로 남는 경우(인증 없음·다른 계정에 만들고 싶음)에만
질문이 남는다. **private 로만 만든다.** 공개 레포는 되돌리기 어려운 발행이라 사람이 정할 일이다.

## 목업 잔존 (⑯) — docs/tasks/mockup/ 에 목업이 남아있으면 종료를 막는다

목업은 사용자에게 보여주고 판단을 받는 게 존재 이유다. 판단이 끝나면 갈 곳이 정해지는데,
그 시점이 "다음에"로 밀리면 죽은 시안이 쌓인다(원류 프로젝트 실태 4건).

행선지는 채택 여부가 가른다 — 채택분은 `docs/tasks/archive/<작업>/` 로 옮겨 plan·research 와
같은 자리에 남기고, 반려분은 지운다. 채택된 시안은 "왜 이 화면이 이렇게 생겼나"의 유일한
기록이라 archive 가 받아야 한다.

추적 여부를 보지 않고 디렉토리를 직접 스캔한다. 목업은 대개 untracked 라 `git ls-files`
기반 게이트로는 잡히지 않는다.

예외: `wip_` 접두 파일은 차단하지 않는다 — 판단이 세션을 넘겨 이어지는 검토 중 시안까지
막으면 세션 종료가 불가능해진다. 전역 스위치가 아니라 파일 단위 명시라, 접두 없는 잔존
(판단 끝난 시안 방치)은 여전히 잡힌다. 채택 확정 시 접두를 떼고 archive 로 옮긴다.

## 과업 산출물 잔존 (⑰) — docs/tasks/ 루트에 plan·research 가 남아있으면 종료를 막는다

목업과 같은 계약이다. 루트에 남은 산출물은 다음 세션에게 "진행 중인 작업"으로 읽힌다.
실제로는 끝난 과업의 잔해라 그 오독이 리서치와 계획을 통째로 낭비시킨다.

`glob("*.md")` 는 루트만 훑어 `archive/`·`mockup/` 하위를 자동으로 제외한다 — archive 는
산출물의 목적지라 거기 있는 것은 잔존이 아니고, mockup 은 위 판정의 관할이다.

plan 은 목업과 달리 **과업이 끝날 때까지 루트에 있는 게 정상**이다(1~3단계 내내 참조된다).
파일 존재만으로 잔존을 판정하면 진행 중인 세션의 종료를 매 턴 막는다 — 원류 프로젝트의 첫
버전이 다른 세션의 진행 중 plan 3건을 잡았다. 그 상태에서 빠져나가는 유일한 길이 `wip_`
접두라, 접두가 기본값이 되고 게이트는 소음이 된다.

완료 신호는 파일이 아니라 **과업 보드**다. `workboard/` 에 과업 파일이 하나라도 있으면
누군가 작업 중이므로 검사를 건너뛴다. 보드가 비었는데 루트에 산출물이 남아 있으면 그것이 잔존이다.
대가는 명시한다 — 다른 과업이 진행 중인 동안에는 끝난 과업의 잔해도 안 잡힌다. 미탐을 택한
이유는 오탐이 곧 종료 데드락이기 때문이다.

보드 행은 **3단계(구현) 시작 시** 등록한다. 그래서 1~2단계(리서치·계획 작성 중)인 세션은
보드에 행이 없고, 위 「보드가 busy 면 건너뛴다」가 그 세션을 못 지킨다 — 다른 세션이 자기 행을
지우는 순간 보드가 비면서 남의 갓 쓴 plan 이 검출된다(2026-09-07 실측: 1분 전 생성된 산출물이
종료를 막았다). 그래서 최근 수정분은 검출하지 않는다. 잔해는 **끝난 과업이 남긴 것**이라
시간이 지나고, 진행 중인 것은 방금 손댄 것이다 — 이 구분이 보드보다 이른 단계까지 덮는다.

예외: `wip_` 접두는 차단하지 않는다. 보드가 빈 상태로 세션을 넘겨 이어지는 검토용 산출물이다.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Callable

from kernel.context import ROOT, default_branch, git_output
from kernel.workboard import active_rows, board_dir, branch_of

# 테스트가 가짜 git 으로 갈아끼우는 자리 — 판정 함수는 이 이름으로만 git 을 부른다.
_git = git_output

TASK_DIR = ROOT / "docs" / "tasks"
MOCKUP_DIR = TASK_DIR / "mockup"

# 갓 만든 산출물의 유예(초) — 계획 단계 세션이 보드 행 없이 작업하는 구간을 덮는다.
# 하루로 두면 "어제 끝낸 과업의 잔해"가 다음날 첫 세션에서 잡힌다 — 다음 세션의 오독을
# 막는다는 목적은 그 정도 지연으로 안 흔들린다(당일 이어 붙는 세션은 대개 같은 과업이다).
FRESH_SEC = 24 * 60 * 60

# GitHub 레포 이름에 쓸 수 있는 문자만 남긴다
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class Finding:
    """판정 하나의 결과. 어댑터가 stderr·trace·exit 로 옮긴다.

    hook    trace 이름 = 기존 Claude 훅 이름("check_task_residue")
    kind    trace kind("task_residue")
    block   True = 차단(exit 2), False = 경고
    message 사용자·모델에게 보일 여러 줄 본문 — 기존 훅의 stderr 문구 그대로
    trace   trace msg 들 — 기존 record 호출과 같은 값
    """
    hook: str
    kind: str
    block: bool
    message: str
    trace: tuple[str, ...] = ()


# ── ⑫ ⑫-1 보드 잔존 ─────────────────────────────────────────────────────────

def is_merged(branch: str, base: str) -> bool:
    """기본 브랜치에 이 브랜치의 PR 머지 커밋이 있는가 — "이 과업은 끝났다"의 무모호 신호.

    reachability 로는 '갓 판 브랜치'와 '머지된 브랜치'를 못 가른다. 둘 다 기본 브랜치의
    조상이고 자기 커밋이 0개다. 머지 커밋 **제목**에는 그 모호함이 없다 — `Merge pull request
    #N from <소유자>/<브랜치>` 는 브랜치가 소스일 때만 나온다. 충돌 해소로 기본 브랜치를
    가져온 `Merge remote-tracking branch '...' into <브랜치>` 는 같은 이름이 들어가도 형태가
    달라 안 걸린다 — 그래서 이름 substring 이 아니라 전체 형태로 맞춘다.

    squash 머지는 이 흔적을 안 남긴다. 그때는 통과하고 정리가 끝난 뒤 `is_dead` 가 받는다.
    미탐을 택하는 이유는 오탐이 곧 종료 방해이기 때문이다.
    """
    log = _git("log", f"origin/{base}", "--merges", "--format=%s")
    if log is None:
        return False
    merged = re.compile(rf"^Merge pull request #\d+ from [^/\s]+/{re.escape(branch)}$")
    return any(merged.match(line.strip()) for line in log.splitlines())


def is_dead(branch: str, base: str) -> bool:
    """주인이 없어진 과업인지 — 머지가 끝났고 브랜치 실물이 **어디에도** 없을 때만 참이다.

    "브랜치가 없다"만으로 판정하면 안 된다. 이 하네스는 단일 세션이면 브랜치 없이 메인
    체크아웃에서 작업하는 것을 정본 경로로 둔다(`workboard/README.md`). 그래서 파일이
    적어둔 브랜치가 아직 실물이 아닌 것이 정상이고, 그것을 잔해로 읽으면 **착수하자마자 자기
    과업이 잔해가 된다.**

    머지 커밋이 그 브랜치가 실재했다는 유일한 증거다 — 없으면 애초에 만들어진 적이 없는
    이름이라 정리할 잔해도 없다. squash 머지는 그 흔적을 안 남겨 여기서 미탐이 된다.
    오탐이 곧 지울 권한 없는 파일로 인한 종료 방해라, 이 판정 전체가 미탐을 택한다.
    """
    if not is_merged(branch, base):
        return False
    if _git("show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}") is not None:
        return False
    return _git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}") is None


def _is_stale(row: str, base: str | None) -> bool:
    """내 과업 중 지금 지워도 되는 것인가 — 머지가 끝났거나 브랜치명이 없는 것이다.

    브랜치명 없는 과업도 대상이다. `git worktree list` 와 조인되는 것이 `#sid` 접미의 존재
    이유라 이름 없는 과업은 서식 위반이고, 내 것이니 내가 고칠 수 있다.
    기본 브랜치를 모르면 머지 판정이 불능이라 통과시킨다.
    """
    branch = branch_of(row)
    if branch is None:
        return True
    return bool(base) and is_merged(branch, base)


def _report(label: str, rows: list[str], guidance: str) -> list[str]:
    return [f"[WORKBOARD] {label} {len(rows)}건", *(f"  {row}" for row in rows), guidance]


def board_residue(sid8: str | None, board: Path | None = None) -> Finding | None:
    """Stop 판정 ⑫·⑫-1 — 머지 끝난 내 과업과 주인 없는 과업이 보드에 남아 있으면 경고 finding."""
    rows = active_rows(board_dir() if board is None else board)
    if not rows:
        return None
    if sid8:
        mine = [row for row in rows if f"#sid:{sid8}" in row]
    else:
        # 세션 식별 불가 — 태그 없는 과업만 내 것일 수 있다. 남의 sid 과업까지 보면 지울 권한이
        # 없는 파일 때문에 종료가 영영 불가능해진다.
        mine = [row for row in rows if "#sid:" not in row]
    base = default_branch()
    others = [row for row in rows if row not in mine]
    mine = [row for row in mine if _is_stale(row, base)]
    dead = [row for row in others
            if base and (branch := branch_of(row)) and is_dead(branch, base)]
    if not mine and not dead:
        return None
    lines: list[str] = []
    if mine:
        reason = "이 세션의" if sid8 else "(세션 식별 불가 — 태그 없는 과업만 검사)"
        lines += _report(f"{reason} 과업 파일이 머지 후에도 남아 있습니다 —", mine,
                         "머지가 끝난 과업이면 `git worktree remove` → `git branch -d` 를 먼저 끝내고 "
                         "workboard/ 의 자기 파일은 맨 끝에 지웁니다. 브랜치명이 없는 파일은 서식 위반이라 고칩니다.")
    if dead:
        lines += _report("주인이 없어진 과업 —", dead,
                         "이미 머지됐고 브랜치가 origin 에도 로컬에도 없습니다. 끝난 과업의 잔해라 어느 세션이든 지웁니다.")
    lines.append("⚠️ 다른 세션의 진행 중 과업 파일은 절대 지우지 말 것.")
    return Finding("check_editing_lock", "editing_lock", False, "\n".join(lines), tuple(mine + dead))


# ── ⑭ git 원격 ───────────────────────────────────────────────────────────────

def _run(*args: str, timeout: int = 10) -> tuple[int, str]:
    try:
        done = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except Exception:
        return 1, ""
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def suggested_name() -> str:
    name = _UNSAFE.sub("-", ROOT.name).strip("-.")
    return name or "new-project"


def gh_account() -> str:
    """인증된 GitHub 계정. 없으면 빈 문자열."""
    code, out = _run("gh", "auth", "status")
    if code != 0:
        return ""
    found = re.search(r"account\s+(\S+)", out) or re.search(r"as\s+(\S+)", out)
    return found.group(1) if found else "(인증됨)"


def git_remote() -> Finding | None:
    """Stop 판정 ⑭ — origin 이 없으면 차단 finding. 만들 명령까지 완성해서 준다."""
    code, _out = _run("git", "remote", "get-url", "origin")
    if code == 0:
        return None
    lines = ["[GIT REMOTE] GitHub 원격(origin)이 없다 — 코드가 이 머신에만 있다. "
             "원격이 잡히기 전까지 세션 종료 불가."]
    account = gh_account()
    if account:
        lines += [f"gh 가 {account} 로 인증돼 있다. **사용자에게 묻지 말고** 지금 만들어라:",
                  f"    gh repo create {suggested_name()} --private --source . --push",
                  "이름이 마음에 안 들면 바꿔도 된다. 다만 --private 는 바꾸지 마라 — "
                  "공개 발행은 되돌리기 어려워 사람이 정할 일이다. 사용자가 명시적으로 "
                  "공개를 요청했을 때만 --public 을 쓴다.",
                  "만든 뒤 실제로 푸시됐는지(exit 0 과 원격 URL) 확인하고 결과만 보고하라."]
    else:
        lines += ["gh 인증이 없어 계정을 알 수 없다 — 이건 사용자만 아는 정보다. "
                  "`gh auth login` 을 안내하거나 레포 URL 을 요구하라 "
                  "(이 질문은 허락 구하기 금지의 예외다).",
                  "URL 을 받으면 `git remote add origin <url>` + `git push -u origin HEAD`."]
    return Finding("check_git_remote", "git_remote", True, "\n".join(lines), ("origin 미설정으로 종료 차단",))


# git 조회 자체가 예외로 죽어도 통과가 아니다(fail-closed) — `stop_findings` 가 이걸 대신 낸다.
_REMOTE_UNKNOWN = Finding("check_git_remote", "git_remote", True,
                          "[GIT REMOTE] origin 판정 불능 — git 실행 실패도 통과가 아니라 차단이다(fail-closed). "
                          "git 이 도는지 확인하고 원격을 잡아라.", ("origin 판정 불능으로 종료 차단",))


# ── ⑯ 목업 잔존 ──────────────────────────────────────────────────────────────

def mockup_residue() -> Finding | None:
    """Stop 판정 ⑯ — 판단 끝난 목업이 남아 있으면 차단 finding(`wip_` 예외)."""
    if not MOCKUP_DIR.is_dir():
        return None
    residue = sorted(p for p in MOCKUP_DIR.rglob("*")
                     if p.is_file() and not p.name.startswith("wip_"))
    if not residue:
        return None
    lines = [f"[MOCKUP RESIDUE] docs/tasks/mockup/ 에 목업 {len(residue)}건이 남아있습니다."]
    lines += [f"  {path.relative_to(MOCKUP_DIR.parents[2]).as_posix()}" for path in residue]
    lines += ["판단이 끝난 목업은 비우고 종료하세요 — 채택분은 docs/tasks/archive/<작업>/ 로 옮기고",
              "반려분은 지웁니다. 검토가 세션을 넘겨 이어지면 wip_ 접두를 붙입니다."]
    return Finding("check_mockup_residue", "mockup_residue", True, "\n".join(lines), (f"{len(residue)}건",))


# ── ⑰ 과업 산출물 잔존 ───────────────────────────────────────────────────────

def board_is_busy() -> bool:
    """과업 보드에 진행 중 과업이 있는지.

    `#sid:` 태그가 붙은 행만 센다 — 태그는 과업 등록의 필수 요소이고, 서식을 안 지킨 파일이
    보드를 영구히 '진행 중'으로 만들어 잔존 검사를 영영 못 돌게 하는 것을 막는다.

    보드 조회가 실패하면 보드를 빈 것으로 본다 — 차단 판정이 보드 고장에 조용히 꺼지면 안 된다
    (예전엔 다른 훅 모듈을 임포트하다 그 모듈의 최상위 `sys.exit(0)` 에 잔존 검사째 끝났다).
    """
    try:
        rows = active_rows(board_dir())
    except Exception:
        return False
    return any("#sid:" in row for row in rows)


def _is_fresh(path: Path, now: float) -> bool:
    """방금 손댄 산출물인가 — 그렇다면 누군가 쓰는 중이다.
    stat 실패는 fresh 로 본다(판정 불능일 때는 막지 않는다 — board_is_busy 와 같은 방향)."""
    try:
        return now - path.stat().st_mtime < FRESH_SEC
    except OSError:
        return True


def task_leftovers() -> list[Path]:
    """루트에 남은 과업 산출물. 정렬은 출력 안정성 목적이다."""
    if not TASK_DIR.is_dir() or board_is_busy():
        return []
    now = time.time()
    return sorted(path for path in TASK_DIR.glob("*.md")
                  if path.is_file() and not path.name.startswith("wip_")
                  and not _is_fresh(path, now))


def task_residue() -> Finding | None:
    """Stop 판정 ⑰ — 보드가 빈데 docs/tasks/ 루트에 산출물이 남아 있으면 차단 finding."""
    leftover = task_leftovers()
    if not leftover:
        return None
    lines = [f"[TASK RESIDUE] docs/tasks/ 루트에 산출물 {len(leftover)}건이 남아있습니다."]
    lines += [f"  docs/tasks/{path.name}" for path in leftover]
    lines += ["구현이 끝났으면 docs/tasks/archive/YYYY-MM-DD-{작업명}/ 으로 옮기세요.",
              "판단이 세션을 넘겨 이어지는 중이면 wip_ 접두를 붙입니다."]
    return Finding("check_task_residue", "task_residue", True, "\n".join(lines), (f"{len(leftover)}건",))


# ── Codex Stop 묶음 ──────────────────────────────────────────────────────────

def stop_findings(sid: str) -> list[Finding]:
    """Codex Stop 이 부르는 다섯 판정 — Claude 의 Stop 훅 순서 그대로. 하나가 예외를 내도 나머지는 돈다.

    예외의 방향은 판정마다 다르다: git 원격만 fail-closed 라 대신 낼 finding 이 있고, 나머지는
    판정 불능 = 통과다. Claude 는 훅마다 프로세스가 따로라 이 묶음을 쓰지 않는다.
    """
    from kernel import worktree  # 잎 모듈이 Finding 을 여기서 가져가므로 위에서 import 하면 순환이다
    sid8 = sid[:8] if len(sid) >= 8 else None
    judgments: tuple[tuple[Callable[[], Finding | None], Finding | None], ...] = (
        (partial(board_residue, sid8), None),
        (git_remote, _REMOTE_UNKNOWN),
        (worktree.worktree_residue, None),
        (mockup_residue, None),
        (task_residue, None),
    )
    found: list[Finding] = []
    for judge, on_error in judgments:
        try:
            finding = judge()
        except Exception:
            finding = on_error
        if finding is not None:
            found.append(finding)
    return found
