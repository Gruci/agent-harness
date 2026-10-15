"""kernel/linters.py — 그 언어의 표준 도구에 위임한다.

커널이 Go 의 구문 트리를 다시 파싱할 이유가 없다. Go 에는 `go vet` 과 `staticcheck` 가
있고 Rust 에는 `clippy` 가 있다. 우리가 만든 어설픈 정규식보다 그쪽이 정확하다.

하네스가 대신 하는 일은 **위임과 정직한 보고**다.

  도구가 있다   → 돌리고 출력을 위반으로 읽는다
  도구가 없다   → [TOOL] 로 찍고 설치 명령을 준다. 통과로 처리하지 않는다

마지막 줄이 핵심이다. 도구가 없는 것을 조용히 넘기면 "검사했는데 깨끗함"과 "검사 자체를 못 함"이
구분되지 않는다 — 이 하네스가 없애려는 상태 그대로다.

언어팩의 `LINTERS` 가 선언 정본이다:

    LINTERS = [
        {"slug": "vet", "cmd": ["go", "vet", "./..."], "parse": "gcc",
         "install": "go 툴체인에 포함"},
    ]

화면 레이어는 언어팩이 아니라 아래 「화면 린터」가 같은 원칙으로 위임한다. 검사 10·17~20·42 의
판정 정본은 `kernel/eslint.harness.mjs` 하나이고, 러너는 npm 프로젝트의 `node_modules/.bin/eslint`
로 그 설정을 돌리고, 메시지 앞의 `[slug]` 로 결과를 여섯 섹션에 나눈다. 예전의 줄 단위 정규식은 문자열과 코드를
구분하지 못해, 주석 속 색 값이 걸리고 여러 줄에 걸친 표현은 놓쳤다.

규칙 본문은 스크립트 AST 기준이라 프레임워크를 모른다. 어느 파서로 AST 를 만들고 어느 확장자를 볼지는
화면 프레임워크팩(`kernel/framework.py`)이 선언하고, 러너가 환경변수 HARNESS_UI_PARSER ·
HARNESS_UI_PARSER_OPTIONS · HARNESS_UI_PARSERS(확장자별 파서) · HARNESS_UI_FILES 로 설정 파일에 넘긴다.
worktree 에는 `node_modules` 가 없으므로 공유 체크아웃의 설치를 쓰고, 그 위치를 HARNESS_UI_MODULES 로 넘긴다.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from kernel import profile
from kernel.context import ROOT, _rel
from kernel.workboard import board_dir

TIMEOUT_SECONDS = 90

# `path:line:col: message` 와 `path:line: message` — 대부분의 도구가 이 모양으로 낸다.
_GCC_LINE = re.compile(r"^(?P<path>\S.*?):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?P<msg>.+)$")
_TSC_LINE = re.compile(r"^(?P<path>.+)\((?P<line>\d+),(?P<col>\d+)\):\s*(?P<msg>.+)$")


def _parse_gcc(output: str, slug: str) -> list[str]:
    found: list[str] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "warning: ", "note: ")):
            continue
        match = _GCC_LINE.match(line) or _TSC_LINE.match(line)
        if not match:
            continue
        path = match.group("path").replace("\\", "/")
        if path.startswith("./"):
            path = path[2:]
        found.append(f"{path}:{match.group('line')}: {match.group('msg').strip()} ({slug})")
    return found


def _entry_name(entry: dict) -> str:
    return str(entry.get("slug") or (entry.get("cmd") or ["tool"])[0])


def missing_tool(entry: dict) -> str:
    """실행 파일이 없으면 그 이름. 있으면 빈 문자열."""
    cmd = entry.get("cmd") or []
    return "" if (cmd and shutil.which(cmd[0])) else (cmd[0] if cmd else "cmd not declared")


def run_one(entry: dict) -> tuple[list[str], str]:
    """한 도구를 돌린다. 반환은 (위반 목록, 건너뛴 사유). 사유가 있으면 [TOOL]."""
    slug = _entry_name(entry)
    parser_name = str(entry.get("parse", "gcc"))
    if parser_name != "gcc":                       # 지원하는 출력 형식은 gcc 하나다
        return [], f"{slug}: unknown output parser {parser_name}"
    absent = missing_tool(entry)
    if absent:
        hint = entry.get("install") or ""
        tail = f" — install: {hint}" if hint else ""
        return [], f"{absent} not installed{tail}"
    # 실행 파일을 경로로 풀어서 부른다 — Windows 의 `npx` 는 `npx.CMD` 셈이라 이름만으로는 CreateProcess 가 못 찾는다.
    cmd = [shutil.which(entry["cmd"][0]) or entry["cmd"][0], *entry["cmd"][1:]]
    try:
        done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return [], f"{slug}: no response within {TIMEOUT_SECONDS}s — check could not run"
    except OSError as exc:
        return [], f"{slug}: run failed {exc.__class__.__name__}"

    output = (done.stdout or "") + "\n" + (done.stderr or "")
    found = _parse_gcc(output, slug)
    if done.returncode and not found:
        return [], f"{slug}: exit code {done.returncode}, no parsable diagnostics — {output.strip()[:300]}"
    return found, ""


def sections() -> list[tuple[str, str, list[str], str]]:
    """언어팩이 선언한 도구 전부. 반환은 (slug, 제목, 위반, 건너뛴 사유)."""
    found: list[tuple[str, str, list[str], str]] = []
    for entry in profile.LINTERS:
        if not isinstance(entry, dict):
            continue
        slug = _entry_name(entry)
        title = f"Static analysis ({slug})"
        violations, skipped = run_one(entry)
        found.append((f"lint:{slug}", title, violations, skipped))
    return found


# ── 화면 린터 ────────────────────────────────────────────────────────────────

UI_SLUGS = ("ts_any", "raw_fetch", "hex_literal", "responsive", "browser_api", "hash_nav")
UI_CONFIG = Path(__file__).resolve().parent / "eslint.harness.mjs"
_SLUG_TAG = re.compile(r"^\[(\w+)\]\s*")
# 프로파일 `ui_admin` 레이어를 면제하는 네 검사. 경로에 /admin/ 이 들어 있다고 면제하던 암묵 규칙은 없앴다 —
# 선언 없이 검사 넷이 꺼져 편집 표면 래칫에도 안 보였다.
_ADMIN_SLUGS = ("raw_fetch", "hex_literal", "responsive", "browser_api")
# 테스트는 토큰 값을 단언하느라 색 리터럴을 쓴다
_TEST_GLOBS = ("**/*.test.*", "**/*.spec.*")


@dataclass
class UiLint:
    found: dict[str, list[str]]     # slug → 위반 문장(`경로:행: 메시지`)
    missing: str                    # 비어 있지 않으면 [TOOL] 사유


def ui_npm_dir() -> Path | None:
    """node_modules 를 가진 npm 프로젝트. 프로파일 `UI_NPM_DIR` 이 우선이고, 없으면 ui 레이어 경로의 첫 세그먼트다.
    프리셋 세 개가 모두 `frontend/src` 라 대개 이 추론으로 충분하고, 다르면 선언을 따른다."""
    ui = profile.layer("ui")
    if not ui:
        return None
    return ROOT / (profile.UI_NPM_DIR or ui.split("/", 1)[0])


def _shared_npm_dir(npm_dir: Path) -> Path | None:
    """worktree 라면 공유 체크아웃의 같은 npm 폴더. `node_modules` 는 git 이 추적하지 않아 worktree 에 없다 —
    링크를 만들지 않고 공유 체크아웃의 설치를 그대로 쓴다. 이미 공유 체크아웃이거나 루트 밖이면 None."""
    shared = board_dir().parent
    try:
        twin = shared / npm_dir.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return None
    return twin if twin.resolve() != npm_dir.resolve() else None


def ui_eslint_bin(npm_dir: Path) -> Path | None:
    """실행 파일이 실제로 있는지 본다. `npx --no-install` 은 패키지가 없으면 npm 오류만 내고 끝나는데, 파서는 이를
    위반 0건으로 읽어 조용히 통과시킨다. 그래서 실행 파일의 존재로 판단한다. 이 체크아웃에 없으면 공유 체크아웃의 것을 쓴다."""
    tail = Path("node_modules") / ".bin" / ("eslint.cmd" if os.name == "nt" else "eslint")
    if (npm_dir / tail).exists():
        return npm_dir / tail
    shared = _shared_npm_dir(npm_dir)
    return shared / tail if shared and (shared / tail).exists() else None


def _npm_relative(npm_dir: Path, rel_path: str) -> str:
    prefix = npm_dir.relative_to(ROOT).as_posix() + "/"
    return rel_path[len(prefix):] if rel_path.startswith(prefix) else rel_path


def ui_allow(npm_dir: Path) -> dict[str, list[str]]:
    """slug 별 면제 glob(npm 디렉토리 기준). 면제 대상은 프로파일 ALLOWLIST, 선언한 admin 레이어, 토큰 정본 파일,
    그리고 색 검사의 테스트 파일이다."""
    admin_layer = profile.layer("ui_admin")
    admin = [_npm_relative(npm_dir, admin_layer) + "**"] if admin_layer else []
    allow = profile.ALLOWLIST
    tokens = profile.layer_raw("ui_tokens")
    per_slug: dict[str, list[str]] = {          # 없는 slug 는 설정 쪽 `allow[slug] || []` 가 빈 면제로 읽는다
        "raw_fetch": [*allow["ui_fetch"], *allow["ui_fetch_wrappers"]],
        "hex_literal": [*allow["ui_hex"], *([tokens] if tokens else [])],
        "responsive": [],
        "browser_api": list(allow["ui_platform"]),
    }
    return {slug: (admin if slug in _ADMIN_SLUGS else []) + (list(_TEST_GLOBS) if slug == "hex_literal" else [])
            + [_npm_relative(npm_dir, p) for p in paths] for slug, paths in per_slug.items()}


def ui_file_globs(patterns: tuple[str, ...]) -> list[str]:
    """화면 소스 패턴(`*.tsx`)을 ESLint 설정의 files glob(`**/*.tsx`)으로. 이미 경로가 있는 패턴은 그대로 둔다."""
    return [pattern if "/" in pattern else f"**/{pattern}" for pattern in patterns]


def eslint_report(npm_dir: Path, targets: list[Path], allow: dict[str, list[str]],
                  tokens_note: str, ui_pack: Mapping[str, object]) -> dict[str, list[str]]:
    """하네스 설정으로 ESLint 를 돌려 `[slug]` 태그로 나눈다. 파서·옵션·대상 확장자는 화면팩(`ui_pack`)에서 읽는다.

    파싱에 실패한(fatal) 파일은 여섯 slug 모두에 기록한다. 그 파일은 여섯 검사 어느 것도 할 수 없기 때문이다.
    테스트와 `pack_check` 가 프로파일 없이 이 함수를 직접 부른다.
    """
    exe = ui_eslint_bin(npm_dir)
    if not exe:
        raise FileNotFoundError(f"{npm_dir}/node_modules/.bin/eslint")
    parsers = {glob: parser for pattern, parser in dict(ui_pack.get("PARSERS") or {}).items()   # type: ignore[call-overload]  # framework.load 가 매핑임을 검증했다
               for glob in ui_file_globs((pattern,))}
    # 파서는 실행 파일이 든 node_modules 에서 찾는다 — worktree 면 공유 체크아웃의 설치다. cwd 는 그대로 이 체크아웃이라
    # 대상 파일이 ESLint 기준 경로 안에 있다.
    env = {**os.environ, "HARNESS_UI_ALLOW": json.dumps(allow), "HARNESS_UI_TOKENS": tokens_note,
           "HARNESS_UI_PARSER": str(ui_pack["ESLINT_PARSER"]),
           "HARNESS_UI_PARSER_OPTIONS": json.dumps(ui_pack["PARSER_OPTIONS"]),
           "HARNESS_UI_PARSERS": json.dumps(parsers), "HARNESS_UI_MODULES": str(exe.parent.parent.parent),
           "HARNESS_UI_FILES": json.dumps(ui_file_globs(tuple(ui_pack["UI_EXT"])))}   # type: ignore[arg-type]  # framework.load 가 목록임을 검증했다
    done = subprocess.run([str(exe), "-c", str(UI_CONFIG), "--no-config-lookup", "--format", "json",
                           "--no-error-on-unmatched-pattern", *map(str, targets)],
                          cwd=npm_dir, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=TIMEOUT_SECONDS, env=env)
    found: dict[str, list[str]] = {slug: [] for slug in UI_SLUGS}
    try:
        report = json.loads(done.stdout)
    except ValueError:
        reason = (done.stderr or done.stdout).strip()[:300]
        for slug in UI_SLUGS:
            found[slug].append(f"eslint run failed — {reason}")
        return found
    if not isinstance(report, list) or any(not isinstance(entry, dict) or "filePath" not in entry
                                           for entry in report):
        return {slug: ["eslint run failed — invalid JSON report"] for slug in UI_SLUGS}
    for entry in report:
        rel = _rel(Path(entry["filePath"]))
        for message in entry.get("messages", []):
            head = f"{rel}:{message.get('line', 0)}: "
            if message.get("fatal"):
                for slug in UI_SLUGS:
                    found[slug].append(head + f"parse failed — {message.get('message', '')[:120]}")
                continue
            tag = _SLUG_TAG.match(message.get("message", ""))
            if tag and tag.group(1) in found:
                found[tag.group(1)].append(head + _SLUG_TAG.sub("", message["message"]))
    if done.returncode and not any(found.values()):
        reason = (done.stderr or done.stdout).strip()[:300]
        return {slug: [f"eslint run failed — exit code {done.returncode}: {reason}"] for slug in UI_SLUGS}
    return found


def run_ui_lint(ui_files: list[Path]) -> UiLint:
    """프로파일 설정을 읽어 eslint_report 에 넘긴다. 대상은 러너가 준 파일 그대로다. `--file` 실행이면 하나, 전체 실행이면 ui 레이어 전부다.

    화면팩이 없으면 파서를 알 수 없다 — 러너가 그 전에 [SKIP] 으로 끊지만, 여기서도 돌리지 않는다.
    대상 확장자는 프로파일 `UI_EXT` 를 쓴다. 러너가 그 패턴으로 파일을 모았으므로 설정의 files 도 같아야 한다.
    """
    if profile.UI is None:
        return UiLint({}, "no UI framework pack selected — set FRAMEWORK in the profile")
    npm_dir = ui_npm_dir()
    if not npm_dir or not npm_dir.is_dir():
        return UiLint({}, "no npm directory — set UI_NPM_DIR in the profile (default: first segment of the ui layer)")
    if not ui_eslint_bin(npm_dir):
        return UiLint({}, f"{npm_dir.relative_to(ROOT).as_posix()}/node_modules/.bin/eslint missing — "
                          f"install: {profile.UI['ESLINT_INSTALL']}")
    tokens = profile.layer_raw("ui_tokens")
    note = f"{tokens} or a CSS variable" if tokens else "the token file or a CSS variable"
    ui_pack = {**profile.UI, "UI_EXT": profile.UI_EXT}
    return UiLint(eslint_report(npm_dir, ui_files, ui_allow(npm_dir), note, ui_pack), "")
