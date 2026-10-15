"""kernel/analyzers/modules.py — 파일 경로와 import 문자열을 레포 모듈 키로 바꾸는 규칙 셋.

tree-sitter 엔진과 정규식 엔진이 같이 쓴다. 팩은 MODULE_RULE 로 이 중 하나를 고른다(`kernel/lang.py` MODULE_RULES).

  go_package  디렉토리가 패키지다. 파일에서 위로 가장 가까운 go.mod 의 module 접두가 붙은 import 만 레포 내부다
              — `backend/go.mod` 도 된다. 루트 go.mod 옆의 파일은 module 경로 끝 이름이 키다
  relative    `./`·`../` 만 레포 내부다(TS·JS). 확장자와 끝의 `index` 를 뗀 경로가 키다 — `./db` 와 `./db/index.ts` 가
              같은 키라 디스크를 뒤지지 않아도 맞는다. 그 밖은 외부이고 이름은 `@scope/pkg` 또는 첫 마디다
  dotted      `.`·`::` 로 이은 이름(Java·Kotlin·C#·Rust)을 레포 모듈 키의 접미로 찾는다. 없으면 끝 마디를 두 번까지
              떼어 다시 찾는다(정적 import·멤버). 앞마디 crate·self·super 는 뗀다. 못 찾으면 외부다
  (없음)      경로가 곧 키이고 import 는 전부 외부다

`resolve` 는 (레포 안 모듈 키, 외부 이름) 을 돌려준다. None 이면 모듈 의존이 아니다(스타일·JSON 같은 자산 import).
"""

from __future__ import annotations

import os
import posixpath
import re
import subprocess
from pathlib import Path

_GO_MODULE = re.compile(r"^\s*module\s+(\S+)", re.M)
_SCRIPT_SUFFIXES = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")
_DOTTED_ROOTS = ("crate", "self", "super")


def is_public(rule: object, name: str) -> bool:
    """PUBLIC_RULE — capitalized 는 대문자 시작이 공개, underscore 는 `_` 접두가 비공개. 규칙이 없으면 전부 공개다."""
    if rule == "capitalized":
        return name[:1].isupper()
    if rule == "underscore":
        return not name.startswith("_")
    return True


def _dotted(path: str) -> str:
    return path.replace("/", ".")


def _go_module_path(go_mod: Path) -> str | None:
    """go.mod 의 module 선언. 없으면 그 아래 import 를 레포 내부로 가를 수 없다."""
    try:
        match = _GO_MODULE.search(go_mod.read_text(encoding="utf-8-sig"))
    except OSError:
        return None
    return match.group(1).strip('"') if match else None


def _repo_files(root: Path, suffixes: tuple[str, ...]) -> list[str]:
    """레포 안 소스 상대경로. git 이면 추적·미추적(무시 제외) 목록이고, git 밖(pack_check 임시 폴더)이면 폴더를 훑는다."""
    try:
        done = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                              cwd=root, capture_output=True, timeout=30)
        names = [name for name in done.stdout.decode("utf-8", "replace").split("\0") if name] if not done.returncode else []
    except (OSError, subprocess.TimeoutExpired):
        names = []
    if not names:
        for folder, dirs, files in os.walk(root):
            dirs[:] = [name for name in dirs if not name.startswith(".") and name != "node_modules"]
            base = Path(folder).relative_to(root).as_posix()
            names += [name if base == "." else f"{base}/{name}" for name in files]
    return [name for name in names if name.endswith(suffixes)]


def _shared(key: str, here: str) -> int:
    """두 키가 앞에서부터 같은 마디 수 — 같은 이름이 여럿이면 import 하는 파일과 가까운 쪽을 고른다."""
    count = 0
    for left, right in zip(key.split("."), here.split(".")):
        if left != right:
            break
        count += 1
    return count


class ModuleRules:
    def __init__(self, rule: object, root: Path, suffixes: tuple[str, ...]) -> None:
        self.rule = rule
        self._root = root
        self._suffixes = suffixes
        self._go_mods: dict[str, tuple[str, str] | None] = {}    # 디렉토리 → (module 경로, go.mod 디렉토리)
        self._index: dict[str, list[str]] | None = None          # dotted 접미 → 모듈 키. 처음 쓸 때 한 번 만든다
        root_module = _go_module_path(root / "go.mod") if rule == "go_package" else None
        self._root_key = root_module.rsplit("/", 1)[-1] if root_module else "main"

    def module_key(self, rel: str) -> str:
        if self.rule == "go_package":
            directory = posixpath.dirname(rel)
            return _dotted(directory) if directory else self._root_key
        return self._stem_key(rel.rsplit(".", 1)[0])

    def _stem_key(self, stem: str) -> str:
        if self.rule == "relative" and stem.endswith("/index"):
            stem = stem[:-len("/index")]                    # Python 의 __init__ 처럼 폴더가 곧 모듈이다
        return _dotted(stem)

    def resolve(self, raw: str, rel: str) -> tuple[str | None, str | None] | None:
        if self.rule == "go_package":
            return self._go(raw, rel)
        if self.rule == "relative":
            return self._relative(raw, rel)
        if self.rule == "dotted":
            return self._dotted_name(raw, rel)
        return None, raw

    def _nearest_go_mod(self, directory: str) -> tuple[str, str] | None:
        if directory not in self._go_mods:
            module = _go_module_path(self._root / directory / "go.mod")
            self._go_mods[directory] = ((module, directory) if module
                                        else self._nearest_go_mod(posixpath.dirname(directory)) if directory else None)
        return self._go_mods[directory]

    def _go(self, raw: str, rel: str) -> tuple[str | None, str | None]:
        found = self._nearest_go_mod(posixpath.dirname(rel))
        if found:
            module, directory = found
            if raw == module or raw.startswith(module + "/"):
                target = "/".join(part for part in (directory, raw[len(module):].strip("/")) if part)
                return (_dotted(target) if target else self._root_key), None
        return None, raw

    def _relative(self, raw: str, rel: str) -> tuple[str | None, str | None] | None:
        if not raw.startswith(("./", "../")) and raw not in (".", ".."):
            parts = raw.split("/")
            return None, "/".join(parts[:2]) if raw.startswith("@") else parts[0]
        target = posixpath.normpath(posixpath.join(posixpath.dirname(rel), raw))
        if target.startswith(".."):
            return None, raw                                  # 레포 밖
        suffix = posixpath.splitext(target)[1]
        if suffix in _SCRIPT_SUFFIXES + self._suffixes:
            target = target[:-len(suffix)]
        elif suffix and (self._root / target).is_file():
            return None                                       # `./styles.css` 같은 자산 — `./orders.service` 는 모듈이다
        return self._stem_key(target), None

    def _suffix_index(self) -> dict[str, list[str]]:
        """모듈 키와 그 폴더 키의 모든 접미 → 키. 폴더도 넣는 것은 `com.x.orders.*` 같은 패키지 import 때문이다."""
        if self._index is None:
            keys = {self.module_key(rel) for rel in _repo_files(self._root, self._suffixes)}
            folders = {key.rsplit(".", depth)[0] for key in keys for depth in range(1, key.count(".") + 1)}
            self._index = {}
            for key in sorted(keys) + sorted(folders - keys):
                parts = key.split(".")
                for start in range(len(parts)):
                    self._index.setdefault(".".join(parts[start:]), []).append(key)
        return self._index

    def _dotted_name(self, raw: str, rel: str) -> tuple[str | None, str | None] | None:
        parts = [part for part in re.split(r"\.|::", raw) if part and part != "*"]
        anchored = bool(parts) and parts[0] in _DOTTED_ROOTS
        while parts and parts[0] in _DOTTED_ROOTS:
            parts.pop(0)
        if not parts:
            return None
        here = self.module_key(rel)
        # 한 마디짜리 이름은 crate·self·super 로 레포 안임이 확정된 경우만 찾는다 — 흔한 이름이 엉뚱한 파일에 붙는다
        for size in range(len(parts), max(len(parts) - 3, 0 if anchored else 1), -1):
            keys = self._suffix_index().get(".".join(parts[:size]))
            if keys:
                return max(keys, key=lambda key: _shared(key, here)), None
        return None, parts[0] if "::" in raw else ".".join(parts[:2])
