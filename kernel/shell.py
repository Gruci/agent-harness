"""kernel/shell.py — 셸 명령줄을 단순 명령 목록으로 읽는다. 셸 명령을 판정하는 검사들의 공용 입력이다.

나올 때 검사(`kernel/exit_gate.py`), worktree 이름 검사(`kernel/worktree.py`), Claude 셸 계약 훅
(`.claude/hooks/check_bash_write.py`)이 같은 읽기를 쓴다. 판정은 각자 하고 여기는 읽기만 한다.
표준 라이브러리 밖을 import 하지 않는다 — 훅 폴더가 이 파일만 읽어도 돌게 하기 위해서다.

## 명령은 조각의 머리에만 있다

명령은 구분자로 끊은 조각(단순 명령)의 맨 앞에서만 찾는다. `echo "git push"` 의 인자와 커밋 메시지 안의
문장은 명령이 아니다. 이 원칙은 그대로 두고, 머리를 가리던 것만 걷어 낸다.

| 걷어 내는 것 | 예 | 왜 |
|---|---|---|
| heredoc·here-string 본문 | `<<'EOF' … EOF`, `@' … '@` | 본문은 데이터다. here-string 안의 `'` 하나가 따옴표 짝을 깨면 명령줄 전체가 판정 밖으로 빠졌다 |
| 줄바꿈·묶음 기호 | 줄바꿈, `(` `)` `{` `}` | PowerShell 은 `A; if ($?) { B }` 로 잇는다. 묶음 안의 B 도 명령이다 |
| 앞에 붙는 말 | `X=1`, `$r =`, `if`·`then`·`do`·`!`·`time`·`env`·`command`·`exec` | 셸 문법상 그 뒤가 명령이다 |
| 감싼 셸 | `cmd /c …`, `powershell -c …`, `bash -c …` | 안쪽 문자열이 실제 명령이다 |
| git 전역 옵션 | `-c k=v`, `--no-pager`, `-C <경로>` | 하위 명령이 셋째 칸에서 밀려난다 |

## 실행 위치

`cd`·`pushd`·`popd`·`Set-Location`·`Push-Location`·`Pop-Location` 을 따라가 명령마다 도는 위치를 함께 준다.
상대경로를 훅 페이로드의 cwd 로만 풀면 `cd <스크래치> && sed -i … a.py` 가 레포 파일로 읽혀 막혔다.
`( … )` 와 감싼 셸 안의 이동은 밖으로 새지 않는다. 같은 명령줄에서 대입만 있는 단순 명령(`SP=/x`·PowerShell
`$sp = 'C:\\x'`)의 값은 기억해 두고, 이동 대상의 `$NAME`·`${NAME}` 을 그 값으로 푼다 — `cd "$SP"` 를 못 풀어 스크래치
쓰기가 레포 파일로 읽혀 막혔다. 값에 `$` 가 든 대입(`$(…)`)은 기억하지 않는다. 그래도 따라갈 수 없는 이동(모르는
변수·`-`·인자 없음)을 만나면 위치를 None 으로 되돌린다. 소비자는 None 을 페이로드 cwd 로 읽으므로 이 경우는 예전 동작과 같다.
"""

from __future__ import annotations

import os
import re
import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path

_PUNCTUATION = "();<>|&{}\n"
_SEPARATOR_CHARS = frozenset(";&|(){}\n")
_HERE_STRING = re.compile(r"@(['\"])[ \t]*\r?\n.*?\r?\n\1@", re.S)
_HEREDOC = re.compile(r"(?<!<)<<-?[ \t]*(['\"]?)([A-Za-z_][\w-]*)\1(?!<)")
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_VARIABLE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
_BRACED_VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_PREFIX_WORDS = frozenset({"if", "then", "else", "elif", "do", "while", "until", "!", "time",
                           "env", "command", "exec"})
_MOVE = frozenset({"cd", "chdir", "pushd", "set-location", "sl", "push-location"})
_PUSH = frozenset({"pushd", "push-location"})
_POP = frozenset({"popd", "pop-location"})
_MOVE_FLAGS = frozenset({"/d", "-path", "-literalpath"})
_GIT_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env",
                                "--super-prefix", "--attr-source"})
_WRAPPER_FLAGS = {"cmd": ("/c", "/k"), "powershell": ("-c", "-command"), "pwsh": ("-c", "-command")}
_POSIX_SHELLS = frozenset({"bash", "sh", "zsh", "dash"})
_MAX_DEPTH = 3


@dataclass(frozen=True)
class Command:
    """단순 명령 하나. argv 는 앞에 붙는 말과 감싼 셸을 걷어 낸 토큰이고, workdir 은 그 명령이 도는 위치다.

    workdir 은 페이로드 cwd 기준 상대경로이거나 절대경로이고, None 이면 페이로드 cwd 다.
    """
    argv: tuple[str, ...]
    workdir: str | None


def program(token: str) -> str:
    """명령 이름 — 경로와 `.exe` 를 떼고 소문자로. `C:/Program Files/Git/cmd/git.exe` 는 `git` 이다."""
    return Path(token).name.lower().removesuffix(".exe")


def native(token: str) -> str:
    """경로 토큰을 이 OS 의 경로 문자열로. `~` 를 풀고, Windows 에서는 Git Bash 경로(`/c/…`·`/tmp`)를 옮긴다."""
    path = os.path.expanduser(token)
    if os.name == "nt":
        drive = re.match(r"/([A-Za-z])(/|$)", path)
        if drive:
            return f"{drive.group(1).upper()}:/{path[3:]}"
        if path == "/tmp" or path.startswith("/tmp/"):
            return Path(tempfile.gettempdir()).as_posix() + path[4:]
    return path


def join(base: str | None, path: str | None) -> str | None:
    """위치 둘을 잇는다. 뒤가 절대경로면 뒤가 이긴다. 둘 다 없으면 None(페이로드 cwd)."""
    if path is None:
        return base
    if base is None:
        return Path(path).as_posix()
    return (Path(base) / path).as_posix()


def commands(command: str) -> list[Command]:
    """명령줄의 단순 명령들. 따옴표 짝이 깨져 셸도 실행할 수 없는 줄은 빈 목록이다."""
    return _parse(command, None, 0)


def git_args(argv: tuple[str, ...]) -> tuple[str | None, tuple[str, ...]] | None:
    """git 명령이면 (`-C` 경로, 전역 옵션 뒤의 하위 명령과 인자). git 이 아니면 None."""
    if not argv or program(argv[0]) != "git":
        return None
    git_dir: str | None = None
    index = 1
    while index < len(argv) and argv[index].startswith("-"):
        option = argv[index]
        if option in _GIT_VALUE_OPTIONS and index + 1 < len(argv):
            if option == "-C":
                git_dir = join(git_dir, native(argv[index + 1]))
            index += 2
        else:
            index += 1
    return git_dir, argv[index:]


_REDIRECTS = (">", ">>", "&>", "&>>")
_SED_SCRIPT_OPTIONS = frozenset({"-e", "-f", "--expression", "--file"})
_PS_WRITERS = frozenset({"set-content", "sc", "add-content", "ac", "out-file", "tee-object"})
_PS_PATH_PARAMS = frozenset({"-path", "-literalpath", "-filepath", "-lp", "-pspath"})
_PS_SWITCHES = frozenset({"-force", "-nonewline", "-append", "-noclobber", "-whatif", "-confirm",
                          "-passthru", "-asbytestream"})


def write_targets(argv: tuple[str, ...]) -> list[str]:
    """이 명령이 내용을 쓰는 파일 토큰 — 리다이렉트 대상, `tee`·`sed -i` 대상, PowerShell 쓰기 cmdlet 의 경로.

    debt:`cp`·`mv`·`python -c "open(...)"` 로 파일을 제자리에 넣는 경로는 읽지 않는다. 셸 문법 전체를 재현하는
    일반 해법은 없고, 실제로 쓰인 우회만 하나씩 더한다.
    """
    found = [argv[index + 1] for index, token in enumerate(argv[:-1]) if token in _REDIRECTS]
    name, rest = program(argv[0]), argv[1:]
    if name == "tee":
        found += [token for token in rest if not token.startswith("-")][:1]
    elif name == "sed" and any(token.startswith(("-i", "--in-place")) for token in rest):
        found += _sed_files(rest)
    elif name in _PS_WRITERS or (name in ("new-item", "ni")
                                 and any(token.lower().startswith("-value") for token in rest)):
        target = _cmdlet_path(rest)
        found += [target] if target else []
    return found


def _sed_files(rest: tuple[str, ...]) -> list[str]:
    """`sed` 의 파일 피연산자. `-e`·`-f` 가 없으면 첫 피연산자는 스크립트다(`s/a.py/b.py/` 를 파일로 읽지 않는다)."""
    operands: list[str] = []
    scripted = skip = False
    for token in rest:
        if skip:
            skip = False
        elif token in _SED_SCRIPT_OPTIONS:
            scripted = skip = True
        elif token.startswith(("--expression=", "--file=")):
            scripted = True
        elif not token.startswith("-"):
            operands.append(token)
    return operands if scripted else operands[1:]


def _cmdlet_path(rest: tuple[str, ...]) -> str | None:
    """PowerShell 쓰기 cmdlet 의 대상. 경로 매개변수가 먼저고, 없으면 첫 위치 인자다(네 cmdlet 모두 0번 위치가 경로)."""
    positional: str | None = None
    index = 0
    while index < len(rest):
        token = rest[index]
        key, colon, _value = token.lower().partition(":")
        if key in _PS_PATH_PARAMS:
            if colon:
                return token.split(":", 1)[1]
            return rest[index + 1] if index + 1 < len(rest) else None
        if token.startswith("-"):
            index += 1 if (key in _PS_SWITCHES or colon) else 2
            continue
        positional = positional or token
        index += 1
    return positional


def _clean(command: str) -> str:
    """here-string 과 heredoc 본문을 지우고, `${NAME}` 을 `$NAME` 으로, Windows 경로 구분자를 `/` 로 바꾼다.

    posix 모드의 shlex 는 백슬래시를 이스케이프로 먹어 `C:\\a\\b.py` 가 `C:ab.py` 가 된다(`kernel/worktree.py` 와 같은 처리).
    `{`·`}` 는 묶음 기호라 구분자로 읽으므로, 변수의 중괄호 표기는 토큰이 되기 전에 푼다.
    """
    text = _BRACED_VARIABLE.sub(r"$\1", _HERE_STRING.sub("''", command))
    kept: list[str] = []
    ends: list[str] = []
    for line in text.splitlines():
        if ends:
            if line.strip() == ends[0]:
                ends.pop(0)
            continue
        kept.append(line)
        ends = [found.group(2) for found in _HEREDOC.finditer(line)]
    return "\n".join(kept).replace("\\", "/")


def _tokens(command: str) -> list[str]:
    """셸 토큰. 주석은 shlex 가 아니라 `_parse` 가 지운다 — shlex 는 낱말 한가운데의 `#` 에서도 줄을 잘라
    `git commit -m fix#12 && git push` 의 push 를 잃는다. 셸은 `#` 로 시작하는 낱말부터만 주석으로 본다."""
    lexer = shlex.shlex(_clean(command), posix=True, punctuation_chars=_PUNCTUATION)
    lexer.whitespace_split = True
    lexer.whitespace = " \t\r"
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        return []


def _parse(command: str, workdir: str | None, depth: int) -> list[Command]:
    found: list[Command] = []
    opened: list[str | None] = []              # `(` 에서 들어갈 때의 위치 — `)` 에서 되돌린다
    pushed: list[str | None] = []              # pushd·Push-Location 이전 위치
    known: dict[str, str] = {}                 # 이 명령줄에서 대입만으로 정해진 변수 값 — 이동 대상을 푸는 데 쓴다
    current: list[str] = []
    comment = False                            # `#` 로 시작한 낱말부터 줄 끝까지
    for token in [*_tokens(command), ";"]:
        separator = set(token) <= _SEPARATOR_CHARS
        if comment and not (separator and "\n" in token):
            continue
        comment = False
        if not separator and token.startswith("#"):
            comment, token = True, ";"
        elif not separator:
            current.append(token)
            continue
        if current:
            workdir = _simple(tuple(current), workdir, depth, found, pushed, known)
            current = []
        for mark in token:
            if mark == "(":
                opened.append(workdir)
            elif mark == ")" and opened:
                workdir = opened.pop()
    return found


def _remember(argv: tuple[str, ...], known: dict[str, str]) -> bool:
    """대입만 있는 단순 명령(`SP=/x`·`$sp = 'C:/x'`)이면 값을 기억하고 True. 값에 `$` 가 들면 기억하지 않는다."""
    if len(argv) == 3 and argv[0].startswith("$") and argv[1] == "=":
        name, value = argv[0][1:], argv[2]
    elif len(argv) == 1 and _ASSIGNMENT.match(argv[0]):
        name, _sep, value = argv[0].partition("=")
    else:
        return False
    if "$" not in value:
        known[name.lower()] = value
    return True


def _expand(target: str, known: dict[str, str]) -> str | None:
    """`$NAME`·`${NAME}` 을 아는 값으로 푼다. 하나라도 모르면 None — 따라갈 수 없는 이동이다."""
    missing = [name for name in _VARIABLE.findall(target) if name.lower() not in known]
    if missing or "%" in target:
        return None
    return _VARIABLE.sub(lambda found: known[found.group(1).lower()], target)


def _simple(argv: tuple[str, ...], workdir: str | None, depth: int,
            found: list[Command], pushed: list[str | None], known: dict[str, str]) -> str | None:
    """단순 명령 하나를 found 에 더하고, 그 뒤의 위치를 돌려준다."""
    if _remember(argv, known):
        return workdir
    argv = _strip_prefix(argv)
    if not argv:
        return workdir
    found.append(Command(argv, workdir))
    inner = _wrapped(argv)
    if inner is not None and depth < _MAX_DEPTH:
        found.extend(_parse(inner, workdir, depth + 1))      # 감싼 셸 안의 이동은 밖으로 새지 않는다
        return workdir
    name = program(argv[0])
    if name in _POP:
        return pushed.pop() if pushed else None
    if name not in _MOVE:
        return workdir
    if name in _PUSH:
        pushed.append(workdir)
    targets = [token for token in argv[1:] if token.lower() not in _MOVE_FLAGS]
    target = _expand(targets[0], known) if len(targets) == 1 and targets[0] != "-" else None
    if target is None:
        return None                                          # 따라갈 수 없다 — 페이로드 cwd 로 읽는다
    return join(workdir, native(target))


def _strip_prefix(argv: tuple[str, ...]) -> tuple[str, ...]:
    """머리 앞의 대입(`X=1`·PowerShell `$r =`)과 예약어·실행 유틸리티(`env` 의 옵션까지)를 걷어 낸다."""
    index, after_env = 0, False
    while index < len(argv):
        token = argv[index]
        if token.startswith("$") and argv[index + 1: index + 2] == ("=",):
            index += 2
        elif token in _PREFIX_WORDS or _ASSIGNMENT.match(token) or (after_env and token.startswith("-")):
            after_env = after_env or token == "env"
            index += 1
        else:
            break
    return argv[index:]


def _wrapped(argv: tuple[str, ...]) -> str | None:
    """감싼 셸(`cmd /c`·`powershell -c`·`bash -c`)이면 안쪽 명령 문자열. 아니면 None."""
    name = program(argv[0])
    if name in _WRAPPER_FLAGS:
        index = next((i for i, token in enumerate(argv) if i and token.lower() in _WRAPPER_FLAGS[name]), None)
        rest = argv[index + 1:] if index is not None else ()
        return (rest[0] if len(rest) == 1 else shlex.join(rest)) if rest else None
    if name in _POSIX_SHELLS:
        index = next((i for i, token in enumerate(argv) if i and re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", token)), None)
        return argv[index + 1] if index is not None and index + 1 < len(argv) else None
    return None
