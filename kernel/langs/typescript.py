"""kernel/langs/typescript.py — TypeScript 언어팩 (서버가 Node 인 경우). 프로젝트는 `profiles/lang/` 에서 덮어쓸 수 있다.

프론트가 TS 인 경우는 이 팩이 아니라 프로파일의 `UI_EXT` 가 담당한다. 여기는 **서버까지
TS 인 프로젝트**용이다.

타입 검사는 `tsc --noEmit` 이 하고 나머지는 `eslint` 가 한다. 하네스가 다시 구현하지 않는다.

실험적: 구문 분석기가 없다(`QUERIES`·`ANALYZER` 미선언). 초기 설정이 command 분석기(`ANALYZER = "command"`,
계약은 `kernel/analyzers/command.py` 헤더)를 만들어야 구문 사실 게이트가 돈다. 그 전에는 [TOOL] 이다.
"""

from __future__ import annotations

EXT = ("*.ts", "*.tsx", "*.mts", "*.cts")
SYNTAX = "typescript"

PATTERNS = {
    "env_read":    r"\bprocess\.env\b|\bDeno\.env\b",
    "any_type":    r":\s*any\b|\bas\s+any\b|<\s*any\b",
    "any_escape":  "any-ok",
    "closure_escape": "closure-ok",
    "comment":     "//",
    "import_stmt": r"^\s*import\b|\brequire\s*\(",
}

NOT_APPLICABLE = {
    "type_hints": "tsc already checks this, so it would duplicate",
    "py_any":     "the TS any gate already covers this",
    "undefined_const":      "Python-only check — tsc rejects undefined names",
    "type_checking_future": "Python-only check — TypeScript has no typing.TYPE_CHECKING",
}

LINTERS = [
    {"slug": "tsc", "cmd": ["npx", "--no-install", "tsc", "--noEmit", "--pretty", "false"],
     "parse": "gcc", "install": "npm i -D typescript"},
    {"slug": "eslint", "cmd": ["npx", "--no-install", "eslint", ".", "--format", "unix"],
     "parse": "gcc", "install": "npm i -D eslint"},
]
