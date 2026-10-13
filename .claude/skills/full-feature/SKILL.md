---
name: full-feature
description: 풀스택 기능 구현 오케스트레이터 — backend + frontend 에이전트를 병렬 실행하고 qa 에이전트로 통합 검증한다. "화면이랑 API 같이 만들어줘"·"페이지 새로 추가해줘"·"풀스택으로 구현해줘" 류의 백엔드·프론트 양쪽 파일이 모두 편집 대상인 요청, 그리고 "그 기능 다시 실행"·"이전 결과 기반으로 보완"·"프론트만 다시" 같은 후속 요청 시 반드시 이 스킬을 사용할 것.
---

# full-feature for Claude Code

> 담는 것: 실행 환경별 연결 지침. 담지 않는 것: 공통 절차(→ `../../../dev/workflows/full-feature.md`). 읽는 시점: 이 스킬이 선택됐을 때.

Read and follow [the shared workflow](../../../dev/workflows/full-feature.md).
Follow CLAUDE.md for environment-specific routing.
Run /feature-workflow for prior research and approval.
Use backend and frontend agents for independent implementation, and qa for integration review when helpful.
Agent models follow their frontmatter; this skill does not override them.
