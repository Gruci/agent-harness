"""profiles/_template.py — 언어 선택 전 새 프로젝트의 프로파일 시작점.

기술을 먼저 정하지 않는다. 사용자가 스택과 업무 분류를 정하면 그래프와 검사 도구를 연결한다.
첫 제품 코드는 승인된 컴포넌트에 속해야 한다. 기술 검사 경로는 업무 분류를 대신하지 않는다.

자가 발전 장치(허브·사고 기록·에이전트 정책표·편집 표면 래칫)는 하네스 레포와 같은 값으로 켜 둔다. 설치가 이 선언으로
동결본(`harness_surface.txt`)을 다시 뜨고 정비 기록을 비운다. 대상 문서가 아직 없는 설치(플러그인)에서는 그 게이트가 사유와 함께 [SKIP] 이다.
"""

from __future__ import annotations

PRESET_SUMMARY = "Stack not chosen — assemble after deciding the classification and language with the user"
PRESET_FITS = "New project. Finish the graph and check tool wiring before the first code"
PROFILE_SCHEMA = 1
# greenfield 는 첫 컴포넌트가 승인되면 저절로 끝난다 — 경로·함수 참조 검사(26·33)가 그때부터 켜진다(kernel/runner.py).
STAGE = "greenfield"

# 실행 언어가 아니라 개발할 제품의 언어다. 하네스가 Python이어도 제품 언어를 추정하지 않는다.
LANG: str | None = None
ARCH: str | None = None
# 서버·화면 프레임워크팩. 역할별로 최대 하나씩(예: ("fastapi", "react")). 비우면 웹·화면 게이트가 [SKIP] 이다.
FRAMEWORK: tuple[str, ...] = ()
COMPONENT_GRAPH = "docs/architecture/components.json"
# 끝난 과업을 본체에 합치는 방식. "direct" 는 ff 로 바로 합치고 "pr" 은 PR 을 거친다(kernel/task_finish.py).
MERGE_FLOW = "direct"
# Optional shared task coordinator; credentials are read from the named local environment variable.
# Enabling TEAM requires MERGE_FLOW = "pr" and protected server-side admission (dev/TEAM.md).
TEAM: dict[str, str] = {}

# 완료 계약(kernel/required.py). 첫 컴포넌트가 생긴 뒤 --verify 에서 여기 적은 검사 slug 가 [SKIP]·[N/A]·결과 없음이면 실패다.
# 예약 slug "tests" 는 TESTS 선언을 요구한다. 지우는 것은 완화라 harness_surface.txt 의 동결 행과 대조된다. 비면 지금과 같다.
REQUIRED_CHECKS: tuple[str, ...] = ()
# 제품 테스트. finish 와 CI 가 kernel/tests_run.py 로 돌린다 — --verify(120초 상한)와 매 턴 Stop 에는 들어가지 않는다.
# cmd 에는 JUnit XML 보고서 자리 "{report}" 가 정확히 하나 있어야 한다. 실행 0건·보고서 없음은 실패다.
# 예: TESTS = ({"slug": "pytest", "cmd": ("python", "-m", "pytest", "-q", "--junitxml={report}"), "timeout": 600},)
TESTS: tuple[dict, ...] = ()
# 생략한 선택 설정은 kernel/profile.py 와 선택한 팩의 기본값을 쓴다. 다른 값이 필요할 때만 선언한다.

# 기술 검사 대상일 뿐 아키텍처 분류가 아니다. 업무 컴포넌트/역할은 COMPONENT_GRAPH 정본에 둔다.
CHECK_PATHS: dict[str, str | None] = {
    "ui": None,
    "ui_admin": None,
    "ui_tokens": None,
    "tests": None,
    "routes": None,
    "schema": None,
}

# 하네스가 함께 싣는 진입 문서. 여기서 링크로 닿지 않는 정본 MD 는 고아다(검사 27).
HUBS: tuple[str, ...] = ("CLAUDE.md", "README.md", "AGENTS.md", "dev/HARNESS.md", "dev/DEVGUIDE.md",
                         "design/DESIGN_GUIDE.md")
HUB_DOMAIN_MD_IMPLICIT = True
HARNESS_MAP = "dev/HARNESS.md"
MD: dict[str, tuple[str, ...]] = {
    # 정본 그래프 밖 — 벤더 사본과 정의 파일, 생성 지도, 보관 전 작업 산출물·시안, 과업 보드.
    "doc_exclude": (".claude/", ".agents/", ".codex/", "docs/architecture/", "docs/tasks/", "docs/mockup/",
                    "workboard/"),
    "ref_exclude": (),
    # 벤더 문서와 정의 파일, 레포 대문, 테스트 픽스처, 과업 보드, 작업 산출물·시안은 역할 계약 규약의 대상이 아니다.
    "style_exclude": (".claude/", ".agents/", ".codex/", "tests/fixtures/", "workboard/", "docs/tasks/",
                      "docs/mockup/", "README.md", "README.ko.md"),
    "date_exempt": ("dev/LESSONS.md",),
}
# 루트에 둘 수 있는 파일(검사 45). 하네스 문서만 미리 적는다. 스택 매니페스트는 스택 맞춤에서 사유와 함께 더한다.
ROOT_FILES: tuple[str, ...] = ("AGENTS.md", "CLAUDE.md", "PROJECT.md", "README.md", "README.ko.md")
LESSONS_DOC: str | None = "dev/LESSONS.md"
# .claude/agents/ 각 파일의 frontmatter 와 대조한다(검사 29). 라우팅을 바꾸면 양쪽을 같은 커밋에서 고친다.
AGENT_MODEL_POLICY: dict[str, tuple[str, str]] = {
    "executor": ("fable", "high"), "orchestrator": ("fable", "high"), "backend": ("opus", "high"),
    "frontend": ("opus", "high"), "qa": ("opus", "high"), "product-reviewer": ("opus", "high"),
}
# 면제·제외 목록은 줄어들기만 한다(harness_gates/edit_surface.py). 동결본은 설치가 이 선언으로 다시 뜬다.
LOCAL_GATES: tuple[str, ...] = ("edit_surface",)
