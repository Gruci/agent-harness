"""tests/fixture_files.py — 시험용 미니 프로젝트의 파일 내용 정본.

게이트마다 위반을 **정확히 1건씩** 심은 가짜 프로젝트의 파일 내용이다. 이 파일에는 데이터만 두고
디스크에 쓰는 일은 `build_fixture.py` 가 맡는다. 위반 사례가 늘어도 이 파일만 길어지도록 나눠 두었다.

새 게이트를 만들면 그 게이트가 잡을 파일을 여기에 하나 추가하고 정답지를 다시 만든다.
추가하지 않으면 골든 대조가 그 게이트를 전혀 검사하지 못한다.
"""

from __future__ import annotations

GITIGNORE = "static_check*.py\nkernel/\nharness_profile.py\n__pycache__/\n"


FILES: dict[str, str] = {}

# MD 픽스처는 fixture_md.py 가 정본이다 — 이 파일은 소스(py·ts) 픽스처만 담는다.
from fixture_md import FILES as _MD_FILES  # noqa: E402

FILES.update(_MD_FILES)

# ── 루트 파이썬 ────────────────────────────────────────────────────────────────

FILES["settings.py"] = '''"""픽스처: 환경변수 로드 정본."""
import os

ALPHA_KEY = os.getenv("ALPHA_KEY")
'''

FILES["batch_runner.py"] = '''"""픽스처: 배치 스케줄 상수."""

BATCH_HOUR = 5
'''


# ── db 레이어 ──────────────────────────────────────────────────────────────────

FILES["db/reads/bad_write.py"] = '''"""픽스처: 읽기 레이어의 쓰기 SQL."""


def wipe(conn):
    conn.execute("DELETE FROM cache")
'''

FILES["db/reads/core_import.py"] = '''"""픽스처: 커넥션 헬퍼를 core 경유로 import."""
from db.core import get_db


def rows():
    return get_db()
'''

FILES["db/conn_loop.py"] = '''"""픽스처: 커넥션 블록 안에서 중첩 루프로 집계."""


def agg():
    with get_db() as conn:
        for row in conn.execute("SELECT 1").fetchall():
            for cell in row:
                print(cell)
'''

FILES["db/schema/tables.py"] = '''"""픽스처: 저장 타입이 소스 정밀도를 못 담는 DDL."""

DDL = """
CREATE TABLE metric (
    amount REAL,
    label TEXT
)
"""
'''


# ── web 레이어 ─────────────────────────────────────────────────────────────────

FILES["web/routes/errors.py"] = '''"""픽스처: 라우트의 에러 응답 형식."""


def fail():
    return JSONResponse({"detail": "no"}, status_code=404)
'''

FILES["web/handlers.py"] = '''"""픽스처: await 없는 async 핸들러."""


async def ping():
    return {"ok": True}
'''

FILES["web/routes/orphan.py"] = '''"""픽스처: 소비 화면이 없는 라우트와 있는 라우트."""


@router.get("/api/used")
def used() -> dict:
    return {"ok": True}


@router.get("/api/nobody-consumes-this")
def orphan() -> dict:
    return {"ok": True}
'''

FILES["utils/stale_const.py"] = '''"""픽스처: 개명에서 소비처를 놓친 모듈 상수."""
PAGE_SIZE = 50


def bounded(offset: int) -> dict:
    return {"limit": DEFAULT_LIMIT, "offset": offset, "page": PAGE_SIZE}
'''

FILES["utils/money_a.py"] = '''"""픽스처: 정본 재구현 — 이름만 갈린 같은 본문(짝은 money_b)."""


def signed_won(value: int) -> str:
    sign = "+" if value > 0 else "-"
    magnitude = abs(value)
    return f"{sign}{magnitude:,}"
'''

FILES["utils/money_b.py"] = '''"""픽스처: 정본 재구현 — 이름만 갈린 같은 본문(짝은 money_a)."""


def won_signed(value: int) -> str:
    sign = "+" if value > 0 else "-"
    magnitude = abs(value)
    return f"{sign}{magnitude:,}"
'''

FILES["web/patch.py"] = '''"""픽스처: 전역 SSL 패치를 진입점 밖에서 호출."""
from utils.ssl_utils import bypass_ssl_verification

bypass_ssl_verification()
'''


# ── utils ──────────────────────────────────────────────────────────────────────

FILES["utils/env.py"] = '''"""픽스처: 설정 모듈 밖에서 환경변수 조회."""
import os

TOKEN = os.getenv("TOKEN")
'''

FILES["utils/abbrev.py"] = '''"""픽스처: 금지 축약어 2종."""

net = 0
oper_income = 1
'''

FILES["utils/anyhint.py"] = '''"""픽스처: 타입힌트 때우기."""
from typing import Any


def passthrough(value: Any) -> Any:
    return value
'''

FILES["utils/closure.py"] = '''"""픽스처: 중첩 def — 맨몸 하나와 탈출 주석 하나."""


def outer():
    def inner():
        return 1
    return inner()


def wrapped():
    def keeper():  # closure-ok: 픽스처 — 탈출 주석이 실제로 면제되는지 증명한다
        return 2
    return keeper()
'''

FILES["utils/moved.py"] = '''# utils/old_name.py
"""픽스처: 파일 이사 후 남은 헤더 경로 주석."""

VALUE = 1
'''

FILES["utils/ssl_utils.py"] = '''"""픽스처: 전역 SSL 패치 정본(호출 위치 예외)."""


def bypass_ssl_verification():
    return None
'''

FILES["utils/tc_future.py"] = '''"""픽스처: future annotations 없는 TYPE_CHECKING 블록."""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

VALUE: "Path | None" = None
'''

# 81줄 함수. 파일 400줄 상한으로는 잡히지 않는 경우다. 줄마다 내용을 다르게 만들어 블록 중복 검사에 걸리지 않게 한다.
FILES["utils/long_func.py"] = (
    '"""픽스처: 함수 길이 상한 초과."""\n\n\ndef long_calc() -> int:\n'
    + "".join(f"    value_{i} = {i}\n" for i in range(80))
    + "    return value_0\n"
)

FILES["db/reads/col_interp.py"] = '''"""픽스처: 읽기 레이어의 컬럼 식별자 raw 보간."""


def series(conn: object, column: str) -> list:
    sql = f'SELECT "{column}" FROM metric'
    return conn.execute(sql).fetchall()
'''

FILES["db/writes/loader.py"] = '''"""픽스처: 적재 직전 반올림 절삭."""


def store(conn: object, value: float) -> None:
    conn.execute("INSERT INTO metric VALUES (?)", (round(value, 2),))
'''

FILES["batches/report.py"] = '''"""픽스처: 배치 안 직접 SELECT."""


def rows(conn: object) -> list:
    return conn.execute("SELECT value FROM metric").fetchall()
'''

# 루트 잡파일: 어느 패키지에도 속하지 않는 메모 덤프다. 잡파일 게이트만 이 파일을 잡는다. .py 가 아니라서 배치 게이트 대상이 아니다.
FILES["notes_dump.txt"] = "임시 조사 메모 덤프\n"


# ── 도메인 · 프론트 · 테스트 ───────────────────────────────────────────────────

FILES["kofia/collect.py"] = '''"""픽스처: 대응 행동 테스트가 없는 수집 모듈."""


def collect():
    return []
'''

FILES["frontend/src/Label.tsx"] = '''export const title = "순신고가";
'''

FILES["frontend/src/Consumer.tsx"] = '''import { useApi } from "./useApi";

export const Panel = () => useApi("/api/used");
'''

FILES["frontend/src/anyts.ts"] = '''export const value: any = 1;
'''

FILES["frontend/src/RawFetch.tsx"] = '''export async function load() {
  return fetch("/api/board");
}
'''

FILES["frontend/src/Hex.tsx"] = '''export const accent = "#ff0000";
'''

FILES["frontend/src/types/api.ts"] = '''export interface Board {
  items: string[];
}
'''

FILES["frontend/src/Fixed.tsx"] = '''export const panel = { width: "480px" };
'''

FILES["frontend/src/Storage.tsx"] = '''export const saved = localStorage.getItem("draft");
'''

# 브라우저 API 래퍼의 정본. 프로파일 ui_platform 에 등록돼 있어 이 파일 자체는 검사 대상이 아니다.
FILES["frontend/src/platform.ts"] = '''export const read = (key: string) => window.localStorage.getItem(key);
'''

# ── 프론트 신설 게이트 픽스처 ──────────────────────────────────────────────────
#
# 테스트 짝 게이트가 잡도록 일부러 심은 위반은 Label.tsx(컴포넌트)와 calcShare.ts(로직) 둘뿐이다.
# 나머지 화면 픽스처에는 같은 이름의 .test 스텁(내용 없는 테스트 파일)을 두어 "게이트마다 위반 1건" 원칙을 지킨다.

FILES["frontend/src/calcShare.ts"] = '''export function share(part: number, total: number): number {
  return total === 0 ? 0 : part / total;
}
'''

FILES["frontend/src/HashNav.tsx"] = '''export const go = (theme: string) => {
  history.pushState(null, "", "#" + theme);
};
'''

for _stub in ("Consumer", "RawFetch", "Hex", "Fixed", "Storage", "HashNav"):
    FILES[f"frontend/src/{_stub}.test.tsx"] = "export {};\n"
FILES["frontend/src/platform.test.ts"] = "export {};\n"

# 시크릿 — AWS 공개 문서의 예시 키 형태. 이 빌더 자신이 게이트에 걸리지 않도록
# 리터럴을 쪼개 조립한다. 생성된 픽스처 파일에는 온전한 형태로 들어간다.
FILES["batches/leak.py"] = '''"""픽스처: 실키 형태의 토큰 하드코딩."""

ACCESS_KEY = "{0}"
'''.format("AKIA" + "IOSFODNN7EXAMPLE")

FILES["tests/unit/test_placeholder.py"] = '''"""픽스처: 짝 검사가 매칭에 실패하는지 확인용 테스트."""


def test_placeholder():
    assert True
'''

# 배열 옵셔널 게이트는 baseline 파일이 없으면 통째로 꺼진다 — 빈 파일로 켜둔다.
FILES["api_array_baseline.txt"] = "# 픽스처: 동결분 없음\n"

# 커널이 프로젝트에 대해 아는 정보는 이 프로파일이 전부다. 픽스처는 모든 게이트가 켜지도록 항목을 다 채운다.
FILES["harness_profile.py"] = '''"""픽스처 프로젝트 프로파일 — 게이트 전량을 켠다."""

STAGE = "mature"
PROFILE_SCHEMA = 1
LANG = "python"
LINTERS = ()  # External process contracts are tested separately from deterministic golden output.

ARCH = "web_layered"      # 화면+서버 풀스택 — 아무것도 N/A 로 돌리지 않는다
FRAMEWORK = ("fastapi", "react")   # 서버·화면 프레임워크팩 — 웹·화면 게이트가 이 선언을 읽는다

CHECK_PATHS = {
    "routes": "web/routes",
    "ui": "frontend/src", "ui_admin": "frontend/src/admin", "ui_tokens": None,
    "tests": "tests", "schema": "db/schema",
}
FILES = {"settings": "settings.py", "ssl_util": "utils/ssl_utils.py"}
SYMBOLS = {"ssl_bypass": "bypass_ssl_verification", "error_response": "JSONResponse"}
SCOPE = {"exclude_all": (), "exclude_scratch": ("scripts/", "docs/")}
HUBS = ("CLAUDE.md", "AGENTS.md", "DEVGUIDE.md", "DESIGN_GUIDE.md", "README.md", "HARNESS.md")
VOCAB = {
    "ui_denylist": ("순신고가",),
    "abbrev_prefixes": ("oper_", "rev_"),
    "abbrev_names": ("net",),
}
ALLOWLIST = {"py_any": (), "ui_hex": (), "ui_fetch": (), "ui_fetch_wrappers": (),
             "env_access": (), "ui_platform": ("frontend/src/platform.ts",)}
# 루트 잡파일 게이트가 확장자 불문 루트 전부를 대조한다 — 정본 MD 도 등재. notes_dump.txt 가 위반 1건.
ROOT_FILES = ("settings.py", "batch_runner.py", "CLAUDE.md", "README.md", "AGENTS.md",
              "DESIGN_GUIDE.md", "DEVGUIDE.md", "HARNESS.md")
LESSONS_DOC = "dev/LESSONS.md"
AGENT_MODEL_POLICY = {"auditor": ("opus", "high")}
MD = {
    "doc_exclude": (".claude/", "docs/"),
    "ref_exclude": ("docs/", "idea/", "memory/"),
    "style_exclude": (),
    "date_exempt": ("dev/LESSONS.md",),
}
DOC_SYNC = [
    {"doc": "DEVGUIDE.md", "code": "batch_runner.py", "kind": "int_consts", "marker": "_HOUR"},
    {"doc": "DEVGUIDE.md", "code": "settings.py", "kind": "env_keys",
     "section": "## .env 키 목록", "allow": ()},
]
BEHAVIOR_TESTED_ROOTS = ("kofia/",)
LOCAL_GATES = ()
'''

# 검사 48(아키텍처 그림 1:1 대조)용. 그림과 실제 코드가 1:1로 맞는지 보는 검사에 위반을 하나씩 심는다.
# 심은 위반: 없는 revision, 없는 파일, 행 범위 밖 참조, sources 없는 노드, 그리지 않은 레이어(utils/), 영수증 없음.
# external 노드는 검사 면제라 통과해야 한다.
FILES["docs/architecture/app.architecture.json"] = '''{
  "schema_version": 1,
  "diagram_type": "architecture",
  "meta": {
    "title": "픽스처 앱",
    "quality_profile": "showcase",
    "repository": { "url": "https://github.com/example/miniproj", "revision": "0000000000000000000000000000000000000000" }
  },
  "components": [
    { "id": "user", "type": "external", "label": "사용자", "pos": [40, 200], "size": [150, 64] },
    { "id": "ui", "type": "frontend", "label": "화면", "sublabel": "frontend/src/", "pos": [300, 200], "size": [170, 64],
      "sources": [ { "path": "frontend/src/Consumer.tsx", "label": "소비 화면" } ] },
    { "id": "routes", "type": "backend", "label": "라우트", "sublabel": "web/routes/", "pos": [560, 200], "size": [170, 64],
      "sources": [ { "path": "web/routes/errors.py", "line": 1 } ] },
    { "id": "reads", "type": "database", "label": "조회", "sublabel": "db/reads/", "pos": [820, 200], "size": [170, 64],
      "sources": [ { "path": "db/reads/bad_write.py", "line": 1, "end_line": 99 }, { "path": "db/writes/loader.py" }, { "path": "db/schema/tables.py" } ] },
    { "id": "batch", "type": "backend", "label": "배치", "sublabel": "batches/", "pos": [560, 380], "size": [170, 64],
      "sources": [ { "path": "batches/report.py" }, { "path": "kofia/collect.py", "label": "수집" }, { "path": "tests/unit/test_placeholder.py", "label": "샘플" } ] },
    { "id": "gone", "type": "backend", "label": "옮긴 모듈", "pos": [820, 380], "size": [170, 64],
      "sources": [ { "path": "utils/gone.py" } ] },
    { "id": "orphan", "type": "backend", "label": "출처 없는 상자", "pos": [300, 380], "size": [170, 64] }
  ],
  "boundaries": [],
  "connections": [
    { "id": "user-ui", "from": "user", "to": "ui" },
    { "id": "ui-routes", "from": "ui", "to": "routes", "label": "fetch" },
    { "id": "routes-reads", "from": "routes", "to": "reads" },
    { "id": "batch-reads", "from": "batch", "to": "reads", "fromSide": "right", "toSide": "bottom" }
  ]
}
'''

FILES[".gitignore"] = GITIGNORE

