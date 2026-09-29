"""profiles/_template.py — 언어 선택 전 새 프로젝트의 프로파일 시작점.

기술을 먼저 정하지 않는다. 사용자가 스택과 업무 분류를 정하면 그래프와 검사 도구를 연결한다.
첫 제품 코드는 승인된 컴포넌트에 속해야 한다. 기술 검사 경로는 업무 분류를 대신하지 않는다.
"""

from __future__ import annotations

PRESET_SUMMARY = "스택 미정 — 사용자와 업무 분류 및 언어를 정한 뒤 조립한다"
PRESET_FITS = "새 프로젝트. 첫 코드 전에 그래프와 검사 도구 연결을 완료한다"
PROFILE_SCHEMA = 1
STAGE = "greenfield"

# 실행 언어가 아니라 개발할 제품의 언어다. 하네스가 Python이어도 제품 언어를 추정하지 않는다.
LANG: str | None = None
ARCH: str | None = None
# 서버·화면 프레임워크팩. 역할별로 최대 하나씩(예: ("fastapi", "react")). 비우면 웹·화면 게이트가 [SKIP] 이다.
FRAMEWORK: tuple[str, ...] = ()
COMPONENT_GRAPH = "docs/architecture/components.json"

# LANG 선택 후 언어팩 값을 사용한다. 필요할 때 SOURCE_EXT, SYNTAX, LINTERS를 명시한다.
# 화면 언어 및 npm 도구도 프로젝트 선택에 따라 구성한다.
UI_EXT: tuple[str, ...] = ()
UI_NPM_DIR: str | None = None

# 기술 검사 대상일 뿐 아키텍처 분류가 아니다. 업무 컴포넌트/역할은 COMPONENT_GRAPH 정본에 둔다.
CHECK_PATHS: dict[str, str | None] = {
    "ui": None,
    "ui_admin": None,
    "ui_tokens": None,
    "tests": None,
    "routes": None,
    "schema": None,
}
FILES: dict[str, str | None] = {"settings": None, "ssl_util": None}
SYMBOLS: dict[str, str | None] = {
    "ssl_bypass": None,
    "error_response": None,
}
SCOPE: dict[str, tuple[str, ...]] = {"exclude_all": (), "exclude_scratch": ()}

HUBS: tuple[str, ...] = ()
HUB_DOMAIN_MD_IMPLICIT = True
HARNESS_MAP = "dev/HARNESS.md"
MD: dict[str, tuple[str, ...]] = {
    "doc_exclude": (), "ref_exclude": (),
    # 하네스가 함께 싣는 벤더 문서(`.claude/`·`.agents/`)와 정의 파일, 레포 대문(README), 테스트 픽스처, 과업 보드는
    # 역할 계약 규약의 대상이 아니다. 하네스 자신의 프로파일도 같은 사유로 뺀다.
    "style_exclude": (".claude/", ".agents/", ".codex/", "tests/fixtures/", "workboard/",
                      "README.md", "README.en.md"),
    "date_exempt": (),
}
VOCAB: dict[str, tuple[str, ...]] = {
    "ui_denylist": (), "abbrev_prefixes": (), "abbrev_names": (),
}
ALLOWLIST: dict[str, tuple[str, ...]] = {
    "py_any": (), "ui_hex": (), "ui_fetch": (), "ui_fetch_wrappers": (),
    "env_access": (), "ui_platform": (),
}
LEGACY_PATHS: tuple[tuple[str, str | None], ...] = ()
ROOT_FILES: tuple[str, ...] = ()
DOC_SYNC: list[dict[str, object]] = []
BEHAVIOR_TESTED_ROOTS: tuple[str, ...] = ()
VERSIONED_PROMPTS: tuple[str, ...] = ()
UI_COPY: dict[str, object] = {}
LESSONS_DOC: str | None = None
AGENT_MODEL_POLICY: dict[str, tuple[str, str]] = {}
LOCAL_GATES: tuple[str, ...] = ()
