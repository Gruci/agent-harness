"""PreToolUse(Bash|PowerShell) 훅 — 셸 명령이 깨면 안 되는 계약 4종을 사전 차단.

매처에 **셸을 실행하는 툴을 전부** 담아야 한다. `Bash` 만 걸면 같은 명령이 `PowerShell`
툴로 그냥 나간다(원본 프로젝트에서 2026-08-06 에 확인). 두 툴의 입력 필드가 똑같이 `command` 다.

| 절 | 막는 것 | 근거 |
|----|---------|------|
| 소스 쓰기 | 리다이렉트·tee·sed -i 로 레포 안 소스 파일 쓰기 | 작성 시점 게이트 우회 |
| 판정 우회 | 판정 명령(gh pr checks 등)을 파이프·체인 앞에 두기 | exit code 가 사라져 체크가 pending 인데도 merge 가 실행된다 |
| 공유 트리 변경 | 병렬 작업 중 공유 메인 체크아웃에서 실행하는 git 변경 명령 | add -A 가 남의 변경까지 담고 브랜치가 섞인다 |
| 격리 밖 링크 | 트리 밖·의존성 디렉토리를 잇는 junction·symlink 생성 | 한쪽을 지울 때 다른 쪽도 같이 지워진다 |

## 절 4 — 격리 밖 링크 (worktree 격리 무력화 방지)

worktree 마다 의존성을 다시 설치하기 싫어서 worktree 안의 `node_modules` 를 공유 체크아웃 쪽으로
junction 으로 연결한 적이 있다. 빌드 몇 초를 아끼려고 **격리된 worktree 와 공유 트리를 링크로 이어 놓은 것**이고,
worktree 를 지우는 과정 어딘가에서 그 링크를 따라가 공유 트리 쪽 내용이 비워졌다. 어느 삭제 명령이 링크를 따라갔는지는
재현하지 못했다. 그래서 **삭제 명령을 하나하나 막는 대신 링크가 생기는 것을 막는다.**
링크가 없으면 따라갈 경로도 없다.

판정 조건이 **두 가지**라는 점이 핵심이다. worktree 위치(`worktrees/`)가 레포 **안**에 있어서
「트리 밖을 가리키는가」 조건만으로는 그 사고 경로의 양쪽 끝이 모두 트리 안이 되어 걸리지 않는다. 의존성
디렉토리는 어느 방향으로도 링크할 이유가 없다. 그 트리에서 직접 설치하면 된다.

worktree 프로토콜이 지키려는 것은 격리다(`workboard/README.md`). 격리 밖을 가리키는 링크는 그 격리를 무너뜨린다.
격리 안에서 안으로 거는 링크는 격리를 깨지 않으므로 통과시킨다.

## 절 1 — 소스 쓰기 (작성 시점 게이트 우회 방지)

PostToolUse(Edit|Write) 게이트는 Edit·Write 툴로 바꾼 파일만 본다. `echo ... > foo.py` 는
그 게이트를 거치지 않아 Stop 훅이 세션 끝에서야 잡는다. 작성 시점 검사는 바로 그 지연을 없애려고 있다.
이 절은 CLAUDE.md "게이트 우회 금지" 규칙을 기계로 강제하는 부분이다.
**레포 안 + 소스 확장자** 두 조건에 모두 해당할 때만 차단한다. 스크래치패드, 레포 밖 경로, 로그는
통과시킨다. 게이트가 일상적인 셸 작업까지 막기 시작하면 우회하는 습관이 생겨 역효과가 난다.
확장자 정본은 프로파일(`SOURCE_EXT`·`UI_EXT`)이다. 커널이 검사하는 언어면 이 훅도 검사한다.

## 절 3 — 적용 조건과 합치기 예외

**링크된 worktree 가 하나라도 있으면** 적용한다. 격리가 강제된 뒤로는(`workboard/README.md` 작업 격리)
과업이 열려 있는 동안 늘 자기 worktree 가 있으므로 이 절도 늘 적용된다.

그래서 `git merge --ff-only` 는 막지 않는다. 완료 절차는 합치기 → 자기 worktree 제거 순서라, 이것까지 막으면
끝난 브랜치를 본체로 합칠 길이 없다(실제로 P2 합치기가 여기 막혔다). fast-forward 는 새 커밋을 만들지 않고
브랜치를 섞지 않는다. 덮어쓸 로컬 변경이 있으면 git 이 거부한다. `git switch`·`git checkout` 은 계속 막으므로
공유 체크아웃은 기본 브랜치에 머문다. 합친 트리는 이어지는 `git push` 에서 나올 때 검사(⑧-7)가 검사한다.
"""
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hookio import SEPARATORS, read_hook_payload, record, segments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

# 확장자 정본은 프로파일이다. 프로파일을 못 읽어도 훅은 동작해야 하므로 기본값으로 대신한다.
_FALLBACK_EXT = (".py", ".ts", ".tsx", ".md", ".css", ".html", ".json")
sys.path.insert(0, str(ROOT))
try:
    from kernel import profile as _profile
    SOURCE_SUFFIXES = tuple(dict.fromkeys(
        [ext.lstrip("*").lower() for ext in (*_profile.SOURCE_EXT, *_profile.UI_EXT)]
        + list(_FALLBACK_EXT)))
except Exception:
    SOURCE_SUFFIXES = _FALLBACK_EXT

REDIRECTS = (">", ">>")

# 절 2 — 판정 명령. 뒤에 파이프나 체인이 붙으면 판정 명령의 exit code 가 사라진다.
# merge 는 되돌릴 수 없어서 CI 확인 명령만 넣는다. 빌드·테스트 체인은 되돌릴 수 있으므로 막지 않는다.
# 하네스는 쌓여서 문제가 되는 것과 되돌릴 수 없는 것만 강제한다.
VERDICT_COMMANDS = ("gh pr checks", "gh run watch")

# 절 2-1 — `gh pr merge --auto`. 이름만 보면 "체크 통과를 기다렸다가 머지"라 판정을 대신해 주는 것처럼
# 보이지만, 무엇을 기다릴지는 **branch protection 필수 체크**가 정한다. 필수 체크가 없는 레포에서 auto 는
# 기다릴 대상이 없어 즉시 머지한다(머지가 곧 배포 트리거일 수 있다). 절 2 가 파이프 때문에 판정 결과를 잃는 경우라면
# 이 절은 판정을 GitHub 에 맡겼다고 착각하는 경우다.
AUTO_MERGE = "gh pr merge"

# 절 3 — 병렬 작업 중 공유 메인 체크아웃에서 금지하는 git 변경 명령.
# `git checkout` 은 파일 복원에도 쓰이지만, 실제 사고는 브랜치 전환으로 났기 때문에 전부 막는다.
MUTATING_GIT = ("git commit", "git add", "git switch", "git checkout", "git merge")
# 끝난 브랜치를 본체로 합치는 명령. 새 커밋을 만들지 않고 브랜치를 섞지 않으므로 병렬 중에도 통과시킨다.
FAST_FORWARD = "--ff-only"


def _tokens(command: str) -> list[str]:
    """셸 토큰 목록. 정규식 대신 shlex 를 쓰는 이유는 따옴표 때문이다. `grep "> a.py"` 의 `>` 는
    리다이렉트가 아닌데 정규식은 이를 구분하지 못해 막지 않아야 할 명령까지 막는다. `punctuation_chars` 가 `>`·`|` 를
    별도 토큰으로 떼어 주므로 연산자와 인자를 구분해 읽을 수 있다.

    debt:따옴표가 안 맞아 파싱이 깨지면 빈 목록(=통과)이다. 그런 명령은 셸도 못 돌린다.
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return []


def _repo_source(target: str) -> str | None:
    """이 토큰이 '레포 안 소스 파일 경로'면 레포 상대경로, 아니면 None."""
    if not target or target.startswith(("&", "$", "-")) or target.startswith("/dev/"):
        return None
    path = Path(target)
    resolved = path if path.is_absolute() else ROOT / path
    try:
        rel = resolved.resolve().relative_to(ROOT)
    except (ValueError, OSError):
        return None                      # 레포 밖 — 스크래치패드·임시파일·시스템 경로
    if resolved.suffix.lower() not in SOURCE_SUFFIXES:
        return None
    return rel.as_posix()


def _write_candidates(tokens: list[str]) -> list[str]:
    """쓰기 대상이 될 수 있는 토큰 목록. 리다이렉트 대상, `tee` 인자, `sed -i` 대상 파일을 본다.

    debt:이 셋만 본다. `python -c "open('x.py','w')"`·`mv`·`cp` 로 파일을 제자리에 넣는 경로는
    잡지 않는다. 셸 문법 전체를 재현하는 일반적인 해법은 없고, 실제로 쓰이는 우회는 이 셋이다.
    새로운 우회가 확인되면 여기에 조건을 추가한다.
    """
    candidates: list[str] = []
    in_sed = sed_inplace = False
    for index, token in enumerate(tokens):
        if token in SEPARATORS:
            in_sed = sed_inplace = False
        elif token in REDIRECTS:
            candidates += tokens[index + 1: index + 2]
        elif token == "tee":
            candidates += [t for t in tokens[index + 1:] if not t.startswith("-")][:1]
        elif token == "sed":
            in_sed, sed_inplace = True, False
        elif in_sed and token.startswith("-i"):
            sed_inplace = True
        elif sed_inplace and not token.startswith("-"):
            candidates.append(token)
    return candidates


def blocked_targets(command: str) -> list[str]:
    """셸 명령이 쓰려는 레포 안 소스 파일들 (레포 상대경로, 중복 제거)."""
    found: list[str] = []
    for candidate in _write_candidates(_tokens(command)):
        rel = _repo_source(candidate)
        if rel and rel not in found:
            found.append(rel)
    return found


def piped_verdict(command: str) -> str | None:
    """판정 명령이 마지막 조각이 아니면 그 명령 이름, 아니면 None.

    `gh pr checks --watch | tail -2 && gh pr merge` 에서 체인의 exit code 는 tail 의 것이라
    checks 가 pending 이어도 merge 가 실행된다. 판정 명령이 마지막 조각이면 그 exit code 가 그대로 남으므로
    통과시킨다. `echo hi && gh pr checks` 는 막지 않는다.
    """
    for segment in segments(_tokens(command))[:-1]:
        head = " ".join(segment[:3])
        hit = next((verdict for verdict in VERDICT_COMMANDS if head.startswith(verdict)), None)
        if hit:
            return hit
    return None


def auto_merge(command: str) -> bool:
    """`gh pr merge` 조각에 `--auto` 가 붙었는지 본다.

    조각의 앞 3토큰으로 명령을 식별하는 이유는 `_makes_link` 와 같다. 커밋 메시지
    본문 안의 `gh pr merge --auto` 를 명령으로 잘못 읽지 않기 위해서다.
    """
    for segment in segments(_tokens(command)):
        if " ".join(segment[:3]).startswith(AUTO_MERGE) and "--auto" in segment:
            return True
    return False


_LINK_ITEM_TYPES = ("junction", "symboliclink", "hardlink")

# 언어와 무관한 의존성·빌드 산출물 디렉토리. 어느 방향으로도 링크할 이유가 없고, 그 트리에서 직접 설치하면 된다.
# 커널은 프로젝트 언어를 모르므로 이름 하나가 아니라 여러 개를 둔다. 새 언어 생태계를 지원하면 여기에 더한다.
DEP_DIRS = ("node_modules", ".venv", "venv", "vendor", "target", "Pods", ".gradle")


def _makes_link(segment: list[str]) -> bool:
    """이 조각이 junction·symlink 를 만드는 명령인지 본다. cmd `mklink`, PowerShell `New-Item -ItemType
    Junction`, POSIX `ln -s` 세 형태를 본다.

    **조각의 앞 3토큰만** 본다. 토큰 전체를 훑으면 커밋 메시지 heredoc 안의 `ln -s` 같은
    본문을 명령으로 잘못 읽는다. 원본 프로젝트에서 이 훅이 그렇게 자기 커밋을 막은 적이 있다. `_tokens` 가 따옴표를
    풀어 주는 것과 같은 이유로, 명령인지 인자인지는 토큰의 위치로 판단한다.
    """
    head = [t.lower() for t in segment[:3]]
    if not head:
        return False
    if "mklink" in head:                       # `cmd /c mklink /J ...` 형태라 앞 3토큰을 본다
        return True
    if "new-item" in head:
        return any(t.lower() in _LINK_ITEM_TYPES for t in segment)
    if head[0] == "ln":
        return any(t.startswith("-") and "s" in t for t in head)
    return False


def outbound_link(command: str) -> str | None:
    """트리 **밖**을 가리키거나 의존성 디렉토리를 잇는 링크 생성 경로.

    경로 후보로는 경로 구분자가 들어 있는 토큰만 본다. `-Target` 같은 플래그 이름과 `Junction` 같은 값은
    경로가 아니기 때문이다. 아직 존재하지 않는 경로도 검사한다(`-Path` 는 명령 실행 전에는 아직 없다).
    """
    for segment in segments(_tokens(command)):
        if not _makes_link(segment):
            continue
        for token in segment:
            if not token or token.startswith("-") or ("/" not in token and "\\" not in token):
                continue
            parts = token.replace("\\", "/").split("/")
            if any(part in DEP_DIRS for part in parts):
                return token
            candidate = Path(token)
            if not candidate.is_absolute():
                candidate = ROOT / token
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if ROOT not in resolved.parents and resolved != ROOT:
                return token
    return None


def _is_main_checkout() -> bool:
    """공유 메인 체크아웃인지 판정한다. 링크된 worktree 는 `.git` 이 파일이고 메인은 디렉토리다.

    `cwd == ROOT` 로는 구분할 수 없다. 훅 파일이 트리마다 복사돼 있어 양쪽 모두 참이 된다.
    """
    return (ROOT / ".git").is_dir()


def _parallel_mode() -> bool:
    """링크된 worktree 가 하나라도 있으면 병렬 작업 중으로 본다. 판정할 수 없으면 병렬이 아닌 것으로 보고 이 절을 적용하지 않는다."""
    try:
        done = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=str(ROOT),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=15)
    except Exception:
        return False
    if done.returncode != 0:
        return False
    records = [line for line in done.stdout.splitlines() if line.startswith("worktree ")]
    return len(records) > 1                              # 첫 레코드(메인) 이후가 있는가


def shared_tree_mutation(command: str) -> str | None:
    """병렬 작업 중 공유 트리를 대상으로 하는 git 변경 명령. worktree 안에서는 항상 None 이라
    프로토콜을 지키는 작업은 막히지 않는다. `git -C <worktree> commit` 도 대상이 공유 트리가 아니므로
    통과한다.
    """
    if not _is_main_checkout() or not _parallel_mode():
        return None
    for segment in segments(_tokens(command)):
        head = " ".join(segment[:3])
        hit = next((mutation for mutation in MUTATING_GIT if head.startswith(mutation)), None)
        if hit == "git merge" and FAST_FORWARD in segment:
            continue
        if hit:
            return hit
    return None


def main() -> None:
    try:
        payload = read_hook_payload()
    except Exception as exc:
        # 하네스 오작동은 비차단(exit 1)이다. 여기서 exit 2 를 내면 Bash 가 통째로 막히고,
        # 셸이 막힌 세션은 복구 수단이 없다.
        print(f"[BASH GATE] 훅 페이로드 파싱 실패({exc.__class__.__name__}) — 셸 명령 검사가 동작하지 않는다. 훅을 점검하라.",
              file=sys.stderr)
        sys.exit(1)

    command = (payload.get("tool_input") or {}).get("command") or ""
    message = _violation(command)
    if message is None:
        sys.exit(0)
    print(message, file=sys.stderr)
    record("check_bash_write", "bash_write", sid=str(payload.get("session_id") or ""),
           msg=message.splitlines()[0])
    sys.exit(2)


def _violation(command: str) -> str | None:
    """첫 위반의 안내문. 절 순서가 곧 우선순위다."""
    targets = blocked_targets(command)
    if targets:
        return ("[BASH GATE] 셸로 소스 파일을 쓰려 한다 — " + " · ".join(targets) + ".\n"
                "Edit/Write 툴로 하라. Bash 리다이렉트는 작성 시점 게이트를 우회한다.\n"
                "임시 산출물이면 스크래치패드 경로로 내보내라(레포 밖은 검사하지 않는다).")

    verdict = piped_verdict(command)
    if verdict:
        return (f"[BASH GATE] `{verdict}` 뒤에 파이프나 체인이 붙어 있다 — 이 명령의 exit code 가 사라진다.\n"
                "판정 명령은 단독으로 실행하고, 성공을 확인한 뒤 merge 를 별도 호출로 실행하라.")

    if auto_merge(command):
        return ("[BASH GATE] `gh pr merge --auto` — auto 가 기다리는 대상은 branch protection 필수 체크다.\n"
                "필수 체크가 없는 레포에서 auto 는 기다릴 대상이 없어 즉시 머지한다(기다리는 것처럼 보이기만 한다).\n"
                "`gh pr checks <PR>` 을 단독 실행해 pass 를 확인한 뒤 `--auto` 없이 머지하라.")

    link = outbound_link(command)
    if link:
        return (f"[BASH GATE] 격리 밖을 가리키는 링크를 만들려 한다 — `{link}`.\n"
                "worktree 는 격리가 목적이다. 밖으로 링크를 이으면 한쪽을 지울 때 다른 쪽도 같이 지워진다\n"
                "(원본 프로젝트 사고: node_modules 를 junction 으로 연결했다가 공유 체크아웃 쪽이 비워졌다).\n"
                "의존성은 그 트리에서 직접 깔아라. 파일이 필요하면 링크 말고 복사하라.")

    mutation = shared_tree_mutation(command)
    if mutation:
        return (f"[BASH GATE] 병렬 작업 중에 공유 메인 체크아웃에서 `{mutation}` 을 실행하려 한다 — 구현과 커밋은 자기 worktree 에서만 한다.\n"
                "EnterWorktree 로 격리하거나, 이미 만든 worktree 가 있으면 `git -C <worktree경로>` 로 실행하라.\n"
                "끝난 브랜치를 합치는 중이면 `git merge --ff-only <브랜치>` 로 실행하라.\n"
                "(정본: workboard/README.md 작업 격리)")
    return None


if __name__ == "__main__":
    main()
