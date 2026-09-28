"""tests/fixture_go.py — 비파이썬 프로젝트 픽스처 (Go).

`SOURCE_EXT` 를 바꿨을 때 파이썬이 아닌 레포에서도 게이트가 도는지, 그리고 **파이썬 구문과
관용구에 묶인 검사가 [OK] 가 아니라 [TOOL] 로 남는지**를 정답지로 고정한다.

이 픽스처는 두 번째 확인 때문에 있다. `os.getenv` 정규식은 Go 의 `os.Getenv` 에 안 걸린다.
그걸 "위반 없음"으로 보고하면 검사기가 거짓말을 하는 것인데, 화면에는 초록불(통과)로 보인다.

여기 심은 위반은 전부 **언어 무관 검사**가 잡아야 하는 것들이다.
"""

from __future__ import annotations

ROLE = "> 담는 것: {0}. 담지 않는 것: 그 밖의 것(→ `CLAUDE.md`). 읽는 시점: {1}."

FILES: dict[str, str] = {}

FILES["CLAUDE.md"] = f"""# CLAUDE.md

{ROLE.format("Go 픽스처의 작업별 라우팅", "세션 시작")}

| 작업 | 읽을 것 |
|------|---------|
| 서버 | `DEVGUIDE.md` |
"""

FILES["DEVGUIDE.md"] = f"""# DEVGUIDE

{ROLE.format("Go 백엔드 규칙", "Go 를 만질 때")}

진입점은 `CLAUDE.md` 다.
"""

FILES["HARNESS.md"] = f"""# HARNESS

{ROLE.format("훅·에이전트·스킬 지도", "하네스를 고칠 때")}

| 종류 | 이름 |
|------|------|
| 훅 | 없음 |
"""

# 언어 무관: 읽기 레이어의 쓰기 SQL
FILES["db/reads/board.go"] = '''package reads

// 조회 전용 레이어인데 삭제 SQL 이 있다.
func PurgeCache(conn *DB) {
	conn.Exec("DELETE FROM board_cache")
}
'''

# 언어 무관: 시크릿 하드코딩
FILES["batches/leak.go"] = '''package batches

const AccessKey = "{0}"
'''.format("AKIA" + "IOSFODNN7EXAMPLE")

# 파이썬 관용구 검사가 놓치는 것 — Go 는 os.Getenv 다.
# 구문 분석 지원 여부와 별개로 선언된 패턴 검사는 이 호출을 탐지해야 한다.
FILES["utils/env.go"] = '''package utils

import "os"

var Token = os.Getenv("TOKEN")
'''

# 언어 무관: 배치 게이트 (레이어 밖 앱 코드)
FILES["stray.go"] = '''package main

func main() {}
'''

FILES["harness_profile.py"] = '''"""Go 픽스처 프로파일 — 서버 언어가 파이썬이 아닌 경우."""

STAGE = "mature"
PROFILE_SCHEMA = 1

LANG = "go"              # profiles/lang/go.py — 확장자·관용구·해당없음·린터를 다 가져온다
ARCH = "headless"        # 웹도 화면도 없다 — 화면·웹 검사 9종이 [N/A] 로 찍힌다

CHECK_PATHS = {
    "routes": None,
    "ui": None, "ui_admin": None, "ui_tokens": None,
    "tests": "tests", "schema": None,
}
FILES = {"settings": "settings.go", "ssl_util": None}
SYMBOLS = {"ssl_bypass": None, "error_response": None}
SCOPE = {"exclude_all": (), "exclude_scratch": ()}
HUBS = ("CLAUDE.md", "DEVGUIDE.md", "HARNESS.md")
VOCAB = {"ui_denylist": (), "abbrev_prefixes": (), "abbrev_names": ()}
ALLOWLIST = {"py_any": (), "ui_hex": (), "ui_fetch": (), "ui_fetch_wrappers": (),
             "env_access": (), "ui_platform": ()}
ROOT_FILES = ()
MD = {"doc_exclude": (), "ref_exclude": (), "style_exclude": (), "date_exempt": ()}
DOC_SYNC = []
BEHAVIOR_TESTED_ROOTS = ()
LESSONS_DOC = None
AGENT_MODEL_POLICY = {}
LOCAL_GATES = ()
'''

FILES[".gitignore"] = "kernel/\nharness_profile.py\n__pycache__/\n"
