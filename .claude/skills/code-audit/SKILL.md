---
name: code-audit
description: >
  Whole-repo audit for over-engineering. Like code-trim, but scans the
  entire codebase instead of a diff: a ranked list of what to delete, simplify,
  or replace with stdlib/native equivalents. Use when the user says "audit this
  codebase", "audit for over-engineering", "what can I delete from this repo",
  "find bloat", "code-audit", or "/code-audit". One-shot report, does
  not apply fixes.
---

# code-audit for Claude Code

> 담는 것: 실행 환경별 연결 지침. 담지 않는 것: 공통 절차(→ `../../../dev/workflows/code-audit.md`). 읽는 시점: 이 스킬이 선택됐을 때.

Read and follow [the shared workflow](../../../dev/workflows/code-audit.md).
Follow CLAUDE.md for environment-specific routing.
