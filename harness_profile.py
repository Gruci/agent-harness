"""harness_profile.py — 이 레포(하네스 자신)의 프로파일.

하네스가 자기 규칙을 안 지키면 그 규칙을 믿을 이유가 없다. 그래서 하네스 레포도 자기
게이트의 검사를 받는다. 다만 여기엔 **앱 코드가 없다** — 커널·프리셋·훅은 전부 하네스
자신의 파일이라 `kernel/context.app_code()` 가 코드 게이트 대상에서 뺀다.
그래서 실질적으로 도는 것은 MD 게이트와 하네스 자기서술 게이트다.

STAGE 가 greenfield 인 이유: 이 레포가 싣고 다니는 문서(`dev/DEVGUIDE.md`·`dev/`)는 **앞으로
만들 프로젝트**의 구조를 설명한다. 그 경로들은 이 레포에 실제로 없는 게 정상이다. 그래서
경로 참조 게이트를 차단으로 두면 배포용 문서를 한 줄도 못 쓴다. 차단 대신 리포트로는 계속 나온다.

새 프로젝트에 이 하네스를 깔면 이 파일은 `profiles/` 의 프리셋으로 덮어쓰인다 —
`harness_install.py` 가 한다.
"""

from __future__ import annotations

# 이 프로파일은 하네스 레포 자신의 것이지 어떤 프로젝트의 설정도 아니다. clone 해 간
# 프로젝트가 이걸 그대로 물려받으면 레이어가 전부 None 이라 게이트가 전부 꺼진 채로
# 통과 표시가 뜬다. 설치 스크립트가 이 표식을 보고 "아직 설정 안 된 상태"로 취급해 덮어쓴다.
HARNESS_SELF = True

STAGE = "greenfield"
PROFILE_SCHEMA = 1
LANG = "python"
# 하네스 본체 개발은 외부 린터 설치를 요구하지 않는다 — 파이썬 팩 기본값(ruff)을 명시적으로 끈다.
# 제품 프로젝트의 린터는 초기 설정에서 고른 언어팩이 정한다.
LINTERS: tuple = ()

# 하네스는 웹도 화면도 없는 CLI 도구다 — 화면·웹 검사 9종은 설정이 빠진 것이 아니라 해당 없음(N/A)이다.
ARCH = "headless"

# 앱 코드가 없다. tests/ 만 실물이고 나머지는 하네스 자신이다.
CHECK_PATHS: dict[str, str | None] = {"tests": "tests"}

FILES: dict[str, str | None] = {"settings": None, "ssl_util": None}
SYMBOLS: dict[str, str | None] = {"ssl_bypass": None, "error_response": None}

# 픽스처는 일부러 위반을 심어둔 가짜 프로젝트다 — 검사 대상이 아니라 검사의 재료다.
SCOPE: dict[str, tuple[str, ...]] = {
    "exclude_all":     ("tests/fixtures/",),
    "exclude_scratch": (),
}

HUBS: tuple[str, ...] = ("CLAUDE.md", "README.md", "dev/HARNESS.md", "dev/DEVGUIDE.md",
                         "design/DESIGN_GUIDE.md", "AGENTS.md")
HUB_DOMAIN_MD_IMPLICIT = True
HARNESS_MAP = "dev/HARNESS.md"

MD: dict[str, tuple[str, ...]] = {
    "doc_exclude":   (".claude/", ".agents/", ".codex/", "tests/fixtures/",
                      "docs/", "workboard/"),   # 작업 산출물 archive·과업 보드 — 정본 그래프 밖
    "ref_exclude":   (),
    # `.claude/` 는 벤더 사본(impeccable 참고 문서 30여 개)과 frontmatter 형식의 정의
    # 파일이라 역할 계약 규약의 대상이 아니다. 레포 대문(README)도 마찬가지다.
    # `workboard/` 과업 파일은 기계가 파싱하는 보드 상태라 문서 서식의 대상이 아니다.
    "style_exclude": (".claude/", ".agents/", ".codex/", "tests/fixtures/",
                      "workboard/", "docs/BACKLOG.md", "README.md", "README.en.md"),
    "date_exempt":   ("dev/LESSONS.md",),
}

VOCAB: dict[str, tuple[str, ...]] = {
    "ui_denylist": (), "abbrev_prefixes": (), "abbrev_names": (),
}

ALLOWLIST: dict[str, tuple[str, ...]] = {
    "py_any": (), "ui_hex": (), "ui_fetch": (), "ui_fetch_wrappers": (),
    "env_access": (), "ui_platform": (),
}

LEGACY_PATHS: tuple[tuple[str, "str | None"], ...] = ()
ROOT_FILES: tuple[str, ...] = ()

DOC_SYNC: list[dict[str, object]] = []
BEHAVIOR_TESTED_ROOTS: tuple[str, ...] = ()

LESSONS_DOC: str | None = "dev/LESSONS.md"

# 이 레포가 싣고 나가는 에이전트들의 모델·effort 정책표.
AGENT_MODEL_POLICY: dict[str, tuple[str, str]] = {
    "executor":         ("fable", "high"),
    "orchestrator":     ("fable", "high"),
    "backend":          ("opus", "high"),
    "frontend":         ("opus", "high"),
    "qa":               ("opus", "high"),     # API·화면 경계의 데이터 형태 대조는 기계적 분산 작업이 아니라 판단이 필요한 일이다
    "product-reviewer": ("opus", "high"),
}

# 이 레포에서만 참인 규칙. 판정은 harness_gates/<이름>.py 의 run(py, ui) 이 한다.
# edit_surface        — 면제·제외 목록이 harness_surface.txt 동결본보다 늘면 막는다.
# archive_not_shipped — 배포본(master)에 docs/tasks/archive/ 가 추적되면 막는다.
# stack_words         — 문서·에이전트(MD)에 스택 이름(react·fastapi·useApi·tanstack·colors.ts)이 돌아오면 막는다.
LOCAL_GATES: tuple[str, ...] = ("edit_surface", "archive_not_shipped", "stack_words")
