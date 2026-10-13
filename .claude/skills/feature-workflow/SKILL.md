---
name: feature-workflow
description: 기능 추가·수정·버그수정 4단계 워크플로우 — 범위 인터뷰 → 리서치 → 계획 → 구현 → 수정/롤백. "기능 만들어줘"·"수정해줘"·"버그 고쳐줘"·"리서치부터 해줘"·"다시 구현해줘"·"이전 plan 기반으로 보완해줘" 등 모든 코드 변경 요청 시 반드시 이 스킬을 사용할 것 (단순 오탈자·설정값 1줄 제외). AI가 독단적으로 코드를 작성하는 것을 방지하고, 설계를 plan.md로 남겨 사용자 승인 후 구현한다.
---

# feature-workflow for Claude Code

> 담는 것: 실행 환경별 연결 지침. 담지 않는 것: 공통 절차(→ `../../../dev/workflows/feature-workflow.md`). 읽는 시점: 이 스킬이 선택됐을 때.

Read and follow [the shared workflow](../../../dev/workflows/feature-workflow.md).
Follow CLAUDE.md for environment-specific routing.
Research and planning stay in the main loop.
Implementation agents follow model routing in CLAUDE.md; do not override their frontmatter model.
Use orchestrator for independent tracks or executor for an implementation handoff when helpful.
