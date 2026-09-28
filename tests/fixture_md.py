"""tests/fixture_md.py — 미니 프로젝트의 MD·하네스 설정 픽스처.

MD 계열 게이트가 잡을 문서와 `.claude/` 설정을 여기 둔다. 대상 게이트는 작성 규칙, 경로 참조,
고아 문서, 지도 대조, 모델 정책, 승격 상태다. 소스 픽스처와 나눈 이유는 성격이 달라서다.
이쪽 문서들은 서로 링크로 이어진 문서 그래프를 이루고, 소스 픽스처는 파일 하나가 위반 하나다.

**본문을 들여쓰지 않는다.** 삼중따옴표 안이 곧 파일 내용이라, 함수로 감싸 들여쓰면 그 공백이
frontmatter 와 제목 앞에 붙어 게이트가 통째로 못 읽는다.
"""

from __future__ import annotations

ROLE = "> 담는 것: {0}. 담지 않는 것: 그 밖의 것(→ `CLAUDE.md`). 읽는 시점: {1}."

FILES: dict[str, str] = {}

# ── MD ─────────────────────────────────────────────────────────────────────────

FILES["CLAUDE.md"] = f"""# CLAUDE.md

{ROLE.format("픽스처 프로젝트의 작업별 라우팅", "세션 시작")}

| 작업 | 읽을 것 |
|------|---------|
| 백엔드 | `DEVGUIDE.md` |
| 디자인 | `DESIGN_GUIDE.md` |
| 하네스 | `HARNESS.md` |
| 코덱스 | `AGENTS.md` |
| 사고 기록 | `dev/LESSONS.md` |
"""

# 승격 상태 검사용: 아래 LESSONS 의 §1 절은 `> 강제:` 선언을 일부러 빠뜨린다
FILES["dev/LESSONS.md"] = f"""# LESSONS

{ROLE.format("사고 경위와 강제 수단", "같은 사고를 또 낼 것 같을 때")}

## §1 읽기 레이어에서 쓰기가 나갔다

캐시를 지우는 SQL 이 조회 경로에 섞여 들어갔다.

## §2 색을 파일마다 직접 적었다

> 강제: 산문 전용 — 토큰 정본이 아직 없어 가리킬 곳이 없다

같은 파랑이 화면마다 달랐다.
"""

# ⑬b 한 줄에 설명 붙은 나열 7개 · ⑬c 괄호 3중 중첩
FILES["README.md"] = f"""# README

{ROLE.format("픽스처가 무엇인지", "픽스처를 고칠 때")}

진입점은 `CLAUDE.md` 다.

수집 단계는 외부 원본을 그대로 받아오고 · 정규화 단계는 결측치를 기본값으로 메우고 · 집계 단계는 월별 기준으로 묶어내고 · 검증 단계는 합계를 원본과 대조하고 · 적재 단계는 트랜잭션으로 밀어넣고 · 알림 단계는 실패 건만 따로 보고하고 · 정리 단계는 임시파일을 전부 지운다

호출 순서는 (수집 (정규화 (집계))) 순이다.
"""

# ④A 실존하지 않는 경로 참조
FILES["AGENTS.md"] = f"""# AGENTS.md

{ROLE.format("코덱스 진입점", "코덱스로 작업할 때")}

읽기 레이어의 정본은 `db/reads/gone.py` 다.
"""

# ⑬a 코드펜스 트리 덤프
FILES["DESIGN_GUIDE.md"] = f"""# DESIGN_GUIDE

{ROLE.format("디자인 허브", "UI 를 만질 때")}

```
frontend/
├── src/
│   ├── Label.tsx
│   ├── RawFetch.tsx
│   └── types/
└── package.json
```
"""

# ④B 배치표 시각 불일치 · ④C .env 키 양방향 불일치 · ⑬e 날짜 태그 6개
FILES["DEVGUIDE.md"] = f"""# DEVGUIDE

{ROLE.format("백엔드 허브", "파이썬을 만질 때")}

## 배치 스케줄

| 배치 | 시각 |
|------|------|
| 일별 (BATCH_HOUR) | 03:00 |

정본 상수는 `batch_runner.py` 에 있다.

## 변경 이력

2026-01-02 · 2026-02-03 · 2026-03-04 · 2026-04-05 · 2026-05-06 · 2026-06-07

## .env 키 목록

- BETA_KEY — 픽스처용 키
"""

# ④E 지도 누락 — 스킬 'runbook' 을 일부러 안 적는다
FILES["HARNESS.md"] = f"""# HARNESS

{ROLE.format("훅·에이전트·스킬 지도", "하네스를 고칠 때")}

| 종류 | 이름 |
|------|------|
| 훅 | probe_hook.py |
| 에이전트 | auditor |

이름을 백틱 없이 적는다 — 지도 대조(④E)는 문자열 등장만 보고, 백틱을 두르면 경로 실존(④A)이
아직 만들지 않은 훅 파일을 잡는다.
"""

# ④D 고아 MD(허브에서 도달 불가) · ⑬d 머리 역할 계약 누락
FILES["notes/GUIDE.md"] = """# GUIDE

어디에서도 링크되지 않는 문서다.
"""

FILES[".claude/agents/auditor.md"] = f"""---
name: auditor
description: 픽스처용 에이전트.
model: sonnet
effort: medium
---

# auditor

{ROLE.format("픽스처 에이전트 정의", "위임받을 때")}
"""

FILES[".claude/skills/runbook/SKILL.md"] = f"""---
name: runbook
description: 픽스처용 스킬.
---

# runbook

{ROLE.format("픽스처 스킬 절차", "호출될 때")}
"""

FILES[".claude/settings.json"] = """{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": "python .claude/hooks/probe_hook.py" }
        ]
      }
    ]
  }
}
"""
