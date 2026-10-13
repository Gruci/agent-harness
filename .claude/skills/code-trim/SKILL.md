---
name: code-trim
description: >
  Code review focused exclusively on over-engineering. Finds what to delete:
  reinvented standard library, unneeded dependencies, speculative abstractions,
  dead flexibility. One line per finding: location, what to cut, what replaces
  it. Use when the user says "review for over-engineering", "what can we
  delete", "is this over-engineered", "simplify review", or invokes
  /code-trim. Complements correctness-focused review, this one only
  hunts complexity.
---

# code-trim for Claude Code

> 담는 것: 실행 환경별 연결 지침. 담지 않는 것: 공통 절차(→ `../../../dev/workflows/code-trim.md`). 읽는 시점: 이 스킬이 선택됐을 때.

Read and follow [the shared workflow](../../../dev/workflows/code-trim.md).
Follow CLAUDE.md for environment-specific routing.
