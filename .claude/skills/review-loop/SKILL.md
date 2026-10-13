---
name: review-loop
description: 서비스 오너 검수 루프 — 화면·지표·문구를 product-reviewer 에이전트가 검수하고, 피드백을 반영해 재작업·재검수를 반복한다. "검수 돌려줘"·"리뷰해줘"·"이 화면 구성 맞는지 봐줘"·"이 지표들이 의미 있는지 확인해줘"·새 페이지/대시보드 완성 후 비즈니스 관점 검증·"재검수해줘" 요청 시 반드시 이 스킬을 사용할 것.
---

# review-loop for Claude Code

> 담는 것: 실행 환경별 연결 지침. 담지 않는 것: 공통 절차(→ `../../../dev/workflows/review-loop.md`). 읽는 시점: 이 스킬이 선택됐을 때.

Read and follow [the shared workflow](../../../dev/workflows/review-loop.md).
Follow CLAUDE.md for environment-specific routing.
Use product-reviewer for delegated business review.
Approved rework can use backend for data changes and frontend for screen changes.
